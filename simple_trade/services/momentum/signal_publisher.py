#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动量信号发布器

将动量引擎检测到的信号:
1. 写入 trade_signals 表
2. 通过 WebSocket 推送到前端
3. 高优先级信号发送企业微信
"""

import logging
from typing import Optional, Union

from .bsr_monitor import MomentumSignal, MomentumState
from .delta_detector import DeltaSignal

logger = logging.getLogger(__name__)


class SignalPublisher:
    """动量信号发布器"""

    # 信号优先级映射
    SIGNAL_PRIORITY = {
        "EXHAUSTION": "HIGH",         # 动量衰竭 → 高优
        "SELL_MOMENTUM": "HIGH",      # 卖方碾压 → 高优
        "BUY_MOMENTUM": "MEDIUM",     # 买方强势 → 中优
        "RECOVERY": "MEDIUM",         # 动量恢复 → 中优
        "DELTA_TURN_DOWN": "HIGH",    # Delta拐头 → 高优
        "DELTA_TURN_UP": "MEDIUM",    # Delta回升 → 中优
        "BEARISH_DIVERGENCE": "HIGH", # 看空背离 → 高优
        "BULLISH_DIVERGENCE": "MEDIUM",
        "EXTREME_DELTA": "LOW",       # 极端值 → 低优
    }

    def __init__(self, container):
        self.container = container
        self._recent_signals: dict[str, float] = {}  # stock_code:type → 上次发送时间
        self._cooldown = 300  # 同类信号冷却5分钟

    async def publish(self, signal: Union[MomentumSignal, DeltaSignal]):
        """发布信号"""
        import time

        # 冷却检查
        key = f"{signal.stock_code}:{signal.signal_type}"
        now = time.time()
        last_sent = self._recent_signals.get(key, 0)
        if now - last_sent < self._cooldown:
            return
        self._recent_signals[key] = now

        priority = self.SIGNAL_PRIORITY.get(signal.signal_type, "LOW")

        logger.info(
            f"[MomentumSignal] [{priority}] {signal.stock_code} "
            f"{signal.signal_type}: {signal.description}"
        )

        # 1. 写入DB
        await self._save_to_db(signal, priority)

        # 2. WebSocket推送
        await self._push_websocket(signal, priority)

        # 3. 高优先级 → 微信
        if priority == "HIGH":
            await self._send_wechat(signal)

    async def _save_to_db(self, signal, priority: str):
        """写入trade_signals表"""
        try:
            db = self.container.db_manager

            # 查找stock_id
            rows = db.execute_query(
                "SELECT id FROM stocks WHERE code=?",
                (signal.stock_code,)
            )
            if not rows:
                return

            stock_id = rows[0][0]

            # 信号类型映射
            if signal.signal_type in ("BUY_MOMENTUM", "RECOVERY", "BULLISH_DIVERGENCE", "DELTA_TURN_UP"):
                signal_type = "BUY"
            elif signal.signal_type in ("SELL_MOMENTUM", "EXHAUSTION", "BEARISH_DIVERGENCE", "DELTA_TURN_DOWN"):
                signal_type = "SELL"
            else:
                signal_type = "WATCH"

            db.execute_update(
                """INSERT INTO trade_signals
                   (stock_id, signal_type, signal_price, condition_text,
                    strategy_id, strategy_name)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (stock_id, signal_type, signal.price,
                 signal.description,
                 f"momentum_{signal.signal_type}",
                 "动量引擎")
            )
        except Exception as e:
            logger.error(f"保存动量信号失败: {e}")

    async def _push_websocket(self, signal, priority: str):
        """WebSocket推送"""
        try:
            from ...websocket.socket_manager import SocketManager
            from ...websocket.events import SocketEvent

            socket_manager = getattr(self.container, '_socket_manager', None)
            if not socket_manager:
                # 尝试从dependencies获取
                from ...dependencies import get_socket_manager
                socket_manager = get_socket_manager()

            if socket_manager:
                data = {
                    "stock_code": signal.stock_code,
                    "signal_type": signal.signal_type,
                    "description": signal.description,
                    "price": signal.price,
                    "priority": priority,
                    "confidence": getattr(signal, 'confidence', 0.5),
                    "bsr": getattr(signal, 'bsr', None),
                    "cum_delta": signal.cum_delta,
                    "timestamp": signal.timestamp,
                }
                await socket_manager.emit_to_all(
                    "momentum_signal", data
                )
        except Exception as e:
            logger.debug(f"WebSocket推送失败: {e}")

    async def _send_wechat(self, signal):
        """企业微信通知"""
        try:
            wechat = getattr(self.container, 'wechat_alert_service', None)
            if not wechat:
                return

            emoji = "🟢" if "BUY" in signal.signal_type or "RECOVERY" in signal.signal_type else "🔴"
            msg = (
                f"{emoji} 动量信号 | {signal.stock_code}\n"
                f"类型: {signal.signal_type}\n"
                f"价格: {signal.price}\n"
                f"{signal.description}"
            )
            await wechat.send_text(msg)
        except Exception as e:
            logger.debug(f"微信通知失败: {e}")
