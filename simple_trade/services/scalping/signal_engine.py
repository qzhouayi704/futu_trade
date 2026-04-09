"""
建仓信号引擎（Signal Engine）

综合 DeltaCalculator、TapeVelocityMonitor、SpoofingFilter、POCCalculator
四个计算器的实时状态，评估突破追多和支撑低吸两种建仓信号。

突破追多信号（需求 9）：
  1. 价格距日内高点 < 5 Tick
  2. 动能点火（TapeVelocityMonitor 刚触发过，is_in_cooldown=True）
  3. Delta 极强正值（> 近 20 周期均值 × 2）
  4. 对应价位阻力线已被抹除（附近无 RESISTANCE 类型 active level）

支撑低吸信号（需求 10）：
  1. 价格距 POC 或绿色支撑线 < 3 Tick
  2. 当前 Delta 为负值
  3. 价格在支撑位附近停滞 > 3 秒（波动 < 2 Tick）
"""

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from simple_trade.services.scalping.calculators.delta_calculator import DeltaCalculator
from simple_trade.services.scalping.models import (
    PriceLevelSide,
    ScalpingSignalData,
    ScalpingSignalType,
)
from simple_trade.services.scalping.calculators.poc_calculator import POCCalculator
from simple_trade.services.scalping.detectors.spoofing_filter import SpoofingFilter
from simple_trade.services.scalping.calculators.tape_velocity import TapeVelocityMonitor
from simple_trade.services.scalping.signal_scorer import SignalScorer
from simple_trade.services.scalping.calculators.ofi_calculator import OFICalculator
from simple_trade.services.scalping.detectors.vwap_guard import VwapExtensionGuard
from simple_trade.websocket.events import SocketEvent

logger = logging.getLogger("scalping")


@dataclass
class _PriceRecord:
    """价格记录，用于停滞检测"""
    price: float
    timestamp: float  # Unix 秒


@dataclass
class _StallTracker:
    """价格停滞跟踪器状态"""
    records: deque = field(default_factory=lambda: deque(maxlen=200))


