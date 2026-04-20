"""
集中调度器（Central Scheduler）

统一管理所有被监控股票的 Ticker/OrderBook 轮询，替代逐只股票独立 Task 的模式。
在每个轮询间隔内均匀分散各股票的查询时间，通过 RateLimiter 控制 API 调用频率。

核心设计：
- 3 个共享循环（Ticker 轮询、OrderBook 轮询、Flush）+ 1 个健康检查循环
- 所有股票共享这 4 个 asyncio Task，动态增减股票无需创建/销毁 Task
- 数据转换使用 data_converter 模块的纯函数

重构说明：
- 拆分自原 central_scheduler.py (501行 → 4个文件)
- 使用组合模式，将4个独立循环拆分到独立组件
- CentralScheduler 作为协调器，管理生命周期和股票列表
"""

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Optional

from simple_trade.services.scalping.rate_limiter import RateLimiter
from .scheduler.ticker_poller import TickerPoller
from .scheduler.orderbook_poller import OrderBookPoller
from .scheduler.health_monitor import HealthMonitor

if TYPE_CHECKING:
    from simple_trade.api.futu_client import FutuClient
    from simple_trade.services.scalping.engine import ScalpingEngine

logger = logging.getLogger("scalping.scheduler")


class CentralScheduler:
    """集中调度器 - 统一管理所有股票的 Ticker/OrderBook 轮询"""

    def __init__(
        self,
        futu_client: "FutuClient",
        engine: "ScalpingEngine",
        subscription_manager,
        rate_limiter: Optional[RateLimiter] = None,
        ticker_interval: float = 15.0,
        order_book_interval: float = 25.0,
        state_manager=None,
    ):
        self._futu_client = futu_client
        self._engine = engine
        self._subscription_manager = subscription_manager
        self._rate_limiter = rate_limiter or RateLimiter()
        self._ticker_interval = ticker_interval
        self._order_book_interval = order_book_interval
        self._state_manager = state_manager

        # 被监控的股票集合（线程安全由 asyncio 单线程保证）
        self._stocks: set[str] = set()
        # 健康状态：stock_code -> 最后收到数据的时间
        self._last_data_time: dict[str, float] = {}

        # 组件：Ticker轮询器、OrderBook轮询器、健康监控器
        self._ticker_poller = TickerPoller(
            futu_client, engine, self._rate_limiter, ticker_interval, state_manager
        )
        self._orderbook_poller = OrderBookPoller(
            futu_client, engine, self._rate_limiter, order_book_interval
        )
        self._health_monitor = HealthMonitor(engine, subscription_manager)

        # asyncio Tasks
        self._tasks: list[asyncio.Task] = []
        self._running = False

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动调度器（4 个共享循环）"""
        if self._running:
            return
        self._running = True

        # 延迟启动：等待 Quote Pipeline 先稳定，避免初始并发请求压垮 OpenD
        logger.info("CentralScheduler 延迟 15 秒启动，等待行情管道稳定...")
        await asyncio.sleep(15)

        # 注册推送处理器（推送为主，轮询为 fallback）
        try:
            from .scheduler.push_handlers import (
                ScalpingTickerHandler, ScalpingOrderBookHandler
            )
            ticker_handler = ScalpingTickerHandler(
                data_time_updater=self._update_data_time
            )
            ob_handler = ScalpingOrderBookHandler(
                data_time_updater=self._update_data_time
            )
            if self._futu_client.register_scalping_handlers(ticker_handler, ob_handler):
                # 推送注册成功，大幅提高轮询间隔（轮询仅作 fallback）
                self._ticker_poller._interval = 60.0
                self._orderbook_poller._interval = 90.0
                logger.info("推送模式已启用，轮询降级为 fallback (60s/90s)")
            else:
                logger.info("推送注册失败，保持原轮询模式")
        except Exception as e:
            logger.warning(f"推送处理器初始化失败，保持原轮询模式: {e}")

        # 创建4个共享循环任务
        self._tasks = [
            asyncio.create_task(
                self._ticker_poller.poll_loop(
                    stocks_getter=lambda: list(self._stocks),
                    running_checker=lambda: self._running,
                    data_time_updater=self._update_data_time,
                ),
                name="scheduler-ticker",
            ),
            asyncio.create_task(
                self._orderbook_poller.poll_loop(
                    stocks_getter=lambda: list(self._stocks),
                    running_checker=lambda: self._running,
                    data_time_updater=self._update_data_time,
                ),
                name="scheduler-ob",
            ),
            asyncio.create_task(
                self._health_monitor.flush_loop(
                    stocks_getter=lambda: list(self._stocks),
                    running_checker=lambda: self._running,
                ),
                name="scheduler-flush",
            ),
            asyncio.create_task(
                self._health_monitor.health_check_loop(
                    stocks_getter=lambda: list(self._stocks),
                    running_checker=lambda: self._running,
                    last_data_time_getter=self._get_last_data_time,
                ),
                name="scheduler-health",
            ),
        ]
        logger.info("CentralScheduler 已启动")

    async def stop(self) -> None:
        """停止调度器"""
        self._running = False
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        logger.info("CentralScheduler 已停止")

    # ------------------------------------------------------------------
    # 股票管理
    # ------------------------------------------------------------------

    async def add_stocks(self, stock_codes: list[str]) -> None:
        """将股票加入监控队列

        注意：不再负责订阅，订阅由 SubscriptionHelper 统一管理
        """
        new_codes = [c for c in stock_codes if c not in self._stocks]
        if not new_codes:
            return

        # 添加到监控列表
        for code in new_codes:
            self._stocks.add(code)
            self._last_data_time[code] = time.time()
            # 通知各组件
            self._ticker_poller.add_stock(code)
            self._orderbook_poller.add_stock(code)
            self._health_monitor.add_stock(code)

        logger.info(f"已加入监控: {new_codes}，当前共 {len(self._stocks)} 只")

    async def remove_stocks(self, stock_codes: list[str]) -> None:
        """将股票从监控队列移除"""
        for code in stock_codes:
            self._stocks.discard(code)
            self._last_data_time.pop(code, None)
            # 通知各组件
            self._ticker_poller.remove_stock(code)
            self._orderbook_poller.remove_stock(code)
            self._health_monitor.remove_stock(code)

        if stock_codes:
            logger.info(f"已移除监控: {stock_codes}，当前共 {len(self._stocks)} 只")

    @property
    def monitored_stocks(self) -> set[str]:
        """当前被监控的股票集合"""
        return set(self._stocks)

    def get_monitored_stocks(self) -> list[str]:
        """获取当前监控的股票列表（便捷方法）"""
        return list(self._stocks)

    def get_last_data_time(self, stock_code: str) -> Optional[float]:
        """获取指定股票最后收到数据的时间"""
        return self._last_data_time.get(stock_code)

    def is_healthy(self, stock_code: str) -> bool:
        """检查指定股票的数据流是否健康"""
        last = self._last_data_time.get(stock_code)
        if last is None:
            return False
        # 数据超时阈值：60秒
        return (time.time() - last) < 60.0

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    def _update_data_time(self, stock_code: str, timestamp: float) -> None:
        """更新股票最后收到数据的时间"""
        self._last_data_time[stock_code] = timestamp

    def _get_last_data_time(self, stock_code: str) -> Optional[float]:
        """获取股票最后收到数据的时间（供健康监控器使用）"""
        return self._last_data_time.get(stock_code)
