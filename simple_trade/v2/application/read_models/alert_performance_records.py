"""Normalize and collapse alert records before performance evaluation."""

from collections import Counter
import json

from ....utils.trade_time import is_hk_continuous_session, market_datetime
from ..strategy.assessments import signal_permission
from .alert_performance_metrics import number


STAGE_RANK = {"SETUP": 1, "WATCHING": 2, "CONFIRMED": 3}
CANDIDATE_EVENT_TYPES = (
    "CANDIDATE_ENTERED",
    "CANDIDATE_UPDATED",
    "CANDIDATE_INVALIDATED",
    "CANDIDATE_REJECTED",
    "BUY_CONFIRMED",
    "BUY_INVALIDATED",
)


def _portfolio_sources(payload: dict) -> list[str]:
    portfolio = payload.get("strategy_portfolio") or {}
    if not isinstance(portfolio, dict):
        return []
    sources = {
        str(value) for value in portfolio.get("strategy_sources", [])
        if str(value).strip()
    }
    lifecycle_source = str(payload.get("lifecycle_strategy_source") or "").strip()
    if lifecycle_source:
        sources.add(lifecycle_source)
    for nomination in portfolio.get("nominations", []):
        if not isinstance(nomination, dict):
            continue
        strategy_id = str(nomination.get("strategy_id") or "").strip()
        if strategy_id and nomination.get("stage") in {"WATCH", "CONFIRMED"}:
            sources.add(strategy_id)
    return sorted(sources)


def eligible_delivered(rows: list[tuple]) -> tuple[list[tuple], dict]:
    eligible = []
    excluded = Counter()
    excluded_rows = 0
    for row in _chronological(rows):
        reasons = []
        if str(row[7] or "").upper() != "APPROVED":
            reasons.append("RISK_NOT_APPROVED")
        if not _is_regular_session(str(row[2]), str(row[3])):
            reasons.append("OUTSIDE_REGULAR_SESSION")
        if reasons:
            excluded_rows += 1
            excluded.update(reasons)
        else:
            eligible.append(row)
    return eligible, {
        "total": excluded_rows,
        "by_reason": dict(sorted(excluded.items())),
    }


def collapse_delivered(rows: list[tuple]) -> list[dict]:
    collapsed: dict[tuple[str, str, str, str], dict] = {}
    for row in _chronological(rows):
        intent_type = str(row[6])
        leg_json = row[9] if intent_type == "SELL" else row[8]
        try:
            leg = json.loads(leg_json or "{}")
            stock_code = str(leg.get("stock_code") or row[2]).strip().upper()
            signal_price = number(leg.get("reference_price"))
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if not stock_code or signal_price is None or signal_price <= 0:
            continue
        observed_at = market_datetime(row[3], stock_code)
        if observed_at is None:
            continue
        signal_time = observed_at.isoformat()
        signal_date = observed_at.date().isoformat()
        try:
            payload = json.loads(row[14] or "{}") if len(row) > 14 else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        strategy_sources = _portfolio_sources(payload)
        key = (signal_date, stock_code, intent_type, str(row[5]))
        if key in collapsed:
            collapsed[key]["alert_count"] += 1
            collapsed[key]["last_alert_time"] = signal_time
            continue
        collapsed[key] = {
            "event_id": row[0],
            "event_type": row[1],
            "stock_code": stock_code,
            "signal_time": signal_time,
            "last_alert_time": signal_time,
            "signal_date": signal_date,
            "signal_price": signal_price,
            "reason_code": row[4],
            "strategy_version": row[5],
            "action": intent_type,
            "direction": "SELL" if intent_type == "SELL" else "BUY",
            "risk_result": row[7],
            "entry_stage": "CONFIRMED",
            "max_stage": "CONFIRMED",
            "current_status": "CONFIRMED",
            "current_reason_code": row[4],
            "current_state_time": signal_time,
            "alert_eligible": True,
            "alert_permission": str(signal_permission(
                "CONFIRMED", alert_eligible=True, delivered=True
            )),
            "strategy_sources": strategy_sources,
            "ever_strategy_sources": strategy_sources,
            "current_strategy_sources": strategy_sources,
            "stage_points": {
                "CONFIRMED": {
                    "time": signal_time,
                    "price": signal_price,
                    "reason_code": row[4],
                }
            },
            "delivered_at": row[10],
            "intraday_mfe_pct": number(row[11]),
            "intraday_mae_pct": number(row[12]),
            "outcome_close_return_pct": number(row[13]),
            "alert_count": 1,
        }
    return list(collapsed.values())


