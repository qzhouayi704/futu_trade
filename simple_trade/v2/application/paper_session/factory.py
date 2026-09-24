"""Translate eligible confirmations into explicitly hypothetical, frozen plans."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from ...domain.decisions import DecisionEvent
from ...domain.enums import EventType, StrategyStatus
from ...domain.paper_session import HK_ZONE, PaperExperiment
from ...domain.planning.models import EntrySetup, PaperExitPolicy, positive
from ...domain.serialization import require_aware
from ..positions.structural_exit import StructuralExitPolicy


@dataclass(frozen=True, slots=True)
class ResearchPlanResult:
    reason: str
    setup: EntrySetup | None = None


def _map(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("required signal evidence is missing")
    return value


def _time(value: object) -> datetime:
    result = datetime.fromisoformat(str(value))
    require_aware(result, "signal evidence time")
    return result


def _price(value: object) -> Decimal:
    result = Decimal(str(value))
    positive(result, "signal evidence value")
    return result


def research_plan(event: DecisionEvent, experiment: PaperExperiment, when: datetime) -> ResearchPlanResult:
    require_aware(when, "when")
    if (event.event_type is not EventType.BUY_CONFIRMED
            or event.new_state != StrategyStatus.CONFIRMED.value
            or event.payload.get("alert_eligible") is not True):
        return ResearchPlanResult("NOT_FORMAL_CONFIRMATION")
    if event.stock_code not in experiment.stock_codes:
        return ResearchPlanResult("OUTSIDE_EXPERIMENT_UNIVERSE")
    if (event.strategy_version != experiment.strategy_version
            or event.payload.get("lifecycle_strategy_source") != experiment.strategy_id):
        return ResearchPlanResult("EXPERIMENT_STRATEGY_MISMATCH")
    interval, exit_at = experiment.interval_at(when), experiment.exit_at(when)
    if interval is None or exit_at is None or exit_at <= when:
        return ResearchPlanResult("TRADING_INTERVAL_UNAVAILABLE_OR_CLOSED")
    if not 0 <= (when - event.received_time).total_seconds() <= experiment.maximum_signal_age_seconds:
        return ResearchPlanResult("SIGNAL_NOT_YET_KNOWN_OR_STALE")
    try:
        snapshot = _map(event.payload.get("feature_snapshot"))
        quote, position = _map(snapshot.get("quote")), _map(snapshot.get("price_position"))
        if (snapshot.get("stock_code") != event.stock_code or quote.get("stock_code") != event.stock_code
                or snapshot.get("quality") != "GOOD" or quote.get("quality") != "GOOD"
                or position.get("quality") != "GOOD"):
            return ResearchPlanResult("SIGNAL_EVIDENCE_QUALITY_INVALID")
        for observed in (event.exchange_time, _time(snapshot.get("computed_at")),
                         _time(quote.get("exchange_time"))):
            if (observed > event.received_time
                    or not 0 <= (when - observed).total_seconds() <= experiment.maximum_signal_age_seconds):
                return ResearchPlanResult("SIGNAL_EVIDENCE_NOT_YET_KNOWN_OR_STALE")
        if _time(position.get("as_of")) > event.received_time:
            return ResearchPlanResult("SIGNAL_EVIDENCE_NOT_YET_KNOWN_OR_STALE")
        lot = _map(quote.get("lot_size_observation"))
        observed_at, quote_time = _time(lot.get("observed_at")), _time(lot.get("quote_exchange_time"))
        if (lot.get("stock_code") != event.stock_code or not lot.get("source")
                or type(lot.get("lot_size")) is not int or lot["lot_size"] <= 0
                or not 0 <= (event.received_time - observed_at).total_seconds() <= 21600
                or quote_time > _time(quote.get("exchange_time"))
                or quote_time > observed_at
                or quote_time.astimezone(HK_ZONE).date() != when.astimezone(HK_ZONE).date()):
            return ResearchPlanResult("LOT_SIZE_EVIDENCE_INVALID")
        price = _price(quote.get("last_price"))
        atr = _price(position.get("atr_percent")) / 100
        production_exit = experiment.exit_policy is PaperExitPolicy.PRODUCTION_RULES
        distance = (Decimal(str(-StructuralExitPolicy.HARD_STOP_PCT)) / 100 if production_exit
                    else max(experiment.minimum_stop_fraction, atr * experiment.atr_stop_multiple))
        if distance > experiment.maximum_stop_fraction:
            return ResearchPlanResult("RESEARCH_STOP_TOO_WIDE")
        entry_min = price * (1 - experiment.pullback_fraction)
        # A lower fill has a lower cost-based stop; reserve against that worst case.
        stop_price = (entry_min if production_exit else price) * (1 - distance)
        valid_until = min(when + timedelta(seconds=experiment.entry_ttl_seconds), interval.closes_at, exit_at)
        if (valid_until - when).total_seconds() <= experiment.policy.latency_seconds:
            return ResearchPlanResult("ENTRY_WINDOW_TOO_SHORT")
        day = when.astimezone(HK_ZONE).date().isoformat()
        return ResearchPlanResult("RESEARCH_SETUP_CREATED", EntrySetup(
            setup_id=f"{experiment.experiment_id}:{event.stock_code}:{day}",
            source_event_id=event.event_id, strategy_id=experiment.strategy_id,
            strategy_version=f"{event.strategy_version}:paper:{experiment.experiment_id}",
            stock_code=event.stock_code, created_at=when, valid_until=valid_until, exit_at=exit_at,
            entry_min=entry_min,
            entry_limit=price * (1 + experiment.chase_fraction), stop_price=stop_price,
            lot_size=lot["lot_size"], position_fraction=experiment.policy.position_fraction,
            exit_policy=experiment.exit_policy,
        ))
    except (TypeError, ValueError, InvalidOperation, OverflowError):
        return ResearchPlanResult("SIGNAL_EVIDENCE_MISSING_OR_INVALID")
