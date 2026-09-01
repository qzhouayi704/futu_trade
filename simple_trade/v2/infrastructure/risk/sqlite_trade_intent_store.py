"""Persist risk-assessed intents through the existing single writer."""

from datetime import datetime
import json

from ...domain.orders import RiskDecision, TradeIntent
from ...domain.serialization import canonical_json, to_primitive
from ..db_write import submit_write


class SqliteTradeIntentStore:
    def __init__(self, db, write_timeout: float) -> None:
        self._db = db
        self._write_timeout = write_timeout

    async def record(self, intent: TradeIntent, risk: RiskDecision) -> bool:
        return await submit_write(
            self._db,
            self._record_sync,
            intent,
            risk,
            timeout=self._write_timeout,
        )

    def _record_sync(self, intent: TradeIntent, risk: RiskDecision) -> bool:
        now = risk.checked_at.isoformat()
        with self._db.transaction() as cursor:
            cursor.execute(
                "INSERT OR IGNORE INTO v2_trade_intents "
                "(intent_id, source_event_id, intent_type, mode, sell_leg_json, "
                "buy_leg_json, risk_result, risk_reason_json, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    intent.intent_id,
                    intent.source_event_id,
                    intent.intent_type.value,
                    intent.mode.value,
                    self._leg_json(intent.sell_leg),
                    self._leg_json(intent.buy_leg),
                    risk.result.value,
                    canonical_json(risk.reason_codes),
                    f"RISK_{risk.result.value}",
                    intent.created_at.isoformat(),
                    now,
                ),
            )
            return cursor.rowcount == 1

    @staticmethod
    def _leg_json(leg) -> str | None:
        if leg is None:
            return None
        return json.dumps(to_primitive(leg), ensure_ascii=True, sort_keys=True)
