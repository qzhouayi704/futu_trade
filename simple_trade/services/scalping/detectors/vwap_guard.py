"""
VWAP 偏离度守卫（VWAP Extension Guard）

基于 Tick 数据实时计算全天累计 VWAP（开盘至当前时刻的
sum(price × volume) / sum(volume)），计算当天 ATR，
在价格严重偏离 VWAP 时推送警报。每日开盘重置累计值。

VWAP 计算：
- 全天累计：sum(price_i × volume_i) / sum(volume_i)
- 每日开盘重置 sum_price_volume 和 sum_volume

ATR 计算：
- 维护 1 分钟 K 线的 (high, low, close) 列表
- True Range = max(high - low, |high - prev_close|, |low - prev_close|)
- ATR = 最近 14 根 K 线的 True Range 均值

偏离判定：
- 偏离 = abs(current_price - vwap)
- 阈值 = ATR × atr_multiplier_high
- 偏离 > 阈值 → 推送 VWAP_EXTENSION_ALERT
- 偏离 < 阈值 × recovery_ratio → 推送 VWAP_EXTENSION_CLEAR
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from simple_trade.services.scalping.models import (
    TickData,
    VwapExtensionAlertData,
    VwapExtensionClearData,
)
from simple_trade.websocket.events import SocketEvent

logger = logging.getLogger("scalping")


@dataclass
class _BarData:
    """1 分钟 K 线数据，用于 ATR 计算"""
    high: float
    low: float
    close: float
    minute_key: int  # 分钟级时间戳（秒），用于归属判定


@dataclass
class _StockVwapState:
    """单个股票的 VWAP 状态"""
    # VWAP 累计值
    sum_price_volume: float = 0.0
    sum_volume: int = 0
    # ATR 相关：已完成的 1 分钟 K 线列表
    completed_bars: list[_BarData] = field(default_factory=list)
    # 当前正在构建的 K 线
    current_bar: _BarData | None = None
    current_bar_minute: int = -1  # 当前 K 线所属分钟
    # 偏离状态
    is_extended: bool = False
    # 最新价格
    last_price: float = 0.0


class VwapExtensionGuard:
    """VWAP 偏离度守卫

    基于 Tick 数据实时计算全天累计 VWAP，计算当天 ATR，
    在价格严重偏离 VWAP 时通过 SocketManager 推送警报。
    """

    def __init__(
        self,
        socket_manager,
        atr_multiplier_low: float = 1.5,
        atr_multiplier_high: float = 2.0,
        recovery_ratio: float = 0.8,
        atr_period: int = 14,
    ):
        """初始化 VwapExtensionGuard

        Args:
            socket_manager: SocketManager 实例
            atr_multiplier_low: ATR 倍数下限，默认 1.5
            atr_multiplier_high: ATR 倍数上限（用作偏离阈值），默认 2.0
            recovery_ratio: 恢复比例，偏离回落至阈值此比例以下时清除，默认 0.8
            atr_period: ATR 计算周期数（1 分钟 K 线），默认 14
        """
        self._socket_manager = socket_manager
        self._atr_multiplier_low = atr_multiplier_low
        self._atr_multiplier_high = atr_multiplier_high
        self._recovery_ratio = recovery_ratio
        self._atr_period = atr_period
        self._persistence = None
        self._states: dict[str, _StockVwapState] = {}

    def _get_state(self, stock_code: str) -> _StockVwapState:
        """获取或创建股票状态"""
        if stock_code not in self._states:
            self._states[stock_code] = _StockVwapState()
        return self._states[stock_code]

    def _get_minute_key(self, timestamp_ms: float) -> int:
        """将毫秒时间戳转换为分钟级 key（秒，截断到分钟起始）"""
        timestamp_sec = timestamp_ms / 1000.0
        return int(timestamp_sec // 60) * 60

    def on_tick(self, stock_code: str, tick: TickData) -> None:
        """处理 Tick 数据，累加 VWAP 累计值，更新 ATR K 线数据

        Args:
            stock_code: 股票代码
            tick: Tick 数据
        """
        if tick.volume <= 0:
            return

        state = self._get_state(stock_code)

        # 1. 累加 VWAP
        state.sum_price_volume += tick.price * tick.volume
        state.sum_volume += tick.volume
        state.last_price = tick.price

        # 2. 更新 ATR K 线数据
        self._update_bar(state, tick)

    def _update_bar(self, state: _StockVwapState, tick: TickData) -> None:
        """更新 1 分钟 K 线数据"""
        minute_key = self._get_minute_key(tick.timestamp)

        if state.current_bar is None or minute_key != state.current_bar_minute:
            # 完成上一根 K 线
            if state.current_bar is not None:
                state.completed_bars.append(state.current_bar)
            # 开始新的 K 线
            state.current_bar = _BarData(
                high=tick.price,
                low=tick.price,
                close=tick.price,
                minute_key=minute_key,
            )
            state.current_bar_minute = minute_key
        else:
            # 更新当前 K 线
            bar = state.current_bar
            bar.high = max(bar.high, tick.price)
            bar.low = min(bar.low, tick.price)
            bar.close = tick.price

    def calculate_vwap(self, stock_code: str) -> float | None:
        """计算全天累计 VWAP 值

        Returns:
            VWAP 值，无数据时返回 None
        """
        state = self._get_state(stock_code)
        if state.sum_volume == 0:
            return None
        return state.sum_price_volume / state.sum_volume

    def calculate_atr(self, stock_code: str) -> float | None:
        """计算当天 ATR 值

        使用已完成的 1 分钟 K 线计算 True Range 均值。
        至少需要 2 根已完成的 K 线才能计算。

        Returns:
            ATR 值，数据不足时返回 None
        """
        state = self._get_state(stock_code)
        bars = state.completed_bars

        if len(bars) < 2:
            return None

        # 取最近 atr_period + 1 根 K 线（需要前一根的 close）
        recent = bars[-(self._atr_period + 1):] if len(bars) > self._atr_period else bars

        true_ranges: list[float] = []
        for i in range(1, len(recent)):
            high = recent[i].high
            low = recent[i].low
            prev_close = recent[i - 1].close
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close),
            )
            true_ranges.append(tr)

        if not true_ranges:
            return None

        return sum(true_ranges) / len(true_ranges)

    def check_extension(
        self,
        stock_code: str,
        current_price: float,
    ) -> VwapExtensionAlertData | VwapExtensionClearData | None:
        """检查价格偏离度，判断是否需要推送警报或恢复事件

        偏离判定逻辑：
        - deviation = abs(current_price - vwap)
        - threshold = ATR × atr_multiplier_high
        - deviation > threshold 且未处于超限状态 → ALERT
        - deviation < threshold × recovery_ratio 且处于超限状态 → CLEAR

        Args:
            stock_code: 股票代码
            current_price: 当前价格

        Returns:
            VwapExtensionAlertData、VwapExtensionClearData 或 None
        """
        vwap = self.calculate_vwap(stock_code)
        if vwap is None or vwap == 0:
            return None

        atr = self.calculate_atr(stock_code)
        if atr is None or atr <= 0:
            return None

        state = self._get_state(stock_code)
        deviation = abs(current_price - vwap)
        deviation_percent = (deviation / vwap) * 100
        threshold = atr * self._atr_multiplier_high
        now_str = datetime.now(timezone.utc).isoformat()

        if not state.is_extended and deviation > threshold:
            # 偏离超限 → 推送 ALERT
            state.is_extended = True
            return VwapExtensionAlertData(
                stock_code=stock_code,
                current_price=current_price,
                vwap_value=vwap,
                deviation_percent=round(deviation_percent, 4),
                dynamic_threshold=round(threshold, 4),
                timestamp=now_str,
            )

        if state.is_extended and deviation < threshold * self._recovery_ratio:
            # 偏离回落至阈值 80% 以下 → 推送 CLEAR
            state.is_extended = False
            return VwapExtensionClearData(
                stock_code=stock_code,
                current_price=current_price,
                vwap_value=vwap,
                deviation_percent=round(deviation_percent, 4),
                timestamp=now_str,
            )

        return None

    async def _emit_event(
        self,
        event: SocketEvent,
        data: VwapExtensionAlertData | VwapExtensionClearData,
    ) -> None:
        """推送事件到前端"""
        data_dict = data.model_dump()
        try:
            await self._socket_manager.emit_to_all(
                event,
                data_dict,
            )
        except Exception as e:
            logger.warning(f"推送 {event.value} 失败: {e}")
        if self._persistence and isinstance(data, VwapExtensionAlertData):
            self._persistence.enqueue_event("vwap_extension", data_dict)

    async def on_tick_async(self, stock_code: str, tick: TickData) -> None:
        """异步版 on_tick，处理 Tick 并检查偏离度、推送事件

        供 ScalpingEngine 在异步上下文中调用。

        Args:
            stock_code: 股票代码
            tick: Tick 数据
        """
        self.on_tick(stock_code, tick)

        result = self.check_extension(stock_code, tick.price)
        if isinstance(result, VwapExtensionAlertData):
            logger.info(
                f"[{stock_code}] VWAP 超限警报: "
                f"价格={result.current_price}, VWAP={result.vwap_value}, "
                f"偏离={result.deviation_percent}%"
            )
            await self._emit_event(SocketEvent.VWAP_EXTENSION_ALERT, result)
        elif isinstance(result, VwapExtensionClearData):
            logger.info(
                f"[{stock_code}] VWAP 恢复正常: "
                f"价格={result.current_price}, VWAP={result.vwap_value}, "
                f"偏离={result.deviation_percent}%"
            )
            await self._emit_event(SocketEvent.VWAP_EXTENSION_CLEAR, result)

    def get_current_vwap(self, stock_code: str) -> float | None:
        """获取当前 VWAP 值（供前端渲染 VWAP 线）

        Args:
            stock_code: 股票代码

        Returns:
            当前 VWAP 值，无数据时返回 None
        """
        return self.calculate_vwap(stock_code)

    def get_deviation_level(
        self,
        stock_code: str,
        current_price: float,
        oversold_threshold: float = -2.0,
        overbought_threshold: float = 3.0,
        fair_range: tuple[float, float] = (-1.0, 1.0),
    ) -> str:
        """
        获取 VWAP 偏离度等级（用于信号评分系统）

        偏离度 = (price - vwap) / vwap * 100

        分级规则：
        - 偏离度 < oversold_threshold → 超跌（oversold），支撑低吸信号权重 +1
        - 偏离度 > overbought_threshold → 超涨（overbought），禁止追多
        - 偏离度在 fair_range → 价格合理区间（fair）
        - 其他 → 中性（neutral）

        Args:
            stock_code: 股票代码
            current_price: 当前价格
            oversold_threshold: 超跌阈值（默认 -2%）
            overbought_threshold: 超涨阈值（默认 +3%）
            fair_range: 合理区间（默认 -1% ~ +1%）

        Returns:
            偏离度等级：
            - "oversold": 超跌
            - "overbought": 超涨
            - "fair": 合理区间
            - "neutral": 中性
            - "unknown": VWAP 数据不足
        """
        vwap = self.calculate_vwap(stock_code)
        if vwap is None or vwap == 0:
            return "unknown"

        # 计算偏离度（百分比）
        deviation_percent = ((current_price - vwap) / vwap) * 100

        # 分级判定
        if deviation_percent < oversold_threshold:
            return "oversold"
        elif deviation_percent > overbought_threshold:
            return "overbought"
        elif fair_range[0] <= deviation_percent <= fair_range[1]:
            return "fair"
        else:
            return "neutral"

    def get_deviation_percent(self, stock_code: str, current_price: float) -> float | None:
        """
        获取 VWAP 偏离度百分比

        Args:
            stock_code: 股票代码
            current_price: 当前价格

        Returns:
            偏离度百分比，VWAP 数据不足时返回 None
        """
        vwap = self.calculate_vwap(stock_code)
        if vwap is None or vwap == 0:
            return None

        return ((current_price - vwap) / vwap) * 100

    def reset(self, stock_code: str) -> None:
        """每日开盘重置累计值

        重置 sum_price_volume、sum_volume、ATR K 线数据和偏离状态。

        Args:
            stock_code: 股票代码
        """
        if stock_code in self._states:
            self._states[stock_code] = _StockVwapState()
            logger.debug(f"[{stock_code}] VWAP 状态已重置")