class SignalEngine:
    """建仓信号引擎

    综合多个计算器的实时状态，评估突破追多和支撑低吸信号。
    满足条件时通过 SocketManager 推送 SCALPING_SIGNAL 事件。
    """

    def __init__(
        self,
        socket_manager,
        delta_calculator: DeltaCalculator,
        tape_velocity: TapeVelocityMonitor,
        spoofing_filter: SpoofingFilter,
        poc_calculator: POCCalculator,
        vwap_guard: VwapExtensionGuard,
        ofi_calculator: Optional[OFICalculator] = None,
        signal_scorer: Optional[SignalScorer] = None,
        tick_size: float = 0.01,
        stall_seconds: float = 3.0,
        stall_max_ticks: int = 2,
        persistence=None,
        min_signal_score: int = 5,
    ):
        """初始化 SignalEngine

        Args:
            socket_manager: SocketManager 实例
            delta_calculator: 多空净动量计算器
            tape_velocity: 盘口流速仪
            spoofing_filter: 防撤单陷阱过滤器
            poc_calculator: 日内控制点计算器
            vwap_guard: VWAP 偏离度守卫
            ofi_calculator: OFI 计算器（可选）
            signal_scorer: 信号评分器（可选）
            tick_size: 最小价格变动单位（默认 0.01）
            stall_seconds: 停滞判定时间阈值（秒）
            stall_max_ticks: 停滞判定最大波动 Tick 数
            persistence: ScalpingPersistence 实例（可选），用于数据持久化
            min_signal_score: 最低信号评分阈值（默认 5 分）
        """
        self._socket_manager = socket_manager
        self._persistence = persistence
        self._delta_calculator = delta_calculator
        self._tape_velocity = tape_velocity
        self._spoofing_filter = spoofing_filter
        self._poc_calculator = poc_calculator
        self._vwap_guard = vwap_guard
        self._ofi_calculator = ofi_calculator
        self._signal_scorer = signal_scorer or SignalScorer()
        self._tick_size = tick_size
        self._stall_seconds = stall_seconds
        self._stall_max_ticks = stall_max_ticks
        self._min_signal_score = min_signal_score

        # 价格停滞跟踪：stock_code -> _StallTracker
        self._stall_trackers: dict[str, _StallTracker] = {}

    def _get_stall_tracker(self, stock_code: str) -> _StallTracker:
        """获取或创建停滞跟踪器"""
        if stock_code not in self._stall_trackers:
            self._stall_trackers[stock_code] = _StallTracker()
        return self._stall_trackers[stock_code]

    def record_price(
        self, stock_code: str, price: float, timestamp: float
    ) -> None:
        """记录价格用于停滞检测

        由外部（ScalpingEngine）在每笔 Tick 到达时调用。

        Args:
            stock_code: 股票代码
            price: 当前价格
            timestamp: Unix 秒时间戳
        """
        tracker = self._get_stall_tracker(stock_code)
        tracker.records.append(_PriceRecord(price=price, timestamp=timestamp))

    def _check_price_stall(
        self, stock_code: str, reference_price: float, now: float
    ) -> bool:
        """检测价格是否在支撑位附近停滞超过 stall_seconds

        停滞定义：在最近 stall_seconds 秒内，所有价格记录的
        波动范围 < stall_max_ticks 个 Tick。

        Args:
            stock_code: 股票代码
            reference_price: 参考价格（支撑位）
            now: 当前时间（Unix 秒）

        Returns:
            True 表示价格停滞
        """
        tracker = self._get_stall_tracker(stock_code)
        if not tracker.records:
            return False

        cutoff = now - self._stall_seconds
        # 收集时间窗口内的价格
        prices_in_window = [
            r.price for r in tracker.records if r.timestamp >= cutoff
        ]

        if not prices_in_window:
            return False

        # 检查时间窗口内的记录是否覆盖了足够长的时间跨度
        earliest_in_window = min(
            r.timestamp for r in tracker.records if r.timestamp >= cutoff
        )
        if now - earliest_in_window < self._stall_seconds:
            return False

        price_range = max(prices_in_window) - min(prices_in_window)
        max_allowed = self._stall_max_ticks * self._tick_size
        return price_range < max_allowed

    def _get_latest_delta(self, stock_code: str) -> Optional[float]:
        """获取最新一个周期的 Delta 值"""
        deltas = self._delta_calculator.get_recent_deltas(stock_code, 1)
        return deltas[-1].delta if deltas else None

    def _get_delta_mean(self, stock_code: str, count: int = 20, exclude_latest: bool = False) -> float:
        """计算最近 N 个周期 Delta 的均值"""
        deltas = self._delta_calculator.get_recent_deltas(stock_code, count + (1 if exclude_latest else 0))
        if exclude_latest and len(deltas) > 0:
            deltas = deltas[:-1]
        if not deltas:
            return 0.0
        return sum(d.delta for d in deltas) / len(deltas)

    def _has_resistance_near(self, stock_code: str, price: float, ticks: int = 5) -> bool:
        """检查指定价格附近是否存在 RESISTANCE 类型的活跃阻力线"""
        levels = self._spoofing_filter.get_active_levels(stock_code)
        for level in levels:
            if level.side == PriceLevelSide.RESISTANCE:
                dist_ticks = round(
                    abs(level.price - price) / self._tick_size
                )
                if dist_ticks <= ticks:
                    return True
        return False

    def _find_nearest_support(
        self, stock_code: str, current_price: float, max_ticks: int = 3,
    ) -> Optional[float]:
        """查找距当前价格最近的支撑位（POC 或绿色支撑线）"""
        candidates: list[float] = []

        # 检查 POC 价格
        poc_state = self._poc_calculator._get_state(stock_code)
        if poc_state.last_poc_price is not None:
            dist_ticks = round(
                abs(current_price - poc_state.last_poc_price) / self._tick_size
            )
            if dist_ticks < max_ticks:
                candidates.append(poc_state.last_poc_price)

        # 检查绿色支撑线
        levels = self._spoofing_filter.get_active_levels(stock_code)
        for level in levels:
            if level.side == PriceLevelSide.SUPPORT:
                dist_ticks = round(
                    abs(current_price - level.price) / self._tick_size
                )
                if dist_ticks < max_ticks:
                    candidates.append(level.price)

        if not candidates:
            return None

        # 返回距当前价格最近的支撑位
        return min(candidates, key=lambda p: abs(current_price - p))

    def _calculate_signal_score(
        self,
        stock_code: str,
        current_price: float,
        current_delta: float,
    ) -> Optional[dict]:
        """
        计算信号评分

        Args:
            stock_code: 股票代码
            current_price: 当前价格
            current_delta: 当前 Delta 值

        Returns:
            包含评分信息的字典，如果数据不足则返回 None
        """
        # 1. 计算 Delta 强度评分
        avg_delta = self._get_delta_mean(stock_code, count=20)

        # 2. 获取 OFI 评分
        ofi_score = 0
        if self._ofi_calculator is not None:
            ofi_score = self._ofi_calculator.get_ofi_score()

        # 3. 获取成交加速度评分
        acceleration = self._tape_velocity.calculate_acceleration(stock_code)

        # 4. 获取 VWAP 偏离度等级
        vwap_deviation_level = self._vwap_guard.get_deviation_level(
            stock_code, current_price
        )

        # 5. 获取 POC 价格
        poc_state = self._poc_calculator._get_state(stock_code)
        poc_price = poc_state.last_poc_price

        # 计算总评分
        score_components = self._signal_scorer.calculate_total_score(
            current_delta=current_delta,
            avg_delta=avg_delta,
            ofi_score=ofi_score,
            acceleration=acceleration,
            vwap_deviation_level=vwap_deviation_level,
            current_price=current_price,
            poc_price=poc_price,
        )

        return {
            "score": score_components.total_score,
            "score_components": {
                "delta_score": score_components.delta_score,
                "ofi_score": score_components.ofi_score,
                "acceleration_score": score_components.acceleration_score,
                "vwap_deviation_score": score_components.vwap_deviation_score,
                "poc_distance_score": score_components.poc_distance_score,
            },
            "quality_level": score_components.get_quality_level(),
        }

    async def evaluate_breakout(
        self, stock_code: str, current_price: float, day_high: float,
    ) -> Optional[ScalpingSignalData]:
        """评估突破追多条件（5 个条件全部满足才触发）"""
        conditions: list[str] = []

        # 条件 1：价格距日内高点 < 5 Tick
        # 使用 round 转换为整数 Tick 数，避免浮点精度问题
        distance = abs(day_high - current_price)
        distance_ticks = round(distance / self._tick_size)
        near_high = distance_ticks < 5
        if not near_high:
            return None
        conditions.append(
            f"价格距日内高点 {distance_ticks} Tick"
        )

        # 条件 2：动能点火（刚触发过，处于冷却期）
        momentum_fired = self._tape_velocity.is_in_cooldown(stock_code)
        if not momentum_fired:
            return None
        conditions.append("动能点火已触发")

        # 条件 3：Delta 极强正值（合并已 flush 和当前实时 Delta）
        latest_delta = self._get_latest_delta(stock_code)
        current_delta, _, _ = self._delta_calculator.get_current_period_stats(stock_code)
        effective_delta = (latest_delta or 0) + current_delta
        delta_mean = self._get_delta_mean(stock_code, count=20, exclude_latest=True)
        strong_delta = effective_delta > abs(delta_mean) * 2
        if not strong_delta:
            return None
        conditions.append(
            f"Delta 极强正值: {effective_delta:.0f} "
            f"(均值 {delta_mean:.0f} × 2)"
        )

        # 条件 4：阻力线已被抹除
        has_resistance = self._has_resistance_near(
            stock_code, day_high, ticks=5
        )
        if has_resistance:
            return None
        conditions.append("阻力线已抹除")

        # 条件 5：大单成交量占比 > 30%
        big_order_ratio = self._delta_calculator.get_big_order_ratio(stock_code)
        if big_order_ratio < 0.3:
            return None
        conditions.append(f"大单成交量占比 {big_order_ratio:.0%}")

        # 计算信号评分
        score_info = self._calculate_signal_score(
            stock_code, current_price, effective_delta
        )

        # 如果评分不足，过滤信号
        if score_info and score_info["score"] < self._min_signal_score:
            logger.debug(
                f"[{stock_code}] 突破信号评分不足: {score_info['score']} < {self._min_signal_score}，已过滤"
            )
            return None

        # 四个条件全部满足，生成信号
        signal = ScalpingSignalData(
            stock_code=stock_code,
            signal_type=ScalpingSignalType.BREAKOUT_LONG,
            trigger_price=current_price,
            conditions=conditions,
            timestamp=datetime.now().isoformat(),
            score=score_info["score"] if score_info else None,
            score_components=score_info["score_components"] if score_info else None,
            quality_level=score_info["quality_level"] if score_info else None,
        )

        await self._emit_signal(signal)
        return signal

    async def evaluate_support_bounce(
        self, stock_code: str, current_price: float, now: Optional[float] = None,
    ) -> Optional[ScalpingSignalData]:
        """评估支撑低吸条件（3 个条件全部满足才触发）"""
        conditions: list[str] = []

        # 条件 1：价格距 POC 或绿色支撑线 < 3 Tick
        support_price = self._find_nearest_support(
            stock_code, current_price, max_ticks=3
        )
        if support_price is None:
            return None
        dist_ticks = round(
            abs(current_price - support_price) / self._tick_size
        )
        conditions.append(
            f"价格距支撑位 {dist_ticks} Tick "
            f"(支撑价 {support_price})"
        )

        # 条件 2：当前 Delta 为负值
        latest_delta = self._get_latest_delta(stock_code)
        if latest_delta is None or latest_delta >= 0:
            return None
        conditions.append(f"Delta 为负值: {latest_delta:.0f}")

        # 条件 3：价格停滞 > 3 秒
        check_time = now if now is not None else time.time()
        stalled = self._check_price_stall(
            stock_code, support_price, check_time
        )
        if not stalled:
            return None
        conditions.append("价格停滞超过 3 秒")

        # 计算信号评分
        score_info = self._calculate_signal_score(
            stock_code, current_price, latest_delta
        )

        # 如果评分不足，过滤信号
        if score_info and score_info["score"] < self._min_signal_score:
            logger.debug(
                f"[{stock_code}] 支撑低吸信号评分不足: {score_info['score']} < {self._min_signal_score}，已过滤"
            )
            return None

        # 三个条件全部满足，生成信号
        signal = ScalpingSignalData(
            stock_code=stock_code,
            signal_type=ScalpingSignalType.SUPPORT_LONG,
            trigger_price=current_price,
            support_price=support_price,
            conditions=conditions,
            timestamp=datetime.now().isoformat(),
            score=score_info["score"] if score_info else None,
            score_components=score_info["score_components"] if score_info else None,
            quality_level=score_info["quality_level"] if score_info else None,
        )

        await self._emit_signal(signal)
        return signal

    async def _emit_signal(self, signal: ScalpingSignalData) -> None:
        """通过 SocketManager 推送信号事件"""
        try:
            await self._socket_manager.emit_to_all(
                SocketEvent.SCALPING_SIGNAL,
                signal.model_dump(),
            )
            logger.info(
                f"[{signal.stock_code}] 生成信号: "
                f"{signal.signal_type.value}, "
                f"价格={signal.trigger_price}"
            )
        except Exception as e:
            logger.warning(f"推送 SCALPING_SIGNAL 失败: {e}")

        if self._persistence is not None:
            try:
                self._persistence.enqueue_signal(signal)
            except Exception as e:
                logger.warning(f"信号入队持久化失败: {e}")

    def reset(self, stock_code: str) -> None:
        """重置指定股票的信号引擎状态"""
        self._stall_trackers.pop(stock_code, None)
        logger.info(f"已重置 {stock_code} 的 SignalEngine 状态")
