"""
ScalpingEngine 协调器 - 管理 Scalping 生命周期，分发 Tick/OrderBook 数据给各计算器。

职责：
- 依赖注入（接收所有计算器/检测器实例）
- 委托 LifecycleManager 处理 start/stop/reconnect
- 委托 DataDispatcher 处理 on_tick/on_order_book
- 委托 CalculationScheduler 处理定期 POC/Delta 计算
- 对外状态查询接口（get_status、get_snapshot 等）
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from simple_trade.services.scalping.calculators.delta_calculator import DeltaCalculator
from simple_trade.services.scalping.models import OrderBookData, TickData
from simple_trade.services.scalping.calculators.poc_calculator import POCCalculator
from simple_trade.services.scalping.signal_engine import SignalEngine
from simple_trade.services.scalping.detectors.spoofing_filter import SpoofingFilter
from simple_trade.services.scalping.calculators.tape_velocity import TapeVelocityMonitor

from simple_trade.services.scalping.lifecycle_manager import (
    LifecycleManager,
    _MAX_RECONNECT_ATTEMPTS,  # noqa: F401 - re-export for backward compat
)
from simple_trade.services.scalping.data_dispatcher import DataDispatcher
from simple_trade.services.scalping.calc_scheduler import (
    CalculationScheduler,
    _POC_CALC_INTERVAL,  # noqa: F401 - re-export for backward compat
)

if TYPE_CHECKING:
    from simple_trade.services.scalping.central_scheduler import CentralScheduler
    from simple_trade.services.scalping.detectors.breakout_monitor import (
        BreakoutSurvivalMonitor,
    )
    from simple_trade.services.scalping.data_poller import ScalpingDataPoller
    from simple_trade.services.scalping.detectors.divergence_detector import (
        OrderFlowDivergenceDetector,
    )
    from simple_trade.services.scalping.detectors.stop_loss_monitor import (
        StopLossMonitor,
    )
    from simple_trade.services.scalping.calculators.tick_credibility import (
        TickCredibilityFilter,
    )
    from simple_trade.services.scalping.detectors.vwap_guard import (
        VwapExtensionGuard,
    )

logger = logging.getLogger("scalping")


@dataclass
class StartResult:
    """start() 方法的结构化返回结果"""
    added: list[str] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)
    filtered: list[str] = field(default_factory=list)
    rejected_reason: str | None = None


class ScalpingEngine:
    """日内超短线交易引擎协调器

    订阅 Tick/OrderBook 数据，分发给各计算器和检测器，协调信号生成。
    """

    MAX_STOCKS = 50
    MIN_TURNOVER_RATE = 0.1  # 换手率筛选阈值（%），与活跃个股筛选一致

    def __init__(
        self,
        subscription_helper,
        realtime_query,
        socket_manager,
        # 已实现的核心计算器
        delta_calculator: DeltaCalculator,
        tape_velocity: TapeVelocityMonitor,
        spoofing_filter: SpoofingFilter,
        poc_calculator: POCCalculator,
        signal_engine: SignalEngine,
        # 尚未实现的可选组件（Task 15.1 中注入）
        tick_credibility_filter: Optional["TickCredibilityFilter"] = None,
        divergence_detector: Optional["OrderFlowDivergenceDetector"] = None,
        breakout_monitor: Optional["BreakoutSurvivalMonitor"] = None,
        vwap_guard: Optional["VwapExtensionGuard"] = None,
        stop_loss_monitor: Optional["StopLossMonitor"] = None,
        # 数据轮询所需
        futu_client=None,
        # 数据持久化
        persistence=None,
        # 状态共享（可选，用于向 Strategy 系统共享指标）
        state_manager=None,
        # 统一订阅管理器（可选，用于订阅变化回调）
        subscription_manager=None,
    ):
        self._subscription_helper = subscription_helper
        self._realtime_query = realtime_query
        self._socket_manager = socket_manager

        # 核心计算器
        self._delta_calculator = delta_calculator
        self._tape_velocity = tape_velocity
        self._spoofing_filter = spoofing_filter
        self._poc_calculator = poc_calculator
        self._signal_engine = signal_engine

        # 可选组件
        self._tick_credibility_filter = tick_credibility_filter
        self._divergence_detector = divergence_detector
        self._breakout_monitor = breakout_monitor
        self._vwap_guard = vwap_guard
        self._stop_loss_monitor = stop_loss_monitor
        self._persistence = persistence
        self._state_manager = state_manager
        self._subscription_manager = subscription_manager

        # 数据调度器（优先使用 CentralScheduler，回退到 DataPoller）
        self._scheduler: Optional["CentralScheduler"] = None
        self._data_poller: Optional["ScalpingDataPoller"] = None
        if futu_client is not None:
            from simple_trade.services.scalping.central_scheduler import (
                CentralScheduler,
            )
            from simple_trade.services.scalping.rate_limiter import (
                RateLimiter,
            )
            self._scheduler = CentralScheduler(
                futu_client=futu_client,
                engine=self,
                subscription_manager=subscription_manager,  # 传入 subscription_manager
                rate_limiter=RateLimiter(),
                state_manager=state_manager,
            )

        # 子模块（LifecycleManager 需在 _subscription_manager 之后初始化，
        # 因为它在 __init__ 中注册订阅回调）
        self._lifecycle = LifecycleManager(self)
        self._dispatcher = DataDispatcher(self)
        self._calc_scheduler = CalculationScheduler(self)

    # ------------------------------------------------------------------
    # 生命周期（委托给 LifecycleManager）
    # ------------------------------------------------------------------

    async def start(
        self,
        stock_codes: list[str],
        turnover_rates: dict[str, float] | None = None,
    ) -> StartResult:
        """启动指定股票的 Scalping 数据流"""
        return await self._lifecycle.start(stock_codes, turnover_rates)

    async def stop(self, stock_codes: list[str] | None = None) -> None:
        """停止指定股票（或全部）的 Scalping 数据流"""
        await self._lifecycle.stop(stock_codes)

    # ------------------------------------------------------------------
    # 数据回调（委托给 DataDispatcher）
    # ------------------------------------------------------------------

    async def on_tick(self, stock_code: str, tick: TickData) -> None:
        """Tick 数据回调"""
        await self._dispatcher.on_tick(stock_code, tick)

    async def on_order_book(
        self, stock_code: str, order_book: OrderBookData
    ) -> None:
        """OrderBook 数据回调"""
        await self._dispatcher.on_order_book(stock_code, order_book)

    # ------------------------------------------------------------------
    # 内部方法（供 CentralScheduler 等外部模块调用）
    # ------------------------------------------------------------------

    @property
    def _reconnect_attempts(self) -> dict[str, int]:
        """重连计数代理（兼容旧代码/测试）"""
        return self._lifecycle._reconnect_attempts

    @_reconnect_attempts.setter
    def _reconnect_attempts(self, value: dict[str, int]) -> None:
        self._lifecycle._reconnect_attempts = value

    async def _reconnect(self, stock_code: str) -> None:
        """断线重连（供 CentralScheduler 调用）"""
        await self._lifecycle.reconnect(stock_code)

    def _publish_scalping_metrics(self, stock_code: str) -> None:
        """发布 Scalping 指标（供 CentralScheduler 调用）"""
        self._calc_scheduler.publish_scalping_metrics(stock_code)

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    @property
    def active_stocks(self) -> set[str]:
        """当前监控中的股票集合"""
        return self._lifecycle.active_stocks

    @property
    def day_highs(self) -> dict[str, float]:
        """各股票的日内最高价"""
        return self._lifecycle.day_highs

    def get_status(self) -> dict:
        """返回引擎状态：监控列表、各股票最后数据时间、健康状态"""
        return self._lifecycle.get_status()

    # ------------------------------------------------------------------
    # 快照查询
    # ------------------------------------------------------------------

    async def get_snapshot(self, stock_code: str) -> dict | None:
        """获取指定股票的 Scalping 数据快照（供前端初始加载）

        优先从内存中的计算器获取（更实时），内存为空时回退到数据库。
        股票不在监控中且数据库也无数据时返回 None。
        """
        snapshot = self._get_memory_snapshot(stock_code)

        has_data = (
            snapshot is not None
            and (snapshot["delta_data"] or snapshot["poc_data"] or snapshot["price_levels"])
        )
        if has_data:
            return snapshot

        if self._persistence is not None:
            db_snapshot = await self._get_db_snapshot(stock_code)
            if db_snapshot is not None:
                return db_snapshot

        return snapshot

    def _get_memory_snapshot(self, stock_code: str) -> dict | None:
        """从内存中的计算器获取快照"""
        if not self._lifecycle.is_active(stock_code):
            return None

        delta_data = [
            d.model_dump()
            for d in self._delta_calculator.get_recent_deltas(stock_code, 60)
        ]

        poc_data = None
        volume_profile = self._poc_calculator.get_volume_profile(stock_code)
        if volume_profile:
            poc_price = max(volume_profile, key=volume_profile.get)
            poc_data = {
                "stock_code": stock_code,
                "poc_price": poc_price,
                "poc_volume": volume_profile[poc_price],
                "volume_profile": {
                    str(k): v for k, v in volume_profile.items()
                },
                "timestamp": datetime.now().isoformat(),
            }

        price_levels = [
            l.model_dump()
            for l in self._spoofing_filter.get_active_levels(stock_code)
        ]

        vwap_value = None
        if self._vwap_guard is not None:
            vwap_value = self._vwap_guard.get_current_vwap(stock_code)

        return {
            "stock_code": stock_code,
            "delta_data": delta_data,
            "poc_data": poc_data,
            "price_levels": price_levels,
            "vwap_value": vwap_value,
            "events": [],  # 事件通过 socket 重播恢复，快照不再重复查询
        }

    async def _get_db_snapshot(self, stock_code: str) -> dict | None:
        """从数据库查询当日快照数据（委托给 persistence 层）"""
        return await self._persistence.get_today_snapshot(stock_code)

