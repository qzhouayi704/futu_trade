"""
ScalpingDataPoller - 数据轮询器

通过 FutuClient 的 pull-based API 定期拉取 Tick 和 OrderBook 数据，
转换为 TickData/OrderBookData 模型后喂给 ScalpingEngine。

轮询频率：
- Ticker: 每 1 秒
- OrderBook: 每 2 秒
"""

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Optional

from futu import RET_OK, SubType

from simple_trade.services.scalping.data_converter import (
    dict_to_order_book,
    parse_time_to_ms as _parse_time_to_ms,
    row_to_tick,
)
from simple_trade.services.scalping.models import (
    OrderBookData,
    OrderBookLevel,
    TickData,
    TickDirection,
)

if TYPE_CHECKING:
    from simple_trade.api.futu_client import FutuClient
    from simple_trade.services.scalping.engine import ScalpingEngine

logger = logging.getLogger("scalping.poller")

# 轮询间隔（秒）
_TICKER_INTERVAL = 1.0
_ORDER_BOOK_INTERVAL = 2.0
# 每次拉取的逐笔数量
_TICKER_NUM = 200


class ScalpingDataPoller:
    """Scalping 数据轮询器

    为每只股票启动三个 asyncio Task：
    - _poll_ticker_loop: 拉取逐笔成交
    - _poll_order_book_loop: 拉取十档盘口
    - _periodic_flush_loop: 定期 flush Delta/POC（不依赖 tick 到达）
    """

    def __init__(
        self,
        futu_client: "FutuClient",
        engine: "ScalpingEngine",
        state_manager=None,
    ):
        self._futu_client = futu_client
        self._engine = engine
        self._state_manager = state_manager
        # stock_code -> (ticker_task, order_book_task, flush_task)
        self._tasks: dict[str, tuple[asyncio.Task, asyncio.Task, asyncio.Task]] = {}
        # 去重：记录每只股票上次处理到的 ticker 序号
        self._last_ticker_idx: dict[str, int] = {}

    async def start(self, stock_code: str) -> None:
        """启动指定股票的数据轮询

        注意：不再负责订阅，订阅由 SubscriptionHelper 统一管理
        """
        if stock_code in self._tasks:
            logger.debug(f"[{stock_code}] 轮询已在运行中")
            return

        self._last_ticker_idx[stock_code] = -1

        ticker_task = asyncio.create_task(
            self._poll_ticker_loop(stock_code),
            name=f"scalping-ticker-{stock_code}",
        )
        ob_task = asyncio.create_task(
            self._poll_order_book_loop(stock_code),
            name=f"scalping-ob-{stock_code}",
        )
        flush_task = asyncio.create_task(
            self._periodic_flush_loop(stock_code),
            name=f"scalping-flush-{stock_code}",
        )
        self._tasks[stock_code] = (ticker_task, ob_task, flush_task)
        logger.info(f"[{stock_code}] 数据轮询已启动")

    async def stop(self, stock_code: str) -> None:
        """停止指定股票的数据轮询"""
        tasks = self._tasks.pop(stock_code, None)
        if tasks is None:
            return

        for task in tasks:
            task.cancel()
        # 等待任务真正结束
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._last_ticker_idx.pop(stock_code, None)
        logger.info(f"[{stock_code}] 数据轮询已停止")

    async def stop_all(self) -> None:
        """停止所有股票的数据轮询"""
        codes = list(self._tasks.keys())
        for code in codes:
            await self.stop(code)

    # ------------------------------------------------------------------
    # Ticker 轮询
    # ------------------------------------------------------------------

    async def _poll_ticker_loop(self, stock_code: str) -> None:
        """Ticker 轮询主循环"""
        logger.info(f"[{stock_code}] Ticker 轮询循环启动")
        while True:
            try:
                await self._poll_ticker(stock_code)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[{stock_code}] Ticker 轮询异常: {e}")
            await asyncio.sleep(_TICKER_INTERVAL)

    async def _poll_ticker(self, stock_code: str) -> None:
        """单次 Ticker 拉取与分发"""
        # futu_client 是同步调用，放到线程池执行避免阻塞事件循环
        loop = asyncio.get_running_loop()
        ret, data = await loop.run_in_executor(
            None,
            lambda: self._futu_client.get_rt_ticker(stock_code, num=_TICKER_NUM),
        )

        if ret != RET_OK:
            logger.debug(f"[{stock_code}] get_rt_ticker 失败: {data}")
            return

        if data is None or data.empty:
            return

        # 将完整 DataFrame 写入共享缓存（在去重之前）
        if self._state_manager is not None:
            try:
                self._state_manager.ticker_df_cache.set(stock_code, data)
            except Exception as e:
                logger.debug(f"[{stock_code}] 写入 ticker_df_cache 失败: {e}")

        last_idx = self._last_ticker_idx.get(stock_code, -1)
        # DataFrame 的 index 是递增的，用它做去重
        new_rows = data[data.index > last_idx] if last_idx >= 0 else data

        if new_rows.empty:
            return

        self._last_ticker_idx[stock_code] = int(new_rows.index[-1])

        for _, row in new_rows.iterrows():
            tick = self._row_to_tick(stock_code, row)
            if tick is not None:
                await self._engine.on_tick(stock_code, tick)

    def _row_to_tick(self, stock_code: str, row) -> Optional[TickData]:
        """将 DataFrame 行转换为 TickData（委托给 data_converter）"""
        return row_to_tick(stock_code, row)

    # ------------------------------------------------------------------
    # 定期 Flush（独立于 Tick 到达）
    # ------------------------------------------------------------------

    async def _periodic_flush_loop(self, stock_code: str) -> None:
        """定期 flush Delta 和 POC，不依赖 tick 到达频率

        每 _DELTA_FLUSH_INTERVAL 秒强制 flush 一次 Delta 累加器，
        每 _POC_CALC_INTERVAL 秒强制计算一次 POC。
        这样即使没有新 tick，前端也能持续收到柱图更新。
        """
        from simple_trade.services.scalping.engine import (
            _DELTA_FLUSH_INTERVAL,
            _POC_CALC_INTERVAL,
        )

        logger.info(f"[{stock_code}] 定期 Flush 循环启动")
        last_delta_flush = time.time()
        last_poc_calc = time.time()

        while True:
            try:
                await asyncio.sleep(1.0)  # 每秒检查一次
                now = time.time()

                # Delta flush
                if now - last_delta_flush >= _DELTA_FLUSH_INTERVAL:
                    last_delta_flush = now
                    try:
                        await self._engine._delta_calculator.flush_period(
                            stock_code
                        )
                    except Exception as e:
                        logger.debug(
                            f"[{stock_code}] 定期 flush_period 异常: {e}"
                        )

                # POC 计算
                if now - last_poc_calc >= _POC_CALC_INTERVAL:
                    last_poc_calc = now
                    try:
                        await self._engine._poc_calculator.calculate_poc(
                            stock_code
                        )
                    except Exception as e:
                        logger.debug(
                            f"[{stock_code}] 定期 calculate_poc 异常: {e}"
                        )

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[{stock_code}] 定期 Flush 异常: {e}")

    # ------------------------------------------------------------------
    # OrderBook 轮询
    # ------------------------------------------------------------------

    async def _poll_order_book_loop(self, stock_code: str) -> None:
        """OrderBook 轮询主循环"""
        logger.info(f"[{stock_code}] OrderBook 轮询循环启动")
        while True:
            try:
                await self._poll_order_book(stock_code)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[{stock_code}] OrderBook 轮询异常: {e}")
            await asyncio.sleep(_ORDER_BOOK_INTERVAL)

    async def _poll_order_book(self, stock_code: str) -> None:
        """单次 OrderBook 拉取与分发"""
        loop = asyncio.get_running_loop()
        ret, data = await loop.run_in_executor(
            None,
            lambda: self._futu_client.get_order_book(stock_code),
        )

        if ret != RET_OK:
            logger.debug(f"[{stock_code}] get_order_book 失败: {data}")
            return

        if data is None:
            return

        order_book = self._dict_to_order_book(stock_code, data)
        if order_book is not None:
            await self._engine.on_order_book(stock_code, order_book)

    def _dict_to_order_book(
        self, stock_code: str, data: dict
    ) -> Optional[OrderBookData]:
        """将 futu 返回的 dict 转换为 OrderBookData（委托给 data_converter）"""
        return dict_to_order_book(stock_code, data)
