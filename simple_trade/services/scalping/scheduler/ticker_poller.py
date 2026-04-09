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

    def add_stock(self, stock_code: str) -> None:
        """添加股票到监控列表"""
        self._last_ticker_idx[stock_code] = -1
        self._fetch_errors[stock_code] = 0

    def remove_stock(self, stock_code: str) -> None:
        """从监控列表移除股票"""
        self._last_ticker_idx.pop(stock_code, None)
        self._fetch_errors.pop(stock_code, None)

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

        while running_checker():
            try:
                stocks = stocks_getter()
                if not stocks:
                    await asyncio.sleep(1.0)
                    continue

                interval_per_stock = self._ticker_interval / len(stocks)
                for stock_code in stocks:
                    if not running_checker() or stock_code not in stocks_getter():
                        break
                    await self._rate_limiter.acquire()
                    await self._poll_ticker(stock_code, data_time_updater)
                    await asyncio.sleep(interval_per_stock)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"Ticker 轮询循环异常: {e}")
                await asyncio.sleep(1.0)

    async def _poll_ticker(self, stock_code: str, data_time_updater) -> None:
        """单次 Ticker 拉取与分发"""
        loop = asyncio.get_running_loop()
        try:
            ret, data = await loop.run_in_executor(
                None,
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
            return

        if ret != RET_OK or data is None or data.empty:
            return

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
            return

        self._last_ticker_idx[stock_code] = int(new_rows.index[-1])
        data_time_updater(stock_code, time.time())

        for _, row in new_rows.iterrows():
            tick = row_to_tick(stock_code, row)
            if tick is not None:
                await self._engine.on_tick(stock_code, tick)
