"""
订单流背离检测器（Order Flow Divergence Detector）

检测价格与订单流方向背离的诱多/诱空陷阱。

诱多检测（Bull Trap）：
- 价格创日内新高
- 当前周期 Delta 为负值或低于近 20 周期 Delta 均值的 20%

诱空检测（Bear Trap）：
- 价格跌破已标记绿色支撑线（< 3 Tick）
- 大量主动卖单涌入但价格 3 秒内波动 < 2 Tick（Absorption 现象）

同一股票同类型警报触发后 15 秒冷却期。
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from simple_trade.services.scalping.models import (
    PriceLevelData,
    PriceLevelSide,
    TickData,
    TickDirection,
    TrapAlertData,
    TrapAlertType,
)
from simple_trade.websocket.events import SocketEvent

if TYPE_CHECKING:
    from simple_trade.services.scalping.calculators.delta_calculator import (
        DeltaCalculator,
    )

logger = logging.getLogger("scalping")


@dataclass
class _TickRecord:
    """用于 Absorption 检测的 Tick 记录"""
    price: float
    volume: int
    direction: TickDirection
    timestamp_sec: float  # Unix 秒


@dataclass
class _StockDivergenceState:
    """单个股票的背离检测状态"""
    day_high: float = 0.0
    # 冷却期：trap_type -> 冷却结束时间（秒）
    cooldown_until: dict = field(default_factory=dict)
    # 最近 Tick 记录，用于 Absorption 检测
    recent_ticks: deque = field(
        default_factory=lambda: deque(maxlen=500)
    )


class OrderFlowDivergenceDetector:
    """订单流背离检测器

    检测价格与订单流方向背离的诱多/诱空陷阱。
    依赖 DeltaCalculator 获取 Delta 值。
    """

    def __init__(
        self,
        socket_manager,
        delta_calculator: "DeltaCalculator",
        cooldown_seconds: float = 15.0,
        delta_divergence_ratio: float = 0.2,
        tick_size: float = 0.01,
        absorption_window_seconds: float = 3.0,
        absorption_max_price_ticks: int = 2,
        support_proximity_ticks: int = 3,
    ):
        """初始化 OrderFlowDivergenceDetector

        Args:
            socket_manager: SocketManager 实例
            delta_calculator: DeltaCalculator 实例
            cooldown_seconds: 同类型警报冷却期（秒），默认 15.0
            delta_divergence_ratio: Delta 背离比例阈值，默认 0.2
            tick_size: 最小价格变动单位，默认 0.01
            absorption_window_seconds: Absorption 时间窗口（秒），默认 3.0
            absorption_max_price_ticks: Absorption 最大价格波动 Tick 数，默认 2
            support_proximity_ticks: 支撑线接近判定 Tick 数，默认 3
        """
        self._socket_manager = socket_manager
        self._delta_calculator = delta_calculator
        self._cooldown_seconds = cooldown_seconds
        self._delta_divergence_ratio = delta_divergence_ratio
        self._tick_size = tick_size
        self._absorption_window_seconds = absorption_window_seconds
        self._absorption_max_price_ticks = absorption_max_price_ticks
        self._support_proximity_ticks = support_proximity_ticks
        self._persistence = None
        self._states: dict[str, _StockDivergenceState] = {}

    def _get_state(self, stock_code: str) -> _StockDivergenceState:
        """获取或创建股票状态"""
        if stock_code not in self._states:
            self._states[stock_code] = _StockDivergenceState()
        return self._states[stock_code]

    def on_tick(self, stock_code: str, tick: TickData) -> None:
        """处理 Tick 数据，更新日内高点和价格历史

        Args:
            stock_code: 股票代码
            tick: 逐笔成交数据
        """
        state = self._get_state(stock_code)
        now_sec = tick.timestamp / 1000.0

        # 更新日内高点
        if tick.price > state.day_high:
            state.day_high = tick.price

        # 记录 Tick 用于 Absorption 检测
        state.recent_ticks.append(
            _TickRecord(
                price=tick.price,
                volume=tick.volume,
                direction=tick.direction,
                timestamp_sec=now_sec,
            )
        )

        # 清理超出时间窗口的旧记录
        cutoff = now_sec - self._absorption_window_seconds
        while (
            state.recent_ticks
            and state.recent_ticks[0].timestamp_sec < cutoff
        ):
            state.recent_ticks.popleft()

    async def check_bull_trap(
        self, stock_code: str, current_price: float
    ) -> Optional[TrapAlertData]:
        """检测诱多：价格创新高 + Delta 背离

        条件：
        1. 价格创日内新高（current_price >= day_high）
        2. 当前周期 Delta 为负值或低于近 20 周期 Delta 均值的 20%

        满足条件且不在冷却期时通过 SocketManager 推送 TRAP_ALERT 事件。

        Args:
            stock_code: 股票代码
            current_price: 当前价格

        Returns:
            TrapAlertData 或 None
        """
        state = self._get_state(stock_code)

        # 条件 1：价格必须创日内新高
        if state.day_high <= 0 or current_price < state.day_high:
            return None

        # 条件 2：检查 Delta 背离
        recent_deltas = self._delta_calculator.get_recent_deltas(
            stock_code, count=20
        )
        if not recent_deltas:
            return None

        current_delta = recent_deltas[-1].delta
        delta_values = [d.delta for d in recent_deltas]
        delta_avg = sum(delta_values) / len(delta_values)

        # Delta 背离：负值或低于均值的 20%
        is_divergent = (
            current_delta < 0
            or current_delta < delta_avg * self._delta_divergence_ratio
        )
        if not is_divergent:
            return None

        # 冷却期检查
        if self.is_in_cooldown(stock_code, TrapAlertType.BULL_TRAP):
            return None

        # 设置冷却期
        now_sec = self._get_current_time(stock_code)
        state.cooldown_until[TrapAlertType.BULL_TRAP] = (
            now_sec + self._cooldown_seconds
        )

        alert = TrapAlertData(
            stock_code=stock_code,
            trap_type=TrapAlertType.BULL_TRAP,
            current_price=current_price,
            reference_price=state.day_high,
            delta_value=current_delta,
            timestamp=datetime.now().isoformat(),
        )

        await self._emit_trap_alert(alert)

        logger.info(
            f"诱多警报 {stock_code}: 价格={current_price}, "
            f"高点={state.day_high}, Delta={current_delta:.0f}, "
            f"均值={delta_avg:.0f}"
        )
        return alert

    async def check_bear_trap(
        self,
        stock_code: str,
        current_price: float,
        support_levels: list[PriceLevelData],
    ) -> Optional[TrapAlertData]:
        """检测诱空：价格跌破支撑 + Absorption 现象

        条件：
        1. 价格跌破已标记绿色支撑线（距离 < 3 Tick）
        2. 大量主动卖单涌入但价格 3 秒内波动 < 2 Tick

        满足条件且不在冷却期时通过 SocketManager 推送 TRAP_ALERT 事件。

        Args:
            stock_code: 股票代码
            current_price: 当前价格
            support_levels: 已标记的支撑线列表

        Returns:
            TrapAlertData 或 None
        """
        state = self._get_state(stock_code)

        # 筛选绿色支撑线
        supports = [
            lv for lv in support_levels
            if lv.side == PriceLevelSide.SUPPORT
        ]
        if not supports:
            return None

        # 查找被跌破的支撑线（价格低于支撑且距离 < 3 Tick）
        proximity = self._support_proximity_ticks * self._tick_size
        broken_support = None
        for lv in supports:
            price_diff = lv.price - current_price
            if 0 < price_diff <= proximity:
                broken_support = lv
                break

        if broken_support is None:
            return None

        # 检查 Absorption 现象
        absorption = self._check_absorption(state)
        if absorption is None:
            return None

        sell_volume, delta_value = absorption

        # 冷却期检查
        if self.is_in_cooldown(stock_code, TrapAlertType.BEAR_TRAP):
            return None

        # 设置冷却期
        now_sec = self._get_current_time(stock_code)
        state.cooldown_until[TrapAlertType.BEAR_TRAP] = (
            now_sec + self._cooldown_seconds
        )

        alert = TrapAlertData(
            stock_code=stock_code,
            trap_type=TrapAlertType.BEAR_TRAP,
            current_price=current_price,
            reference_price=broken_support.price,
            delta_value=delta_value,
            sell_volume=sell_volume,
            timestamp=datetime.now().isoformat(),
        )

        await self._emit_trap_alert(alert)

        logger.info(
            f"诱空警报 {stock_code}: 价格={current_price}, "
            f"支撑={broken_support.price}, 卖单量={sell_volume}"
        )
        return alert

    def _check_absorption(
        self, state: _StockDivergenceState
    ) -> Optional[tuple[int, float]]:
        """检查 Absorption 现象：大量卖单但价格停滞

        条件：
        - 最近 3 秒内有主动卖单
        - 价格波动 < absorption_max_price_ticks 个 Tick

        Returns:
            (sell_volume, delta_value) 或 None
        """
        if len(state.recent_ticks) < 2:
            return None

        latest_time = state.recent_ticks[-1].timestamp_sec
        cutoff = latest_time - self._absorption_window_seconds
        window_ticks = [
            t for t in state.recent_ticks
            if t.timestamp_sec >= cutoff
        ]

        if len(window_ticks) < 2:
            return None

        # 统计卖单量
        sell_volume = sum(
            t.volume for t in window_ticks
            if t.direction == TickDirection.SELL
        )
        if sell_volume <= 0:
            return None

        # 价格波动范围
        prices = [t.price for t in window_ticks]
        price_range = max(prices) - min(prices)
        max_range = self._absorption_max_price_ticks * self._tick_size

        # Absorption：大量卖单但价格停滞（波动 < max_range）
        if price_range >= max_range:
            return None

        buy_volume = sum(
            t.volume for t in window_ticks
            if t.direction == TickDirection.BUY
        )
        delta_value = float(buy_volume - sell_volume)

        return sell_volume, delta_value

    def is_in_cooldown(
        self, stock_code: str, trap_type: TrapAlertType
    ) -> bool:
        """检查指定股票的指定警报类型是否在冷却期内

        Args:
            stock_code: 股票代码
            trap_type: 警报类型

        Returns:
            True 表示在冷却期内
        """
        state = self._get_state(stock_code)
        cooldown_end = state.cooldown_until.get(trap_type, 0.0)
        now_sec = self._get_current_time(stock_code)
        return now_sec < cooldown_end

    def update_day_high(self, stock_code: str, price: float) -> None:
        """更新日内高点

        Args:
            stock_code: 股票代码
            price: 新的价格
        """
        state = self._get_state(stock_code)
        if price > state.day_high:
            state.day_high = price

    def reset(self, stock_code: str) -> None:
        """重置指定股票的状态（日内高点、冷却期等）

        Args:
            stock_code: 股票代码
        """
        if stock_code in self._states:
            del self._states[stock_code]
        logger.info(f"已重置 {stock_code} 的背离检测状态")

    def _get_current_time(self, stock_code: str) -> float:
        """获取当前时间（基于最近 Tick 的时间戳）"""
        state = self._get_state(stock_code)
        if state.recent_ticks:
            return state.recent_ticks[-1].timestamp_sec
        return 0.0

    async def _emit_trap_alert(self, alert: TrapAlertData) -> None:
        """推送诱多/诱空警报事件"""
        data = alert.model_dump()
        try:
            await self._socket_manager.emit_to_all(
                SocketEvent.TRAP_ALERT,
                data,
            )
        except Exception as e:
            logger.warning(f"推送 TRAP_ALERT 失败: {e}")
        if self._persistence:
            self._persistence.enqueue_event("trap_alert", data)
