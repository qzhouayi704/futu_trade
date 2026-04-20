"""
Ticker 轮询器

负责定期拉取所有监控股票的逐笔成交数据（Ticker），
并将新数据分发给 ScalpingEngine 处理。
"""

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from futu import RET_OK

from simple_trade.services.scalping.data_converter import row_to_tick
from simple_trade.utils.logger import print_status

if TYPE_CHECKING:
    from simple_trade.api.futu_client import FutuClient
    from simple_trade.services.scalping.engine import ScalpingEngine

logger = logging.getLogger("scalping.ticker_poller")

# 每次拉取的逐笔数量
_TICKER_NUM = 200
# 连续失败 N 次后临时降频
_FAIL_SKIP_THRESHOLD = 5
# 降频后跳过的周期数
_FAIL_SKIP_CYCLES = 4


class TickerPoller:
    """Ticker 轮询器 - 定期拉取逐笔成交数据"""

    def __init__(
        self,
        futu_client: "FutuClient",
        engine: "ScalpingEngine",
        rate_limiter,
        ticker_interval: float,
        state_manager=None,
    ):
        self._futu_client = futu_client
        self._engine = engine
        self._rate_limiter = rate_limiter
        self._ticker_interval = ticker_interval
        self._state_manager = state_manager

        # 去重：记录每只股票上次处理到的 ticker 序号
        self._last_ticker_idx: dict[str, int] = {}
        # 数据获取失败统计
        self._fetch_errors: dict[str, int] = {}
        # 连续失败跳过：剩余跳过周期数
        self._skip_remaining: dict[str, int] = {}

    def add_stock(self, stock_code: str) -> None:
        """添加股票到监控列表"""
        self._last_ticker_idx[stock_code] = -1
        self._fetch_errors[stock_code] = 0
        self._skip_remaining[stock_code] = 0

    def remove_stock(self, stock_code: str) -> None:
        """从监控列表移除股票"""
        self._last_ticker_idx.pop(stock_code, None)
        self._fetch_errors.pop(stock_code, None)
        self._skip_remaining.pop(stock_code, None)

    @property
    def _interval(self):
        return self._ticker_interval

    @_interval.setter
    def _interval(self, value):
        self._ticker_interval = value

    async def poll_loop(
        self, stocks_getter, running_checker, data_time_updater
    ) -> None:
        """Ticker 轮询主循环

        Args:
            stocks_getter: 获取当前监控股票列表的回调函数
            running_checker: 检查是否继续运行的回调函数
            data_time_updater: 更新数据接收时间的回调函数
        """
        logger.info("Ticker 轮询循环启动")

        # 等待股票列表就绪（最多等待 10 秒）
        for _ in range(10):
            if stocks_getter():
                break
            await asyncio.sleep(1.0)

        if not stocks_getter():
            logger.warning("Ticker 轮询循环启动超时：无股票需要监控")

        empty_cycle_count = 0  # 连续空数据计数器
        empty_alerted = False  # 是否已发送告警
        cycle_count = 0  # 总周期计数

        while running_checker():
            try:
                stocks = stocks_getter()
                if not stocks:
                    empty_cycle_count += 1
                    if empty_cycle_count >= 5 and not empty_alerted:
                        empty_alerted = True
                        logger.error(
                            f"[Scalping告警] Ticker 轮询连续 {empty_cycle_count} 个"
                            f"周期无股票数据，引擎可能处于空转状态"
                        )
                    await asyncio.sleep(1.0)
                    continue

                # 有数据时重置计数器
                if empty_cycle_count > 0:
                    empty_cycle_count = 0
                    empty_alerted = False

                cycle_count += 1
                cycle_start = time.time()
                success_count = 0
                fail_count = 0
                empty_count = 0
                new_tick_total = 0

                interval_per_stock = self._ticker_interval / len(stocks)
                # 最小间隔 300ms，避免股票数量多时请求过于密集
                interval_per_stock = max(interval_per_stock, 0.3)
                skip_count = 0
                for stock_code in stocks:
                    if not running_checker() or stock_code not in stocks_getter():
                        break

                    # 连续失败跳过机制
                    remaining = self._skip_remaining.get(stock_code, 0)
                    if remaining > 0:
                        self._skip_remaining[stock_code] = remaining - 1
                        skip_count += 1
                        continue

                    await self._rate_limiter.acquire()
                    result = await self._poll_ticker(stock_code, data_time_updater)
                    if result == 'ok':
                        success_count += 1
                        # 成功后重置失败计数
                        self._fetch_errors[stock_code] = 0
                    elif result == 'empty':
                        empty_count += 1
                    else:
                        fail_count += 1
                        # 连续失败达到阈值时启动跳过
                        err_cnt = self._fetch_errors.get(stock_code, 0)
                        if err_cnt >= _FAIL_SKIP_THRESHOLD:
                            self._skip_remaining[stock_code] = _FAIL_SKIP_CYCLES
                            logger.warning(
                                f"[Ticker降频] {stock_code} 连续失败{err_cnt}次，"
                                f"跳过接下来{_FAIL_SKIP_CYCLES}个周期"
                            )
                    await asyncio.sleep(interval_per_stock)

                # 每 6 个周期输出一次诊断摘要
                if cycle_count % 3 == 1:
                    cycle_duration = time.time() - cycle_start
                    # 统计有持续错误的股票
                    problem_stocks = [
                        f"{code}:{cnt}"
                        for code, cnt in self._fetch_errors.items()
                        if cnt >= 3
                    ]
                    problem_str = f" | 问题股: {problem_stocks[:5]}" if problem_stocks else ""
                    skip_str = f" 跳过:{skip_count}" if skip_count else ""
                    logger.info(
                        f"[Ticker诊断] 周期#{cycle_count} | "
                        f"{len(stocks)}只 | "
                        f"成功:{success_count} 空:{empty_count} 失败:{fail_count}{skip_str} | "
                        f"耗时:{cycle_duration:.1f}s | "
                        f"间隔:{interval_per_stock:.2f}s/只"
                        f"{problem_str}"
                    )

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"Ticker 轮询循环异常: {e}")
                await asyncio.sleep(1.0)

    async def _poll_ticker(self, stock_code: str, data_time_updater) -> str:
        """单次 Ticker 拉取与分发

        Returns:
            'ok' - 成功获取新数据, 'empty' - 无新数据, 'fail' - 获取失败
        """
        loop = asyncio.get_running_loop()
        try:
            ret, data = await loop.run_in_executor(
                self._futu_client.executor,
                lambda: self._futu_client.get_rt_ticker(
                    stock_code, num=_TICKER_NUM
                ),
            )
        except Exception as e:
            self._fetch_errors[stock_code] = (
                self._fetch_errors.get(stock_code, 0) + 1
            )
            err_count = self._fetch_errors[stock_code]
            if err_count <= 3 or err_count % 10 == 0:
                print_status(
                    f"【Scalping错误】[{stock_code}] Ticker获取失败 "
                    f"({type(e).__name__}), 累计{err_count}次",
                    "error",
                )
            return 'fail'

        if ret != RET_OK or data is None or data.empty:
            return 'empty'

        # 收到数据，重置错误计数
        self._fetch_errors[stock_code] = 0

        # 将完整 DataFrame 写入共享缓存（在去重之前）
        if self._state_manager is not None:
            try:
                self._state_manager.ticker_df_cache.set(stock_code, data)
            except Exception as e:
                logger.debug(f"[{stock_code}] 写入 ticker_df_cache 失败: {e}")

        last_idx = self._last_ticker_idx.get(stock_code, -1)
        new_rows = data[data.index > last_idx] if last_idx >= 0 else data
        if new_rows.empty:
            return 'empty'

        self._last_ticker_idx[stock_code] = int(new_rows.index[-1])
        data_time_updater(stock_code, time.time())

        for _, row in new_rows.iterrows():
            tick = row_to_tick(stock_code, row)
            if tick is not None:
                await self._engine.on_tick(stock_code, tick)

        return 'ok'
