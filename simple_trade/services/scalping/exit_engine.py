"""
平仓信号引擎（Exit Engine）

评估 Scalping 持仓的平仓条件，支持三种独立触发器：
1. Delta 反转：最新 Delta 符号与建仓方向相反，且绝对值 > 均值
2. 时间衰减：建仓超过 max_hold_seconds 未达止盈
3. 固定止损：亏损超过 max_loss_ticks
"""

import logging
import time
from datetime import datetime
from typing import Optional

from simple_trade.services.scalping.calculators.delta_calculator import DeltaCalculator
from simple_trade.services.scalping.models import (
    ExitConfig,
    ScalpingSignalData,
    ScalpingSignalType,
)
from simple_trade.websocket.events import SocketEvent

logger = logging.getLogger("scalping")


class ExitEngine:
    """平仓信号引擎

    在每次 tick 到达时评估是否应该平仓。
    三个触发器任一满足即生成平仓信号。
    """

    def __init__(
        self,
        socket_manager,
        delta_calculator: DeltaCalculator,
        tick_size: float = 0.01,
        config: Optional[ExitConfig] = None,
        persistence=None,
    ):
        self._socket_manager = socket_manager
        self._delta_calculator = delta_calculator
        self._tick_size = tick_size
        self._config = config or ExitConfig()
        self._persistence = persistence

    async def evaluate_exit(
        self,
        stock_code: str,
        current_price: float,
        entry_price: float,
        entry_time: float,
        signal_type: ScalpingSignalType,
        now: Optional[float] = None,
    ) -> Optional[ScalpingSignalData]:
        """评估平仓条件

        Args:
            stock_code: 股票代码
            current_price: 当前价格
            entry_price: 建仓价格
            entry_time: 建仓时间（Unix 秒）
            signal_type: 建仓信号类型（用于判断方向）
            now: 当前时间（Unix 秒），默认 time.time()

        Returns:
            ScalpingSignalData（平仓信号）或 None
        """
        check_time = now if now is not None else time.time()
        cfg = self._config

        # 触发器 1：固定止损
        loss_ticks = round((entry_price - current_price) / self._tick_size)
        if loss_ticks >= cfg.max_loss_ticks:
            return await self._emit_exit(
                stock_code, current_price, entry_price,
                ScalpingSignalType.EXIT_DELTA_REVERSAL,
                [f"亏损 {loss_ticks} Tick，超过止损阈值 {cfg.max_loss_ticks}"],
            )

        # 触发器 2：时间衰减
        hold_seconds = check_time - entry_time
        if hold_seconds >= cfg.max_hold_seconds:
            return await self._emit_exit(
                stock_code, current_price, entry_price,
                ScalpingSignalType.EXIT_TIME_DECAY,
                [f"持仓 {hold_seconds:.0f}s，超过最大持仓时间 {cfg.max_hold_seconds:.0f}s"],
            )

        # 触发器 3：Delta 反转
        exit_signal = self._check_delta_reversal(
            stock_code, signal_type,
        )
        if exit_signal is not None:
            return await self._emit_exit(
                stock_code, current_price, entry_price,
                ScalpingSignalType.EXIT_DELTA_REVERSAL,
                [exit_signal],
            )

        return None

    def _check_delta_reversal(
        self,
        stock_code: str,
        entry_signal_type: ScalpingSignalType,
    ) -> Optional[str]:
        """检测 Delta 是否反转"""
        deltas = self._delta_calculator.get_recent_deltas(stock_code, 20)
        if not deltas:
            return None

        latest_delta = deltas[-1].delta
        if len(deltas) < 2:
            return None

        mean_abs = sum(abs(d.delta) for d in deltas[:-1]) / (len(deltas) - 1)
        threshold = mean_abs * self._config.delta_reversal_threshold

        # 做多建仓 → Delta 转负且绝对值超过阈值 → 反转
        is_long = entry_signal_type in (
            ScalpingSignalType.BREAKOUT_LONG,
            ScalpingSignalType.SUPPORT_LONG,
        )
        if is_long and latest_delta < -threshold:
            return (
                f"Delta 反转: {latest_delta:.0f} "
                f"(阈值 -{threshold:.0f})"
            )

        return None

    async def _emit_exit(
        self,
        stock_code: str,
        current_price: float,
        entry_price: float,
        exit_type: ScalpingSignalType,
        conditions: list[str],
    ) -> ScalpingSignalData:
        """构建并推送平仓信号"""
        pnl_ticks = round(
            (current_price - entry_price) / self._tick_size
        )
        conditions.append(f"盈亏 {pnl_ticks} Tick")

        signal = ScalpingSignalData(
            stock_code=stock_code,
            signal_type=exit_type,
            trigger_price=current_price,
            conditions=conditions,
            timestamp=datetime.now().isoformat(),
        )

        try:
            await self._socket_manager.emit_to_all(
                SocketEvent.SCALPING_SIGNAL,
                signal.model_dump(),
            )
            logger.info(
                f"[{stock_code}] 平仓信号: {exit_type.value}, "
                f"价格={current_price}, 盈亏={pnl_ticks} Tick"
            )
        except Exception as e:
            logger.warning(f"推送平仓信号失败: {e}")

        if self._persistence is not None:
            try:
                self._persistence.enqueue_signal(signal)
            except Exception as e:
                logger.warning(f"平仓信号入队持久化失败: {e}")

        return signal
