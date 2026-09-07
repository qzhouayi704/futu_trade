"""Normalize and collapse alert records before performance evaluation."""

from collections import Counter
import json

from .alert_performance_metrics import max_number, min_number, number


STAGE_RANK = {"SETUP": 1, "WATCHING": 2, "CONFIRMED": 3}


def eligible_delivered(rows: list[tuple]) -> tuple[list[tuple], dict]:
    eligible = []
    excluded = Counter()
    excluded_rows = 0
    for row in rows:
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
    for row in rows:
        intent_type = str(row[6])
        leg_json = row[9] if intent_type == "SELL" else row[8]
        try:
            leg = json.loads(leg_json or "{}")
            stock_code = str(leg.get("stock_code") or row[2]).strip().upper()
            signal_price = float(leg.get("reference_price") or 0)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not stock_code or signal_price <= 0:
            continue
        signal_date = str(row[3])[:10]
        key = (signal_date, stock_code, intent_type, str(row[5]))
        if key in collapsed:
            collapsed[key]["alert_count"] += 1
            collapsed[key]["last_alert_time"] = row[3]
            continue
        collapsed[key] = {
            "event_id": row[0],
            "event_type": row[1],
            "stock_code": stock_code,
            "signal_time": row[3],
            "last_alert_time": row[3],
            "signal_date": signal_date,
            "signal_price": signal_price,
            "reason_code": row[4],
            "strategy_version": row[5],
            "action": intent_type,
            "direction": "SELL" if intent_type == "SELL" else "BUY",
            "risk_result": row[7],
            "entry_stage": "CONFIRMED",
            "max_stage": "CONFIRMED",
            "stage_points": {
                "CONFIRMED": {
                    "time": row[3],
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
    for row in rows:
        try:
            payload = json.loads(row[7] or "{}")
            feature = payload.get("feature_snapshot") or {}
            quote = feature.get("quote") or {}
            signal_price = float(quote.get("last_price") or 0)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        stock_code = str(row[2]).strip().upper()
        stage = str(row[6] or "SETUP")
        if not stock_code or signal_price <= 0 or stage not in STAGE_RANK:
            continue
        signal_date = str(row[3])[:10]
        strategy_version = str(row[5])
        key = (signal_date, stock_code, strategy_version)
        stage_point = {
            "time": row[3],
            "price": signal_price,
            "reason_code": row[4],
        }
        if key in collapsed:
            item = collapsed[key]
            item["alert_count"] += 1
            item["last_alert_time"] = row[3]
            item["stage_points"].setdefault(stage, stage_point)
            if STAGE_RANK[stage] > STAGE_RANK[item["max_stage"]]:
                item["max_stage"] = stage
            item["intraday_mfe_pct"] = max_number(item["intraday_mfe_pct"], row[8])
            item["intraday_mae_pct"] = min_number(item["intraday_mae_pct"], row[9])
            continue
        collapsed[key] = {
            "event_id": row[0],
            "event_type": row[1],
            "stock_code": stock_code,
            "signal_time": row[3],
            "last_alert_time": row[3],
            "signal_date": signal_date,
            "signal_price": signal_price,
            "reason_code": row[4],
            "strategy_version": strategy_version,
            "action": "CANDIDATE",
            "direction": "BUY",
            "risk_result": "NOT_REQUIRED",
            "entry_stage": stage,
            "max_stage": stage,
            "stage_points": {stage: stage_point},
            "delivered_at": None,
            "intraday_mfe_pct": number(row[8]),
            "intraday_mae_pct": number(row[9]),
            "outcome_close_return_pct": number(row[10]),
            "alert_count": 1,
        }
    return list(collapsed.values())


def _is_regular_session(stock_code: str, exchange_time: str) -> bool:
    if not stock_code.upper().startswith("HK."):
        return True
    text = str(exchange_time or "")
    time_part = text.split("T", 1)[-1] if "T" in text else text.split(" ", 1)[-1]
    minute = time_part[:5]
    return "09:30" <= minute <= "16:00"
