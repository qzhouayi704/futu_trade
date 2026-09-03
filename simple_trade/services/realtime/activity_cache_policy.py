"""Runtime policy for activity-cache freshness and refresh cadence."""

from dataclasses import dataclass
from datetime import datetime, time
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class ActivityCachePolicy:
    """Keep activity discovery fresh without rebuilding the whole cache."""

    active_ttl_seconds: int = 300
    inactive_ttl_seconds: int = 120
    failed_ttl_seconds: int = 30
    opening_refilter_interval_seconds: int = 120
    regular_refilter_interval_seconds: int = 300

    @classmethod
    def from_config(cls, config: Any = None) -> "ActivityCachePolicy":
        raw = getattr(config, "realtime_activity_filter", {}) if config else {}
        if raw is None:
            raw = {}

        def value(name: str, default: int) -> int:
            getter = getattr(raw, "get", None)
            result = getter(name, default) if getter else getattr(raw, name, default)
            try:
                return max(1, int(result))
            except (TypeError, ValueError):
                return default

        return cls(
            active_ttl_seconds=value("active_cache_ttl_seconds", 300),
            inactive_ttl_seconds=value("inactive_cache_ttl_seconds", 120),
            failed_ttl_seconds=value("failed_cache_ttl_seconds", 30),
            opening_refilter_interval_seconds=value(
                "opening_refilter_interval_seconds", 120
            ),
            regular_refilter_interval_seconds=value(
                "regular_refilter_interval_seconds", 300
            ),
        )

    def ttl_seconds(self, record: Mapping[str, Any]) -> int:
        if float(record.get("activity_score", 0) or 0) == -1:
            return self.failed_ttl_seconds
        if bool(record.get("is_active")):
            return self.active_ttl_seconds
        return self.inactive_ttl_seconds

    def is_fresh(
        self,
        record: Mapping[str, Any],
        now: Optional[datetime] = None,
    ) -> bool:
        checked_at = self._parse_datetime(record.get("created_at"))
        if checked_at is None:
            return False
        current = now or datetime.now()
        if current.tzinfo is not None and checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=current.tzinfo)
        elif current.tzinfo is None and checked_at.tzinfo is not None:
            checked_at = checked_at.replace(tzinfo=None)
        age_seconds = max(0.0, (current - checked_at).total_seconds())
        return age_seconds < self.ttl_seconds(record)

    def refilter_interval_seconds(self, now: Optional[datetime] = None) -> int:
        current_time = (now or datetime.now()).time()
        if self._is_opening_discovery_window(current_time):
            return self.opening_refilter_interval_seconds
        return self.regular_refilter_interval_seconds

    @staticmethod
    def _is_opening_discovery_window(current_time: time) -> bool:
        return (
            time(9, 30) <= current_time < time(10, 0)
            or time(13, 0) <= current_time < time(13, 30)
        )

    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value
        if not value:
            return None
        text = str(value).strip()
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
