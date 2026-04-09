"""
盘口流速仪（Tape Velocity Monitor）

统计 3 秒滑动窗口内的成交笔数，计算最近 5 分钟滚动均值作为基准，
当成交笔数达到基准 3 倍时触发动能点火事件。

核心逻辑：
- 3 秒滑动窗口：仅统计时间戳在 [now - 3s, now] 范围内的 Tick 笔数
- 5 分钟滚动基准：将时间轴按 3 秒切片，统计每个切片的笔数，取均值
- 冷却期：触发后 10 秒内不重复触发
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from simple_trade.services.scalping.models import (
    MomentumIgnitionData,
    TickData,
)
from simple_trade.websocket.events import SocketEvent

logger = logging.getLogger("scalping")


@dataclass
class _WindowSlice:
    """3 秒窗口切片的统计快照"""
    timestamp: float  # 切片结束时间（秒）
    count: int        # 该切片内的成交笔数


@dataclass
class _StockVelocityState:
    """单个股票的流速状态"""
    # 3 秒滑动窗口内的 tick 时间戳列表（秒）
    tick_timestamps: deque = field(default_factory=deque)
    # 历史切片，用于计算 5 分钟滚动基准
    history_slices: deque = field(default_factory=deque)
    # 上次切片时间（秒）
    last_slice_time: float = 0.0
    # 冷却期结束时间（秒）
    cooldown_until: float = 0.0
    # 成交速度历史（用于计算加速度）
    velocity_history: deque = field(default_factory=lambda: deque(maxlen=10))


class TapeVelocityMonitor:
    """盘口流速仪

    维护 3 秒滑动窗口统计成交笔数，计算最近 5 分钟滚动均值作为基准，
    成交笔数达到基准 3 倍时触发动能点火事件。
    """

    def __init__(
        self,
        socket_manager,
        window_seconds: float = 3.0,
        baseline_window_seconds: float = 300.0,
        ignition_multiplier: float = 3.0,
        cooldown_seconds: float = 10.0,
        max_cooldown: float = 60.0,
        warmup_slices: int = 100,
    ):
        """初始化 TapeVelocityMonitor

        Args:
            socket_manager: SocketManager 实例，用于推送事件
            window_seconds: 滑动窗口大小（秒），默认 3.0
            baseline_window_seconds: 基准计算窗口（秒），默认 300.0
            ignition_multiplier: 点火倍数阈值，默认 3.0
            cooldown_seconds: 基础冷却期（秒），默认 10.0
            max_cooldown: 最大冷却期（秒），默认 60.0
            warmup_slices: 开盘预热切片数（排除前 N 个切片），默认 100（≈5 分钟）
        """
        self._socket_manager = socket_manager
        self._window_seconds = window_seconds
        self._baseline_window_seconds = baseline_window_seconds
        self._ignition_multiplier = ignition_multiplier
        self._base_cooldown = cooldown_seconds
        self._max_cooldown = max_cooldown
        self._warmup_slices = warmup_slices
        self._persistence = None
        self._states: dict[str, _StockVelocityState] = {}
        # 连续触发计数（用于动态冷却期）
        self._consecutive_triggers: dict[str, int] = {}

    def _get_state(self, stock_code: str) -> _StockVelocityState:
        """获取或创建股票状态"""
        if stock_code not in self._states:
            self._states[stock_code] = _StockVelocityState()
        return self._states[stock_code]

    def _purge_window(
        self, state: _StockVelocityState, now_sec: float
    ) -> None:
        """清理滑动窗口中过期的 tick 时间戳"""
        cutoff = now_sec - self._window_seconds
        while state.tick_timestamps and state.tick_timestamps[0] < cutoff:
            state.tick_timestamps.popleft()

    def _archive_slice(
        self, state: _StockVelocityState, now_sec: float
    ) -> None:
        """将当前窗口快照归档为历史切片，用于基准计算。

        每隔 window_seconds 归档一次，避免重复归档。
        """
        if state.last_slice_time == 0.0:
            state.last_slice_time = now_sec
            return

        # 每隔 window_seconds 归档一次
        if now_sec - state.last_slice_time >= self._window_seconds:
            current_count = len(state.tick_timestamps)
            state.history_slices.append(
                _WindowSlice(timestamp=now_sec, count=current_count)
            )
            state.last_slice_time = now_sec

            # 记录成交速度（用于加速度计算）
            state.velocity_history.append(current_count)

            # 清理超出 baseline_window_seconds 的历史切片
            cutoff = now_sec - self._baseline_window_seconds
            while (
                state.history_slices
                and state.history_slices[0].timestamp < cutoff
            ):
                state.history_slices.popleft()

    def on_tick(self, stock_code: str, tick: TickData) -> None:
        """记录成交笔数，更新 3 秒滑动窗口和基准

        Args:
            stock_code: 股票代码
            tick: 逐笔成交数据（timestamp 为 Unix 毫秒）
        """
        state = self._get_state(stock_code)
        now_sec = tick.timestamp / 1000.0

        # 添加到滑动窗口
        state.tick_timestamps.append(now_sec)

        # 清理过期数据
        self._purge_window(state, now_sec)

        # 归档切片
        self._archive_slice(state, now_sec)

        # 超过 max_cooldown 未触发则重置连续触发计数
        if (
            stock_code in self._consecutive_triggers
            and state.cooldown_until > 0
            and now_sec > state.cooldown_until + self._max_cooldown
        ):
            self._consecutive_triggers.pop(stock_code, None)

    def get_window_count(self, stock_code: str) -> int:
        """获取当前 3 秒窗口内的成交笔数

        Args:
            stock_code: 股票代码

        Returns:
            当前窗口内的成交笔数
        """
        state = self._get_state(stock_code)
        return len(state.tick_timestamps)

    def get_baseline_avg(self, stock_code: str) -> float:
        """获取最近 5 分钟的滚动均值基准

        排除开盘前 warmup_slices 个切片（约 5 分钟），
        避免开盘效应拉高基准导致盘中正常放量无法触发。

        Args:
            stock_code: 股票代码

        Returns:
            基准均值（每 3 秒窗口的平均成交笔数）
        """
        state = self._get_state(stock_code)
        if not state.history_slices:
            return 0.0
        slices = list(state.history_slices)
        # 排除开盘预热期
        if len(slices) > self._warmup_slices:
            slices = slices[self._warmup_slices:]
        if not slices:
            return 0.0
        total = sum(s.count for s in slices)
        return total / len(slices)

    def calculate_acceleration(self, stock_code: str) -> Optional[float]:
        """
        计算成交速度加速度（用于信号评分系统）

        加速度 = 当前成交速度 - 上一周期成交速度

        应用场景：
        - 加速度 > 阈值 → 动能点火，提高信号权重
        - 加速度 < 0 → 动能衰减，降低信号权重或触发止损

        Args:
            stock_code: 股票代码

        Returns:
            加速度值，数据不足时返回 None
        """
        state = self._get_state(stock_code)

        if len(state.velocity_history) < 2:
            return None

        # 计算加速度：当前速度 - 上一周期速度
        current_velocity = state.velocity_history[-1]
        previous_velocity = state.velocity_history[-2]

        acceleration = current_velocity - previous_velocity

        return acceleration

    def get_velocity_history(self, stock_code: str) -> list[int]:
        """
        获取成交速度历史

        Args:
            stock_code: 股票代码

        Returns:
            成交速度历史列表
        """
        state = self._get_state(stock_code)
        return list(state.velocity_history)

    def is_in_cooldown(self, stock_code: str) -> bool:
        """检查指定股票是否在冷却期内

        Args:
            stock_code: 股票代码

        Returns:
            True 表示在冷却期内
        """
        state = self._get_state(stock_code)
        if not state.tick_timestamps:
            return False
        now_sec = state.tick_timestamps[-1]
        return now_sec < state.cooldown_until

    async def check_ignition(
        self, stock_code: str
    ) -> Optional[MomentumIgnitionData]:
        """检测是否触发动能点火事件

        当 3 秒窗口内成交笔数 >= 基准均值 × ignition_multiplier
        且不在冷却期内时触发，并通过 SocketManager 推送事件。

        Args:
            stock_code: 股票代码

        Returns:
            MomentumIgnitionData 或 None
        """
        state = self._get_state(stock_code)

        if not state.tick_timestamps:
            return None

        now_sec = state.tick_timestamps[-1]

        # 冷却期检查
        if now_sec < state.cooldown_until:
            return None

        current_count = len(state.tick_timestamps)
        baseline_avg = self.get_baseline_avg(stock_code)

        # 基准为 0 时不触发（没有历史数据）
        if baseline_avg <= 0:
            return None

        multiplier = current_count / baseline_avg

        if multiplier < self._ignition_multiplier:
            return None

        # 触发动能点火 —— 动态冷却期：连续触发时翻倍
        count = self._consecutive_triggers.get(stock_code, 0)
        cooldown = min(self._base_cooldown * (2 ** count), self._max_cooldown)
        state.cooldown_until = now_sec + cooldown
        self._consecutive_triggers[stock_code] = count + 1

        event_data = MomentumIgnitionData(
            stock_code=stock_code,
            current_count=current_count,
            baseline_avg=round(baseline_avg, 2),
            multiplier=round(multiplier, 2),
            timestamp=datetime.fromtimestamp(now_sec).isoformat(),
        )

        try:
            await self._socket_manager.emit_to_all(
                SocketEvent.MOMENTUM_IGNITION,
                event_data.model_dump(),
            )
            logger.info(
                f"动能点火 {stock_code}: "
                f"当前={current_count}, 基准={baseline_avg:.1f}, "
                f"倍数={multiplier:.1f}"
            )
        except Exception as e:
            logger.warning(f"推送 MOMENTUM_IGNITION 失败: {e}")
        if self._persistence:
            self._persistence.enqueue_event("momentum_ignition", event_data.model_dump())

        return event_data

    def reset(self, stock_code: str) -> None:
        """重置指定股票的流速状态

        Args:
            stock_code: 股票代码
        """
        if stock_code in self._states:
            del self._states[stock_code]
        logger.info(f"已重置 {stock_code} 的流速状态")
