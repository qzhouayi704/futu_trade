"""Idempotent notification delivery log using the database single writer."""

from datetime import datetime

from ...domain.decisions import NotificationEvent
from ..db_write import submit_write


class SqliteNotificationStore:
    def __init__(self, db, write_timeout: float) -> None:
        self._db = db
        self._write_timeout = write_timeout

    async def claim(self, event: NotificationEvent) -> bool:
        return await submit_write(
            self._db, self._claim_sync, event, timeout=self._write_timeout
        )

    async def mark(
        self,
        event: NotificationEvent,
        *,
        status: str,
        attempts: int,
        error: str | None = None,
        delivered_at: datetime | None = None,
    ) -> None:
        await submit_write(
            self._db,
            self._mark_sync,
            event,
            status,
            attempts,
            error,
            delivered_at,
            timeout=self._write_timeout,
        )

    def _claim_sync(self, event: NotificationEvent) -> bool:
        with self._db.transaction() as cursor:
            cursor.execute(
                "INSERT OR IGNORE INTO v2_notification_log "
                "(decision_event_id, idempotency_key, channel, status, attempt_count, expires_at) "
                "VALUES (?, ?, ?, 'PENDING', 0, ?)",
                (
                    event.decision_event_id,
                    event.idempotency_key,
                    event.channel.value,
                    event.expires_at.isoformat() if event.expires_at else None,
                ),
            )
            return cursor.rowcount == 1

    def _mark_sync(
        self,
        event: NotificationEvent,
        status: str,
        attempts: int,
        error: str | None,
        delivered_at: datetime | None,
    ) -> None:
        with self._db.transaction() as cursor:
            cursor.execute(
                "UPDATE v2_notification_log SET status=?, attempt_count=?, last_error=?, "
                "delivered_at=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE idempotency_key=? AND channel=?",
                (
                    status,
                    attempts,
                    error,
                    delivered_at.isoformat() if delivered_at else None,
                    event.idempotency_key,
                    event.channel.value,
                ),
            )
