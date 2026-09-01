"""In-memory V1 alert versus V2 state-transition scoreboard."""

from dataclasses import dataclass
from datetime import datetime, timezone
import threading

from ...domain.decisions import DecisionEvent
from ...domain.enums import EventType
from ...domain.serialization import require_aware, require_stock_code


@dataclass(frozen=True, slots=True, kw_only=True)
class LegacySignalObservation:
    stock_code: str
    observed_at: datetime
    direction: str
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", require_stock_code(self.stock_code))
        require_aware(self.observed_at, "observed_at")


@dataclass(frozen=True, slots=True)
class DualTrackReport:
    legacy_rising: int
    v2_confirmed: int
    matched: int
    legacy_only: int
    v2_only: int
    v2_invalidated: int

    def to_markdown(self) -> str:
        return "\n".join(
            (
                "| 指标 | 数量 |",
                "|---|---:|",
                f"| V1 上升提醒 | {self.legacy_rising} |",
                f"| V2 买入确认 | {self.v2_confirmed} |",
                f"| 5 分钟内同股匹配 | {self.matched} |",
                f"| 仅 V1 | {self.legacy_only} |",
                f"| 仅 V2 | {self.v2_only} |",
                f"| V2 后续失效 | {self.v2_invalidated} |",
            )
        )


class DualTrackScoreboard:
    def __init__(self, max_records: int = 10_000) -> None:
        if max_records <= 0:
            raise ValueError("max_records must be positive")
        self._max_records = max_records
        self._legacy: list[LegacySignalObservation] = []
        self._v2: list[DecisionEvent] = []
        self._lock = threading.RLock()

    def record_legacy(self, observation: LegacySignalObservation) -> None:
        with self._lock:
            self._legacy.append(observation)
            del self._legacy[:-self._max_records]

    def record_legacy_payload(self, payload: dict) -> None:
        code = payload.get("stock_code") or payload.get("code")
        if not code:
            return
        observed_at = self._parse_time(payload.get("timestamp"))
        self.record_legacy(
            LegacySignalObservation(
                stock_code=str(code),
                observed_at=observed_at,
                direction=str(payload.get("direction") or "UNKNOWN").upper(),
                reason=str(payload.get("reason") or ""),
            )
        )

    def record_v2(self, event: DecisionEvent) -> None:
        with self._lock:
            self._v2.append(event)
            del self._v2[:-self._max_records]

    def report(self, *, match_seconds: int = 300) -> DualTrackReport:
        with self._lock:
            legacy = tuple(item for item in self._legacy if item.direction == "RISING")
            confirmed = tuple(
                event for event in self._v2 if event.event_type is EventType.BUY_CONFIRMED
            )
            invalidated = sum(
                event.event_type in {EventType.BUY_INVALIDATED, EventType.CANDIDATE_INVALIDATED}
                for event in self._v2
            )
        used: set[int] = set()
        matched = 0
        for event in confirmed:
            candidates = [
                (index, abs((item.observed_at - event.exchange_time).total_seconds()))
                for index, item in enumerate(legacy)
                if index not in used and item.stock_code == event.stock_code
            ]
            if not candidates:
                continue
            index, distance = min(candidates, key=lambda item: item[1])
            if distance <= match_seconds:
                used.add(index)
                matched += 1
        return DualTrackReport(
            legacy_rising=len(legacy),
            v2_confirmed=len(confirmed),
            matched=matched,
            legacy_only=len(legacy) - matched,
            v2_only=len(confirmed) - matched,
            v2_invalidated=invalidated,
        )

    @staticmethod
    def _parse_time(value: object) -> datetime:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, (int, float)):
            parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
        elif value:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        else:
            parsed = datetime.now(timezone.utc)
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
