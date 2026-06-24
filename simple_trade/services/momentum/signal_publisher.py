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
        # BSR
        "EXHAUSTION": "HIGH", "SELL_MOMENTUM": "HIGH",
        "BUY_MOMENTUM": "MEDIUM", "RECOVERY": "MEDIUM",
        # Delta
        "DELTA_TURN_DOWN": "HIGH", "DELTA_TURN_UP": "MEDIUM",
        "BEARISH_DIVERGENCE": "HIGH", "BULLISH_DIVERGENCE": "MEDIUM",
        "EXTREME_DELTA": "LOW",
        # 速度
        "ACCELERATE_BUY": "MEDIUM", "ACCELERATE_SELL": "HIGH",
        "VOLUME_SPIKE": "LOW", "VOLUME_DRY": "LOW",
        # 大单
        "BIG_BUY_CLUSTER": "HIGH", "BIG_SELL_CLUSTER": "HIGH",
        "BIG_ORDER_BATTLE": "MEDIUM",
        # VWAP
        "VWAP_BOUNCE": "MEDIUM", "VWAP_BREAK": "HIGH",
        "OVERBOUGHT": "LOW", "OVERSOLD": "LOW",
        # 吸筹/派发
        "ACCUMULATION": "HIGH", "DISTRIBUTION": "HIGH",
        # 共振
        "STRONG_BUY": "HIGH", "STRONG_SELL": "HIGH",
        "MODERATE_BUY": "MEDIUM", "MODERATE_SELL": "MEDIUM",
    }

    # BUY/SELL分类
    BUY_TYPES = {
        "BUY_MOMENTUM", "RECOVERY", "BULLISH_DIVERGENCE", "DELTA_TURN_UP",
        "ACCELERATE_BUY", "BIG_BUY_CLUSTER", "VWAP_BOUNCE", "OVERSOLD",
        "ACCUMULATION", "STRONG_BUY", "MODERATE_BUY",
    }
    SELL_TYPES = {
        "SELL_MOMENTUM", "EXHAUSTION", "BEARISH_DIVERGENCE", "DELTA_TURN_DOWN",
        "ACCELERATE_SELL", "BIG_SELL_CLUSTER", "VWAP_BREAK", "OVERBOUGHT",
        "DISTRIBUTION", "STRONG_SELL", "MODERATE_SELL",
    }

    def __init__(self, container):
        self.container = container
        self._recent_signals: dict[str, float] = {}  # stock_code:type → 上次发送时间
        self._cooldown = 300  # 同类信号冷却5分钟
        # 持仓集合缓存（供"持仓风险"告警判定；momentum 作为 sniper 之外的第二传感器为持仓兜底）
        self._held_codes: set = set()
        self._held_ts: float = 0.0
        self._held_ttl = 60  # 持仓集合缓存秒数

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

        # 3. 持仓股的卖出风险 → "持仓风险" CRITICAL 告警（绕过仅 HIGH 才推的门）。
        #    momentum 是 sniper 之外的第二传感器：2026-06-23 HK.06871 的 EXTREME_DELTA/VWAP_BREAK
        #    @09:49 早于 sniper 抓到风险，却因非持仓路由从未变成"持仓风险"——此处补上。
        held_risk = False
        if signal.signal_type in self.SELL_TYPES:
            held_codes = await self._get_held_codes()
            if signal.stock_code in held_codes:
                held_risk = True
                await self._send_held_risk_wechat(signal)

        # 4. 高优先级 → 微信（持仓风险已单独推过，避免重复）
        if priority == "HIGH" and not held_risk:
            await self._send_wechat(signal)

        # 5. 接入决策引擎 (STRONG_BUY / MODERATE_BUY)
        if signal.signal_type in ("STRONG_BUY", "MODERATE_BUY"):
            try:
                engine = getattr(self.container, "trade_decision_engine", None)
                if engine:
                    await engine.on_momentum_signal(signal)
            except Exception as e:
                logger.error(f"发送信号至决策引擎失败: {e}", exc_info=True)

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
            if signal.signal_type in self.BUY_TYPES:
                signal_type = "BUY"
            elif signal.signal_type in self.SELL_TYPES:
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
                    "price": getattr(signal, 'price', 0),
                    "priority": priority,
                    "confidence": getattr(signal, 'confidence', 0.5),
                    "bsr": getattr(signal, 'bsr', None),
                    "cum_delta": getattr(signal, 'cum_delta', None),
                    "timestamp": getattr(signal, 'timestamp', 0),
                    "dimensions": getattr(signal, 'dimensions', None),
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

    async def _get_held_codes(self) -> set:
        """带缓存(60s)的持仓集合。失败保留上次结果、绝不抛出（不能打断信号发布）。"""
        import time as _time
        import asyncio
        now = _time.time()
        if now - self._held_ts < self._held_ttl:
            return self._held_codes
        try:
            fts = getattr(self.container, 'futu_trade_service', None)
            if fts:
                loop = asyncio.get_running_loop()
                res = await loop.run_in_executor(None, fts.get_positions)
                if res and res.get('success'):
                    self._held_codes = {
                        p.get('stock_code', '') for p in res.get('positions', [])
                        if p.get('stock_code') and (p.get('qty', 0) or 0) > 0
                    }
            self._held_ts = now
        except Exception as e:
            logger.debug(f"动量发布器刷新持仓集合失败: {e}")
        return self._held_codes

    async def _send_held_risk_wechat(self, signal):
        """持仓股卖出风险 → "⚠️持仓风险" CRITICAL 告警（与 sniper 同款，独立去重键）。"""
        try:
            wechat = getattr(self.container, 'wechat_alert_service', None)
            if not (wechat and getattr(wechat, 'enabled', False)):
                return
            from ..alert.wechat_alert import AlertLevel
            await wechat.send(
                level=AlertLevel.CRITICAL,
                title=f"⚠️持仓风险 — {signal.stock_code}",
                content=(
                    "**【你的持仓·动量预警】**\n"
                    f"- 类型：{signal.signal_type}\n"
                    f"- 价格：{signal.price}\n"
                    f"- {signal.description}"
                ),
                dedup_key=f"hold_risk:{signal.stock_code}:{signal.signal_type}",
                category="持仓风险",
                stock_code=signal.stock_code,
                price=getattr(signal, 'price', None),
            )
        except Exception as e:
            logger.debug(f"持仓风险微信通知失败: {e}")
