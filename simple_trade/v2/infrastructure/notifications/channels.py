"""V2 notification channels backed by existing WebSocket and WeChat services."""

from ...domain.decisions import NotificationEvent
from ...domain.enums import NotificationChannel, NotificationDeliveryResult


class UnifiedNotifier:
    def __init__(self, socket_manager=None, wechat_service=None) -> None:
        self._socket = socket_manager
        self._wechat = wechat_service

    async def send(
        self, event: NotificationEvent, *, attempt: int
    ) -> NotificationDeliveryResult:
        if event.channel in {NotificationChannel.WEBSOCKET, NotificationChannel.FRONTEND}:
            return await self._websocket(event)
        if event.channel is NotificationChannel.WECHAT:
            return await self._wechat_send(event, attempt)
        return NotificationDeliveryResult.FAILED

    async def _websocket(self, event: NotificationEvent) -> NotificationDeliveryResult:
        if self._socket is None:
            return NotificationDeliveryResult.COLLAPSED
        try:
            await self._socket.emit_to_all(
                "v2_trade_alert",
                {
                    "event_id": event.event_id,
                    "decision_event_id": event.decision_event_id,
                    "stock_code": event.stock_code,
                    "title": event.title,
                    "message": event.message,
                    "exchange_time": event.exchange_time.isoformat(),
                    "strategy_version": event.strategy_version,
                },
            )
            return NotificationDeliveryResult.DELIVERED
        except Exception:
            return NotificationDeliveryResult.FAILED

    async def _wechat_send(
        self, event: NotificationEvent, attempt: int
    ) -> NotificationDeliveryResult:
        if self._wechat is None or not getattr(self._wechat, "enabled", False):
            return NotificationDeliveryResult.COLLAPSED
        try:
            from ....services.alert.wechat_alert import (
                AlertLevel,
                SEND_DELIVERED,
                SEND_SUPPRESSED,
            )

            critical = "退出" in event.title or "止损" in event.title
            level = AlertLevel.CRITICAL if critical else AlertLevel.INFO
            outcome = await self._wechat.send_with_outcome(
                level,
                event.title,
                event.message,
                event.idempotency_key,
                category="持仓风险" if critical else "交易信号",
                stock_code=event.stock_code,
                priority=100 if critical else None,
                retry=attempt > 1,
            )
            if outcome == SEND_DELIVERED:
                return NotificationDeliveryResult.DELIVERED
            if outcome == SEND_SUPPRESSED:
                return NotificationDeliveryResult.COLLAPSED
            return NotificationDeliveryResult.FAILED
        except Exception:
            return NotificationDeliveryResult.FAILED
