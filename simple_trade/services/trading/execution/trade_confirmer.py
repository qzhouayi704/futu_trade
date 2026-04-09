#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易确认管理器

在自动交易执行前，通过 WebSocket 推送确认请求给前端，
等待用户确认/拒绝或超时后决定是否执行交易。
支持自动确认模式（跳过人工确认直接执行）。
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional

from ....websocket.events import SocketEvent


@dataclass
class PendingConfirmation:
    """待确认的交易请求"""
    signal_id: int
    stock_code: str
    trade_type: str       # BUY / SELL
    price: float
    quantity: int
    timeout: float        # 超时秒数
    created_at: datetime
    status: str = 'pending'  # pending / confirmed / rejected / timeout


class TradeConfirmer:
    """
    交易确认管理器

    职责：
    - 管理待确认交易的生命周期
    - 通过 WebSocket 推送确认请求到前端
    - 等待用户响应或超时
    - 支持自动确认模式
    """

    def __init__(self, socket_manager, config: Optional[Dict] = None):
        """
        初始化交易确认管理器

        Args:
            socket_manager: WebSocket 管理器，用于推送事件
            config: 配置字典，支持 auto_confirm 和 confirm_timeout
        """
        config = config or {}
        self.socket_manager = socket_manager
        self.auto_confirm: bool = config.get('auto_confirm', False)
        self.confirm_timeout: float = config.get('confirm_timeout', 30)
        self.pending: Dict[int, PendingConfirmation] = {}

    async def request_confirmation(self, signal: Dict) -> str:
        """
        请求交易确认

        Args:
            signal: 信号字典，需包含 id, stock_code, stock_name,
                    signal_type, price, 可选 quantity, reason

        Returns:
            'confirmed' / 'rejected' / 'timeout'
        """
        # 自动确认模式：直接返回确认
        if self.auto_confirm:
            logging.info(f"自动确认模式：信号 {signal['id']} 直接确认")
            return 'confirmed'

        confirmation = PendingConfirmation(
            signal_id=signal['id'],
            stock_code=signal['stock_code'],
            trade_type=signal['signal_type'],
            price=signal['price'],
            quantity=signal.get('quantity', 0),
            timeout=self.confirm_timeout,
            created_at=datetime.now(),
        )
        self.pending[signal['id']] = confirmation

        # 推送确认请求到前端
        await self._emit_confirm_request(signal)

        # 等待响应或超时
        result = await self._wait_for_response(signal['id'])

        logging.info(
            f"交易确认结果: 信号 {signal['id']} "
            f"({signal['stock_code']}) -> {result}"
        )
        return result

    def handle_response(self, signal_id: int, confirmed: bool) -> bool:
        """
        处理前端的确认/拒绝响应

        Args:
            signal_id: 信号 ID
            confirmed: True=确认执行, False=拒绝

        Returns:
            是否成功处理（信号是否在待确认列表中）
        """
        if signal_id not in self.pending:
            logging.warning(f"收到未知信号的确认响应: {signal_id}")
            return False

        pending = self.pending[signal_id]
        if pending.status != 'pending':
            logging.warning(
                f"信号 {signal_id} 已处理 (status={pending.status})，"
                f"忽略重复响应"
            )
            return False

        pending.status = 'confirmed' if confirmed else 'rejected'
        action = "确认" if confirmed else "拒绝"
        logging.info(f"用户{action}交易: 信号 {signal_id}")
        return True

    def get_pending_count(self) -> int:
        """获取待确认交易数量"""
        return sum(
            1 for p in self.pending.values() if p.status == 'pending'
        )

    def cleanup_expired(self):
        """清理已完成的确认记录（非 pending 状态）"""
        expired_ids = [
            sid for sid, p in self.pending.items()
            if p.status != 'pending'
        ]
        for sid in expired_ids:
            del self.pending[sid]

    # ==================== 内部方法 ====================

    async def _emit_confirm_request(self, signal: Dict):
        """推送确认请求到前端"""
        data = {
            'signal_id': signal['id'],
            'stock_code': signal['stock_code'],
            'stock_name': signal.get('stock_name', ''),
            'trade_type': signal['signal_type'],
            'price': signal['price'],
            'reason': signal.get('reason', ''),
            'timeout': self.confirm_timeout,
            'timestamp': datetime.now().isoformat(),
        }
        await self.socket_manager.emit_to_all(
            SocketEvent.TRADE_CONFIRM_REQUEST, data
        )

    async def _wait_for_response(self, signal_id: int) -> str:
        """
        等待用户响应或超时

        以 0.5 秒为间隔轮询 pending 状态，
        超时后自动标记为 timeout。

        Returns:
            'confirmed' / 'rejected' / 'timeout'
        """
        poll_interval = 0.5
        elapsed = 0.0

        while elapsed < self.confirm_timeout:
            pending = self.pending.get(signal_id)
            if not pending:
                return 'timeout'

            if pending.status != 'pending':
                return pending.status

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        # 超时处理
        if signal_id in self.pending:
            self.pending[signal_id].status = 'timeout'
            logging.warning(
                f"交易确认超时: 信号 {signal_id}，"
                f"超时时间 {self.confirm_timeout}s"
            )

        return 'timeout'