def collapse_candidates(rows: list[tuple]) -> list[dict]:
    collapsed: dict[tuple[str, str, str], dict] = {}
    for row in _chronological(rows):
        try:
            payload = json.loads(row[7] or "{}")
            feature = payload.get("feature_snapshot") or {}
            quote = feature.get("quote") or {}
            signal_price = number(quote.get("last_price"))
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
            continue
        stock_code = str(row[2]).strip().upper()
        stage = str(row[6] or "SETUP")
        if not stock_code or signal_price is None or signal_price <= 0 or stage not in STAGE_RANK:
            continue
        observed_at = market_datetime(row[3], stock_code)
        if observed_at is None:
            continue
        signal_time = observed_at.isoformat()
        signal_date = observed_at.date().isoformat()
        strategy_version = str(row[5])
        key = (signal_date, stock_code, strategy_version)
        stage_point = {
            "time": signal_time,
            "price": signal_price,
            "reason_code": row[4],
        }
        alert_eligible = payload.get("alert_eligible") is True
        strategy_sources = _portfolio_sources(payload)
        if key in collapsed:
            item = collapsed[key]
            item["alert_count"] += 1
            item["last_alert_time"] = signal_time
            item["stage_points"].setdefault(stage, stage_point)
            if STAGE_RANK[stage] > STAGE_RANK[item["max_stage"]]:
                item["max_stage"] = stage
            item.update({
                "current_status": stage,
                "current_reason_code": row[4],
                "current_state_time": signal_time,
                "alert_eligible": alert_eligible,
                "alert_permission": str(signal_permission(
                    stage, alert_eligible=alert_eligible
                )),
                "ever_strategy_sources": sorted(
                    set(item["ever_strategy_sources"]) | set(strategy_sources)
                ),
                "current_strategy_sources": strategy_sources,
            })
            continue
        collapsed[key] = {
            "event_id": row[0],
            "event_type": row[1],
            "stock_code": stock_code,
            "signal_time": signal_time,
            "last_alert_time": signal_time,
            "signal_date": signal_date,
            "signal_price": signal_price,
            "reason_code": row[4],
            "strategy_version": strategy_version,
            "action": "CANDIDATE",
            "direction": "BUY",
            "risk_result": "NOT_REQUIRED",
            "entry_stage": stage,
            "max_stage": stage,
            "current_status": stage,
            "current_reason_code": row[4],
            "current_state_time": signal_time,
            "alert_eligible": alert_eligible,
            "alert_permission": str(signal_permission(
                stage, alert_eligible=alert_eligible
            )),
            "strategy_sources": strategy_sources,
            "ever_strategy_sources": strategy_sources,
            "current_strategy_sources": strategy_sources,
            "stage_points": {stage: stage_point},
            "delivered_at": None,
            "intraday_mfe_pct": number(row[8]),
            "intraday_mae_pct": number(row[9]),
            "outcome_close_return_pct": number(row[10]),
            "alert_count": 1,
        }
    return list(collapsed.values())


def apply_candidate_lifecycle(items: list[dict], rows: list[tuple]) -> list[dict]:
    """Attach the latest state without changing each scope's performance basis."""
    latest: dict[tuple[str, str, str], dict] = {}
    all_sources: dict[tuple[str, str, str], set[str]] = {}
    for row in _chronological(rows):
        stock_code = str(row[2]).strip().upper()
        observed_at = market_datetime(row[3], stock_code)
        if observed_at is None:
            continue
        try:
            payload = json.loads(row[7] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        sources = _portfolio_sources(payload)
        status = str(row[6] or "IDLE").upper()
        alert_eligible = payload.get("alert_eligible") is True
        key = (observed_at.date().isoformat(), stock_code, str(row[5]))
        all_sources.setdefault(key, set()).update(sources)
        latest[key] = {
            "current_status": status,
            "current_reason_code": row[4],
            "current_state_time": observed_at.isoformat(),
            "alert_eligible": alert_eligible,
            "alert_permission": str(signal_permission(
                status, alert_eligible=alert_eligible
            )),
            "current_strategy_sources": sources,
        }
    for item in items:
        key = (
            item["signal_date"], item["stock_code"], item["strategy_version"]
        )
        if key in latest:
            item.update(latest[key])
        item["ever_strategy_sources"] = sorted(
            set(item.get("ever_strategy_sources") or ()) | all_sources.get(key, set())
        )
    return items


def lifecycle_summary(items: list[dict]) -> dict:
    return {
        "current_status": dict(sorted(Counter(
            str(item.get("current_status") or "UNKNOWN") for item in items
        ).items())),
        "max_stage": dict(sorted(Counter(
            str(item.get("max_stage") or "UNKNOWN") for item in items
        ).items())),
        "alert_permission": dict(sorted(Counter(
            str(item.get("alert_permission") or "NONE") for item in items
        ).items())),
    }


def _is_regular_session(stock_code: str, exchange_time: str) -> bool:
    if not stock_code.upper().startswith("HK."):
        return True
    return is_hk_continuous_session(exchange_time)


def _chronological(rows: list[tuple]) -> list[tuple]:
    def timestamp(row: tuple) -> float:
        parsed = market_datetime(row[3], str(row[2]))
        return parsed.timestamp() if parsed is not None else float("inf")

    return sorted(rows, key=timestamp)
