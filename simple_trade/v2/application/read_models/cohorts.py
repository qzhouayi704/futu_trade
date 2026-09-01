"""Pure cohort aggregation for the ten-trading-day shadow acceptance report."""

from collections import defaultdict
from typing import Any

from .distribution import percentile, summary


FIRST_INFLOW_REASON = "FIRST_STRONG_INFLOW_WATCH"


def build_shadow_acceptance(rows: list[dict[str, Any]], target_days: int = 10) -> dict:
    available_days = sorted({_trade_day(row) for row in rows if _trade_day(row)}, reverse=True)
    selected_days = available_days[:target_days]
    selected = [row for row in rows if _trade_day(row) in selected_days]
    entries = [row for row in selected if row.get("event_type") == "BUY_CONFIRMED"]
    controls = [
        row for row in selected
        if row.get("event_type") == "CANDIDATE_UPDATED"
        and row.get("reason_code") == FIRST_INFLOW_REASON
    ]
    rotations = [row for row in selected if row.get("event_type") == "ROTATION_PROPOSED"]

    warnings = []
    if len(selected_days) < target_days:
        warnings.append(f"当前仅覆盖 {len(selected_days)}/{target_days} 个交易日")
    if not controls:
        warnings.append("尚无首次强流入对照样本")
    if not rotations:
        warnings.append("尚无换票对照样本")

    return {
        "target_days": target_days,
        "observed_days": len(selected_days),
        "ready": len(selected_days) >= target_days,
        "date_range": {
            "start": min(selected_days) if selected_days else None,
            "end": max(selected_days) if selected_days else None,
        },
        "sample_count": len(selected),
        "entry_summary": _stats(entries),
        "first_inflow_control": _stats(controls),
        "rotation_summary": _rotation_stats(rotations),
        "cohorts": {
            "market_regime": _group(entries, _market_regime),
            "confirmation_window": _group(entries, _confirmation_window),
            "inflow_frequency": _group(entries + controls, _inflow_frequency),
            "outflow_context": _group(entries + controls, _outflow_context),
            "signal_stage": _group(entries + controls, _signal_stage),
        },
        "daily": _daily(selected),
        "warnings": warnings,
    }


def _group(rows: list[dict[str, Any]], classifier) -> list[dict]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[classifier(row)].append(row)
    return [
        {"key": key, **_stats(items)}
        for key, items in sorted(groups.items(), key=lambda item: item[0])
    ]


def _stats(rows: list[dict[str, Any]]) -> dict:
    mfe = _numbers(rows, "mfe_pct")
    mae = _numbers(rows, "mae_pct")
    closes = _numbers(rows, "close_return_pct")
    times = _numbers(rows, "time_to_1_5_seconds")
    count = len(rows)
    return {
        "sample_count": count,
        "completed_count": sum(row.get("next_day_return_pct") is not None for row in rows),
        "reached_1_5_ratio": _ratio(rows, "reached_1_5"),
        "reached_3_ratio": _ratio(rows, "reached_3"),
        "reached_5_ratio": _ratio(rows, "reached_5"),
        "mfe": summary(mfe),
        "mae": summary(mae),
        "close_return": summary(closes),
        "median_time_to_1_5_seconds": percentile(times, 50),
    }


def _rotation_stats(rows: list[dict[str, Any]]) -> dict:
    advantages = [
        float(row["rotation_return_pct"]) - float(row["hold_control_return_pct"])
        for row in rows
        if row.get("rotation_return_pct") is not None
        and row.get("hold_control_return_pct") is not None
    ]
    return {
        **_stats(rows),
        "comparable_count": len(advantages),
        "advantage": summary(advantages),
        "rotation_win_ratio": (
            round(sum(value > 0 for value in advantages) / len(advantages), 4)
            if advantages else 0.0
        ),
    }


def _daily(rows: list[dict[str, Any]]) -> list[dict]:
    days: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        days[_trade_day(row)].append(row)
    result = []
    for day, items in sorted(days.items(), reverse=True):
        entries = [item for item in items if item.get("event_type") == "BUY_CONFIRMED"]
        controls = [item for item in items if item.get("reason_code") == FIRST_INFLOW_REASON]
        rotations = [item for item in items if item.get("event_type") == "ROTATION_PROPOSED"]
        result.append({
            "trade_date": day,
            "entry": _stats(entries),
            "first_inflow": _stats(controls),
            "rotation": _rotation_stats(rotations),
        })
    return result


def _market_regime(row: dict[str, Any]) -> str:
    context = _feature(row).get("market_context")
    return str(context.get("market_regime", "UNKNOWN")) if isinstance(context, dict) else "UNKNOWN"


def _confirmation_window(row: dict[str, Any]) -> str:
    reason = str(row.get("reason_code", ""))
    if "15M" in reason:
        return "FAST_15M"
    if "60M" in reason:
        return "SLOW_60M"
    return "UNKNOWN"


def _inflow_frequency(row: dict[str, Any]) -> str:
    window = _selected_window(row)
    count = int(window.get("independent_buy_events", 0)) if window else 0
    if count <= 1:
        return "SINGLE"
    if count == 2:
        return "MULTI_2"
    return "MULTI_3_PLUS"


def _outflow_context(row: dict[str, Any]) -> str:
    window = _selected_window(row)
    if not window or int(window.get("independent_sell_events", 0)) <= 0:
        return "NO_LARGE_OUTFLOW"
    buy = float(window.get("buy_amount") or 0)
    sell = float(window.get("sell_amount") or 0)
    net = float(window.get("main_net") or 0)
    if net < 0 or (buy > 0 and sell >= buy * 0.8):
        return "MATERIAL_OFFSET"
    return "MINOR_OUTFLOW"


def _signal_stage(row: dict[str, Any]) -> str:
    return "FIRST_INFLOW_CONTROL" if row.get("reason_code") == FIRST_INFLOW_REASON else "CONFIRMED_ENTRY"


def _selected_window(row: dict[str, Any]) -> dict:
    reason = str(row.get("reason_code", ""))
    seconds = 3600 if "60M" in reason else 900
    windows = _feature(row).get("tick_windows")
    if not isinstance(windows, list):
        return {}
    return next(
        (item for item in windows if isinstance(item, dict) and item.get("window_seconds") == seconds),
        {},
    )


def _feature(row: dict[str, Any]) -> dict:
    payload = row.get("payload")
    feature = payload.get("feature_snapshot") if isinstance(payload, dict) else None
    return feature if isinstance(feature, dict) else {}


def _trade_day(row: dict[str, Any]) -> str:
    value = str(row.get("signal_time") or "")
    return value[:10] if len(value) >= 10 else ""


def _numbers(rows: list[dict[str, Any]], key: str) -> list[float]:
    return [float(row[key]) for row in rows if row.get(key) is not None]


def _ratio(rows: list[dict[str, Any]], key: str) -> float:
    return round(sum(bool(row.get(key)) for row in rows) / len(rows), 4) if rows else 0.0
