"""Convert assessed intents into stable channel notifications."""

from datetime import timedelta

from ...domain.decisions import NotificationEvent
from ...domain.enums import EventType, IntentType, NotificationChannel, RiskResult
from ...domain.events import RiskAssessedEvent


class NotificationFormatter:
    def __init__(self, *, expiry_seconds: int) -> None:
        self._expiry = timedelta(seconds=expiry_seconds)

    def build(self, source: RiskAssessedEvent) -> tuple[NotificationEvent, ...]:
        title = self._title(source)
        message = self._message(source)
        return tuple(
            NotificationEvent(
                event_type=EventType.NOTIFICATION_REQUESTED,
                stock_code=source.stock_code,
                exchange_time=source.exchange_time,
                received_time=source.received_time,
                source="v2.notification-formatter",
                schema_version=source.schema_version,
                strategy_version=source.strategy_version,
                correlation_id=source.correlation_id,
                decision_event_id=source.source_decision_event_id,
                channel=channel,
                idempotency_key=self._idempotency(source, channel),
                title=title,
                message=message,
                expires_at=source.received_time + self._expiry,
            )
            for channel in (NotificationChannel.WEBSOCKET, NotificationChannel.WECHAT)
        )

    @staticmethod
    def _title(source: RiskAssessedEvent) -> str:
        approved = source.risk.result is RiskResult.APPROVED
        if source.intent.intent_type is IntentType.BUY:
            return "V2 买入确认" if approved else "V2 买入观察（风控未通过）"
        if source.intent.intent_type is IntentType.SELL:
            return "V2 持仓退出提醒" if approved else "V2 持仓风险（执行受限）"
        return "V2 换票建议" if approved else "V2 换票观察（风控未通过）"

    @staticmethod
    def _message(source: RiskAssessedEvent) -> str:
        intent = source.intent
        lines = [f"- 股票：**{source.stock_code}**"]
        if intent.sell_leg is not None:
            lines.append(
                f"- 卖出参考：{intent.sell_leg.quantity} 股 @ "
                f"{intent.sell_leg.reference_price:.3f}"
            )
        if intent.buy_leg is not None:
            lines.append(
                f"- 买入参考：{intent.buy_leg.stock_code} "
                f"{intent.buy_leg.quantity} 股 @ {intent.buy_leg.reference_price:.3f}"
            )
        lines.append(f"- 风控：**{source.risk.result.value}**")
        lines.append(f"- 原因：{', '.join(source.risk.reason_codes)}")
        lines.append("- 当前仅为提醒，不会自动下单")
        return "\n".join(lines)

    @staticmethod
    def _idempotency(source: RiskAssessedEvent, channel: NotificationChannel) -> str:
        if source.intent.intent_type is IntentType.BUY:
            bucket = int(source.exchange_time.timestamp() // 600)
            identity = f"{source.stock_code}:BUY:{source.risk.result.value}:{bucket}"
        else:
            identity = source.source_decision_event_id
        return f"{source.strategy_version}:{identity}:{channel.value}"
