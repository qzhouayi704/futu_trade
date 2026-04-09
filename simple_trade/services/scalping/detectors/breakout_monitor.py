"""
突破生存法则监控器（Breakout Survival Monitor）

在突破发生后监控 3-5 秒内的价格推进和流速变化，区分真突破和假突破。

核心逻辑：
- 价格突破日内高点或红色阻力线时启动监控计时器
- 计时器到期时评估流速和价格推进
- 流速回落至 3 倍以下且价格未推进 → FAKE_BREAKOUT_ALERT
- 流速维持 3 倍以上且价格推进至少 2 Tick → TRUE_BREAKOUT_CONFIRM
- 支持 market_type 参数：美股默认 3.0 秒，港股默认 5.0 秒
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from simple_trade.services.scalping.models import (
    FakeBreakoutAlertData,
    PriceLevelData,
    PriceLevelSide,
    TickData,
    TrueBreakoutConfirmData,
)
from simple_trade.websocket.events import SocketEvent

if TYPE_CHECKING:
    from simple_trade.services.scalping.detectors.spoofing_filter import SpoofingFilter
    from simple_trade.services.scalping.calculators.tape_velocity import (
        TapeVelocityMonitor,
    )

logger = logging.getLogger("scalping")

# market_type 对应的默认 survival_seconds
_DEFAULT_SURVIVAL: dict[str, float] = {
    "us": 3.0,
    "hk": 5.0,
}


@dataclass
class _BreakoutEntry:
    """单次突破监控条目"""
    breakout_price: float       # 突破时价格
    baseline_velocity: float    # 突破时流速基准值
    start_time: float           # 监控开始时间（秒）
    highest_price: float = 0.0  # 监控期间最高价


@dataclass
class _StockBreakoutState:
    """单个股票的突破监控状态"""
    # 活跃的突破监控列表
    active_monitors: list[_BreakoutEntry] = field(default_factory=list)
    # 日内高点
    day_high: float = 0.0
    # 当前价格
    current_price: float = 0.0
    # 最近 tick 时间（秒）
    last_tick_time: float = 0.0


class BreakoutSurvivalMonitor:
    """突破生存法则监控器

    在突破发生后监控价格推进和流速变化，区分真突破和假突破。
    依赖 TapeVelocityMonitor 获取流速，依赖 SpoofingFilter 获取阻力线。
    """

    def __init__(
        self,
        socket_manager,
        tape_velocity: "TapeVelocityMonitor",
        spoofing_filter: "SpoofingFilter",
        market_type: str = "us",
        survival_seconds: float | None = None,
        velocity_multiplier: float = 3.0,
        min_advance_ticks: int = 2,
        tick_size: float = 0.01,
    ):
        """初始化 BreakoutSurvivalMonitor

        Args:
            socket_manager: SocketManager 实例
            tape_velocity: TapeVelocityMonitor 实例
            spoofing_filter: SpoofingFilter 实例
            market_type: 市场类型（"us" 或 "hk"），自动选择默认窗口
            survival_seconds: 监控窗口（秒），None 时按 market_type 自动选择
            velocity_multiplier: 流速维持倍数阈值，默认 3.0
            min_advance_ticks: 最小价格推进 Tick 数，默认 2
            tick_size: 最小价格变动单位，默认 0.01
        """
        self._socket_manager = socket_manager
        self._tape_velocity = tape_velocity
        self._spoofing_filter = spoofing_filter
        self._market_type = market_type
        self._survival_seconds = (
            survival_seconds
            if survival_seconds is not None
            else _DEFAULT_SURVIVAL.get(market_type, 3.0)
        )
        self._velocity_multiplier = velocity_multiplier
        self._min_advance_ticks = min_advance_ticks
        self._tick_size = tick_size
        self._persistence = None
        self._states: dict[str, _StockBreakoutState] = {}

    def _get_state(self, stock_code: str) -> _StockBreakoutState:
        """获取或创建股票状态"""
        if stock_code not in self._states:
            self._states[stock_code] = _StockBreakoutState()
        return self._states[stock_code]

    def on_tick(self, stock_code: str, tick: TickData) -> None:
        """处理 Tick 数据，检测突破并管理活跃的监控计时器

        Args:
            stock_code: 股票代码
            tick: 逐笔成交数据
        """
        state = self._get_state(stock_code)
        now_sec = tick.timestamp / 1000.0
        state.current_price = tick.price
        state.last_tick_time = now_sec

        # 更新日内高点
        if tick.price > state.day_high:
            state.day_high = tick.price

        # 更新活跃监控中的最高价
        for entry in state.active_monitors:
            if tick.price > entry.highest_price:
                entry.highest_price = tick.price

        # 检测是否触发新的突破（价格突破日内高点或红色阻力线）
        self._check_breakout_trigger(stock_code, tick.price, now_sec)

    def _check_breakout_trigger(
        self, stock_code: str, price: float, now_sec: float
    ) -> None:
        """检测是否触发突破，启动监控

        突破条件：
        1. 价格突破日内高点（price >= day_high 且 day_high > 0）
        2. 价格突破红色阻力线
        """
        state = self._get_state(stock_code)

        # 避免对同一价格重复启动监控
        existing_prices = {
            e.breakout_price for e in state.active_monitors
        }

        # 检查是否突破红色阻力线
        resistance_levels = [
            lv for lv in self._spoofing_filter.get_active_levels(stock_code)
            if lv.side == PriceLevelSide.RESISTANCE
        ]
        for lv in resistance_levels:
            if price >= lv.price and lv.price not in existing_prices:
                baseline = self._tape_velocity.get_baseline_avg(stock_code)
                if baseline > 0:
                    self.start_monitoring(stock_code, lv.price, baseline)

    def start_monitoring(
        self,
        stock_code: str,
        breakout_price: float,
        baseline_velocity: float,
    ) -> None:
        """启动突破监控计时器

        Args:
            stock_code: 股票代码
            breakout_price: 突破时价格
            baseline_velocity: 突破时流速基准值
        """
        state = self._get_state(stock_code)
        now_sec = state.last_tick_time if state.last_tick_time > 0 else 0.0

        entry = _BreakoutEntry(
            breakout_price=breakout_price,
            baseline_velocity=baseline_velocity,
            start_time=now_sec,
            highest_price=state.current_price,
        )
        state.active_monitors.append(entry)

        logger.info(
            f"启动突破监控 {stock_code}: "
            f"突破价={breakout_price}, 基准流速={baseline_velocity:.1f}, "
            f"窗口={self._survival_seconds}s"
        )

    async def evaluate_survival(
        self, stock_code: str,
    ) -> FakeBreakoutAlertData | TrueBreakoutConfirmData | None:
        """评估所有到期的突破监控

        计时器到期时评估：
        - 流速回落至 velocity_multiplier 倍以下且价格未推进 → FAKE_BREAKOUT_ALERT
        - 流速维持 velocity_multiplier 倍以上且价格推进至少 min_advance_ticks → TRUE_BREAKOUT_CONFIRM

        Args:
            stock_code: 股票代码

        Returns:
            FakeBreakoutAlertData 或 TrueBreakoutConfirmData 或 None
        """
        state = self._get_state(stock_code)
        now_sec = state.last_tick_time

        if not state.active_monitors:
            return None

        # 查找已到期的监控
        expired: list[_BreakoutEntry] = []
        remaining: list[_BreakoutEntry] = []

        for entry in state.active_monitors:
            elapsed = now_sec - entry.start_time
            if elapsed >= self._survival_seconds:
                expired.append(entry)
            else:
                remaining.append(entry)

        state.active_monitors = remaining

        # 评估到期的监控（返回第一个结果）
        for entry in expired:
            result = await self._evaluate_entry(stock_code, entry, now_sec)
            if result is not None:
                return result

        return None

    async def _evaluate_entry(
        self,
        stock_code: str,
        entry: _BreakoutEntry,
        now_sec: float,
    ) -> FakeBreakoutAlertData | TrueBreakoutConfirmData | None:
        """评估单个到期的突破监控条目

        Args:
            stock_code: 股票代码
            entry: 突破监控条目
            now_sec: 当前时间（秒）

        Returns:
            假突破或真突破事件数据，或 None
        """
        state = self._get_state(stock_code)
        current_price = state.current_price

        # 计算流速倍数
        current_window_count = self._tape_velocity.get_window_count(
            stock_code
        )
        if entry.baseline_velocity > 0:
            velocity_ratio = current_window_count / entry.baseline_velocity
        else:
            velocity_ratio = 0.0

        # 计算价格推进 Tick 数
        price_advance = entry.highest_price - entry.breakout_price
        advance_ticks = round(price_advance / self._tick_size) if self._tick_size > 0 else 0

        # 判定：流速维持 + 价格推进 → 真突破
        velocity_maintained = velocity_ratio >= self._velocity_multiplier
        price_advanced = advance_ticks >= self._min_advance_ticks

        elapsed = now_sec - entry.start_time

        if velocity_maintained and price_advanced:
            return await self._emit_true_breakout(
                stock_code, entry, current_price,
                velocity_ratio, advance_ticks, elapsed,
            )
        else:
            return await self._emit_fake_breakout(
                stock_code, entry, current_price,
                velocity_ratio, elapsed,
            )

    async def _emit_fake_breakout(
        self,
        stock_code: str,
        entry: _BreakoutEntry,
        current_price: float,
        velocity_ratio: float,
        elapsed: float,
    ) -> FakeBreakoutAlertData:
        """推送假突破警报事件"""
        alert = FakeBreakoutAlertData(
            stock_code=stock_code,
            breakout_price=entry.breakout_price,
            current_price=current_price,
            velocity_decay_ratio=round(velocity_ratio, 2),
            survival_seconds=round(elapsed, 2),
            timestamp=datetime.now().isoformat(),
        )

        try:
            await self._socket_manager.emit_to_all(
                SocketEvent.FAKE_BREAKOUT_ALERT,
                alert.model_dump(),
            )
            logger.info(
                f"假突破警报 {stock_code}: "
                f"突破价={entry.breakout_price}, "
                f"当前价={current_price}, "
                f"流速比={velocity_ratio:.1f}"
            )
        except Exception as e:
            logger.warning(f"推送 FAKE_BREAKOUT_ALERT 失败: {e}")
        if self._persistence:
            self._persistence.enqueue_event("fake_breakout", alert.model_dump())

        return alert

    async def _emit_true_breakout(
        self,
        stock_code: str,
        entry: _BreakoutEntry,
        current_price: float,
        velocity_ratio: float,
        advance_ticks: int,
        elapsed: float,
    ) -> TrueBreakoutConfirmData:
        """推送真突破确认事件"""
        confirm = TrueBreakoutConfirmData(
            stock_code=stock_code,
            breakout_price=entry.breakout_price,
            current_price=current_price,
            velocity_multiplier=round(velocity_ratio, 2),
            advance_ticks=advance_ticks,
            timestamp=datetime.now().isoformat(),
        )

        try:
            await self._socket_manager.emit_to_all(
                SocketEvent.TRUE_BREAKOUT_CONFIRM,
                confirm.model_dump(),
            )
            logger.info(
                f"真突破确认 {stock_code}: "
                f"突破价={entry.breakout_price}, "
                f"当前价={current_price}, "
                f"推进={advance_ticks} Tick"
            )
        except Exception as e:
            logger.warning(f"推送 TRUE_BREAKOUT_CONFIRM 失败: {e}")
        if self._persistence:
            self._persistence.enqueue_event("true_breakout", confirm.model_dump())

        return confirm

    def get_active_monitors(self, stock_code: str) -> list[dict]:
        """获取当前活跃的突破监控列表

        Args:
            stock_code: 股票代码

        Returns:
            活跃监控条目的字典列表
        """
        state = self._get_state(stock_code)
        return [
            {
                "breakout_price": e.breakout_price,
                "baseline_velocity": e.baseline_velocity,
                "start_time": e.start_time,
                "highest_price": e.highest_price,
            }
            for e in state.active_monitors
        ]

    def reset(self, stock_code: str) -> None:
        """重置指定股票的突破监控状态

        Args:
            stock_code: 股票代码
        """
        if stock_code in self._states:
            del self._states[stock_code]
        logger.info(f"已重置 {stock_code} 的突破监控状态")
