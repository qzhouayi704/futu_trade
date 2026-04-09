"""
止损监控器（Stop Loss Monitor）

在入场信号触发后监控价格回撤并推送止损提示。

工作流程：
1. on_signal 接收 SignalEngine 生成的入场信号，记录入场价格并开始监控
   - breakout_long 信号：记录 trigger_price 作为突破价格，stop_price = trigger_price
   - support_long 信号：记录 support_price 作为支撑位价格，stop_price = support_price
2. on_tick 处理每笔 Tick，检查是否触发止损条件
   - 突破做多：价格回落到突破价格以下 → 推送 STOP_LOSS_ALERT
   - 支撑低吸：价格跌破支撑位价格 → 推送 STOP_LOSS_ALERT
3. 同一入场信号仅推送一次止损提示，推送后从 active_positions 中移除
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from simple_trade.services.scalping.models import (
    ScalpingSignalData,
    ScalpingSignalType,
    StopLossAlertData,
    StopLossSignalType,
    TickData,
)
from simple_trade.websocket.events import SocketEvent

logger = logging.getLogger("scalping")


@dataclass
class _ActivePosition:
    """单个活跃持仓监控记录"""

    signal_type: ScalpingSignalType
    entry_price: float       # trigger_price（入场价格）
    stop_price: float        # 止损触发价格
    support_price: float | None  # 仅 support_long 信号
    timestamp: str


class StopLossMonitor:
    """止损监控器

    监听 SignalEngine 生成的入场信号，记录入场价格后独立监控价格回撤。
    维护 active_positions 列表，跟踪所有未关闭的入场信号。
    同一入场信号仅推送一次止损提示，推送后从 active_positions 中移除。
    """

    def __init__(self, socket_manager) -> None:
        """初始化 StopLossMonitor

        Args:
            socket_manager: SocketManager 实例，用于推送 STOP_LOSS_ALERT 事件
        """
        self._socket_manager = socket_manager
        # stock_code → list[_ActivePosition]
        self._positions: dict[str, list[_ActivePosition]] = {}

    def on_signal(
        self, stock_code: str, signal: ScalpingSignalData
    ) -> None:
        """接收入场信号，记录入场价格并开始监控

        - breakout_long：stop_price = trigger_price（突破价格）
        - support_long：stop_price = support_price（支撑位价格）

        Args:
            stock_code: 股票代码
            signal: 入场信号数据
        """
        if signal.signal_type == ScalpingSignalType.BREAKOUT_LONG:
            stop_price = signal.trigger_price
        elif signal.signal_type == ScalpingSignalType.SUPPORT_LONG:
            if signal.support_price is None:
                logger.warning(
                    f"[{stock_code}] support_long 信号缺少 support_price，"
                    f"回退使用 trigger_price"
                )
                stop_price = signal.trigger_price
            else:
                stop_price = signal.support_price
        else:
            logger.warning(
                f"[{stock_code}] 未知信号类型: {signal.signal_type}"
            )
            return

        position = _ActivePosition(
            signal_type=signal.signal_type,
            entry_price=signal.trigger_price,
            stop_price=stop_price,
            support_price=signal.support_price,
            timestamp=signal.timestamp,
        )

        if stock_code not in self._positions:
            self._positions[stock_code] = []
        self._positions[stock_code].append(position)

        logger.info(
            f"[{stock_code}] 新增止损监控: "
            f"type={signal.signal_type.value}, "
            f"entry={signal.trigger_price}, "
            f"stop={stop_price}"
        )

    def on_tick(self, stock_code: str, tick: TickData) -> None:
        """处理 Tick 数据，检查是否触发止损条件

        遍历该股票的所有活跃持仓，当价格跌破 stop_price 时：
        1. 推送 STOP_LOSS_ALERT 事件
        2. 从 active_positions 中移除该持仓

        Args:
            stock_code: 股票代码
            tick: Tick 数据
        """
        positions = self._positions.get(stock_code)
        if not positions:
            return

        current_price = tick.price
        triggered: list[_ActivePosition] = []

        for pos in positions:
            if current_price < pos.stop_price:
                triggered.append(pos)

        for pos in triggered:
            positions.remove(pos)
            self._emit_stop_loss_alert(stock_code, pos, current_price)

        # 清理空列表
        if not positions:
            del self._positions[stock_code]

    def get_active_positions(self, stock_code: str) -> list[dict]:
        """获取指定股票的活跃持仓监控列表

        Args:
            stock_code: 股票代码

        Returns:
            活跃持仓列表，每个元素包含 signal_type、entry_price、
            stop_price、timestamp
        """
        positions = self._positions.get(stock_code, [])
        return [
            {
                "signal_type": pos.signal_type.value,
                "entry_price": pos.entry_price,
                "stop_price": pos.stop_price,
                "support_price": pos.support_price,
                "timestamp": pos.timestamp,
            }
            for pos in positions
        ]

    def reset(self, stock_code: str) -> None:
        """重置指定股票的所有活跃持仓监控

        Args:
            stock_code: 股票代码
        """
        if stock_code in self._positions:
            count = len(self._positions[stock_code])
            del self._positions[stock_code]
            logger.info(
                f"[{stock_code}] 已重置止损监控，移除 {count} 个活跃持仓"
            )

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    def _emit_stop_loss_alert(
        self,
        stock_code: str,
        position: _ActivePosition,
        current_price: float,
    ) -> None:
        """构建并推送 STOP_LOSS_ALERT 事件

        Args:
            stock_code: 股票代码
            position: 触发止损的持仓记录
            current_price: 当前价格
        """
        # 计算回撤幅度百分比
        if position.entry_price != 0:
            drawdown = (
                (position.entry_price - current_price)
                / position.entry_price
                * 100
            )
        else:
            drawdown = 0.0

        # 映射信号类型到止损类型
        if position.signal_type == ScalpingSignalType.BREAKOUT_LONG:
            sl_type = StopLossSignalType.BREAKOUT_STOP
        else:
            sl_type = StopLossSignalType.SUPPORT_STOP

        alert = StopLossAlertData(
            stock_code=stock_code,
            signal_type=sl_type,
            entry_price=position.entry_price,
            support_price=position.support_price,
            current_price=current_price,
            drawdown_percent=round(drawdown, 4),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        logger.info(
            f"[{stock_code}] 止损提示: "
            f"type={sl_type.value}, "
            f"entry={position.entry_price}, "
            f"current={current_price}, "
            f"drawdown={drawdown:.2f}%"
        )

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._do_emit_alert(alert))
        except RuntimeError:
            logger.debug("无事件循环，跳过 STOP_LOSS_ALERT 推送")

    async def _do_emit_alert(self, alert: StopLossAlertData) -> None:
        """实际执行 STOP_LOSS_ALERT 事件推送"""
        try:
            await self._socket_manager.emit_to_all(
                SocketEvent.STOP_LOSS_ALERT,
                alert.model_dump(),
            )
        except Exception as e:
            logger.warning(f"推送 STOP_LOSS_ALERT 失败: {e}")
