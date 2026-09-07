"""Pure post-signal performance calculations for the review read model."""

HORIZONS = (1, 3, 5, 10)


def evaluate_alert(
    alert: dict,
    names: dict,
    klines: dict,
    intraday: dict,
    intraday_closes: dict,
) -> dict:
    basis = alert["signal_price"]
    direction = alert["direction"]
    stock_days = klines.get(alert["stock_code"], {})
    same_day = stock_days.get(alert["signal_date"])
    later_days = [day for day in sorted(stock_days) if day > alert["signal_date"]]
    signal_minute = _signal_minute(alert["signal_time"])
    minute_rows = [
        row for row in intraday.get(alert["stock_code"], [])
        if row[0] >= signal_minute
    ]

    outcome_close = alert["outcome_close_return_pct"]
    same_close = None
    same_day_source = None
    price_scale = 1.0
    if outcome_close is not None:
        same_close = _directional_value(outcome_close, direction)
        same_day_source = "OUTCOME"
        if same_day and same_day[0] > 0:
            actual_close = basis * (1.0 + outcome_close / 100.0)
            price_scale = actual_close / same_day[0]
    elif same_day:
        same_close = _directional_return(same_day[0], basis, direction)
        same_day_source = "DAILY_KLINE"
    elif minute_rows:
        close_price = intraday_closes.get(alert["stock_code"], minute_rows[-1][1])
        same_close = _directional_return(close_price, basis, direction)
        same_day_source = "TICKER_MINUTE"

    same_best = None
    same_worst = None
    if minute_rows:
        favorable_price = (
            min(row[3] for row in minute_rows)
            if direction == "SELL"
            else max(row[2] for row in minute_rows)
        )
        adverse_price = (
            max(row[2] for row in minute_rows)
            if direction == "SELL"
            else min(row[3] for row in minute_rows)
        )
        same_best = _directional_return(favorable_price, basis, direction)
        same_worst = _directional_return(adverse_price, basis, direction)

    periods = {
        str(horizon): _period(
            horizon, later_days, stock_days, basis, direction, price_scale
        )
        for horizon in HORIZONS
    }
    return {
        **alert,
        "stock_name": names.get(alert["stock_code"], ""),
        "same_day": {
            "status": "READY" if same_close is not None else "OBSERVING",
            "trading_day": alert["signal_date"],
            "close_return_pct": same_close,
            "max_return_pct": same_best,
            "max_drawdown_pct": same_worst,
            "source": same_day_source,
            "intraday_covered": bool(minute_rows),
        },
        "periods": periods,
        "completed_horizon": max(
            (
                horizon
                for horizon in HORIZONS
                if periods[str(horizon)]["status"] == "READY"
            ),
            default=0,
        ),
    }


def performance_summary(items: list[dict]) -> dict:
    return {
        "alert_count": len(items),
        "same_day": _metric(
            [item["same_day"] for item in items if item["same_day"]["status"] == "READY"]
        ),
        "periods": {
            str(horizon): _metric([
                item["periods"][str(horizon)]
                for item in items
                if item["periods"][str(horizon)]["status"] == "READY"
            ])
            for horizon in HORIZONS
        },
    }


def number(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def max_number(current: float | None, candidate) -> float | None:
    value = number(candidate)
    if value is None:
        return current
    return value if current is None else max(current, value)


def min_number(current: float | None, candidate) -> float | None:
    value = number(candidate)
    if value is None:
        return current
    return value if current is None else min(current, value)


def _period(
    horizon: int,
    later_days: list[str],
    stock_days: dict[str, tuple],
    basis: float,
    direction: str,
    price_scale: float,
) -> dict:
    if len(later_days) < horizon:
        return {
            "status": "PENDING",
            "trading_day": None,
            "close_return_pct": None,
            "max_return_pct": None,
            "max_drawdown_pct": None,
        }
    window = [stock_days[day] for day in later_days[:horizon]]
    close_price = window[-1][0] * price_scale
    if direction == "SELL":
        favorable_price = min(row[2] for row in window) * price_scale
        adverse_price = max(row[1] for row in window) * price_scale
    else:
        favorable_price = max(row[1] for row in window) * price_scale
        adverse_price = min(row[2] for row in window) * price_scale
    return {
        "status": "READY",
        "trading_day": later_days[horizon - 1],
        "close_return_pct": _directional_return(close_price, basis, direction),
        "max_return_pct": _directional_return(favorable_price, basis, direction),
        "max_drawdown_pct": _directional_return(adverse_price, basis, direction),
    }


def _metric(rows: list[dict]) -> dict:
    closes = [row["close_return_pct"] for row in rows if row["close_return_pct"] is not None]
    best = [row["max_return_pct"] for row in rows if row["max_return_pct"] is not None]
    worst = [
        row["max_drawdown_pct"]
        for row in rows
        if row["max_drawdown_pct"] is not None
    ]
    reached = [value for value in best if value >= 1.5]
    return {
        "completed_count": len(closes),
        "win_count": sum(value > 0 for value in closes),
        "win_ratio": round(sum(value > 0 for value in closes) / len(closes), 4)
        if closes else None,
        "mean_return_pct": round(sum(closes) / len(closes), 4) if closes else None,
        "opportunity_count": len(best),
        "reached_1_5_count": len(reached),
        "reached_1_5_ratio": round(len(reached) / len(best), 4) if best else None,
        "mean_max_return_pct": round(sum(best) / len(best), 4) if best else None,
        "mean_max_drawdown_pct": round(sum(worst) / len(worst), 4) if worst else None,
    }


def _directional_return(price: float, basis: float, direction: str) -> float:
    raw = (float(price) / basis - 1.0) * 100.0
    return _directional_value(raw, direction)


def _directional_value(value: float | None, direction: str) -> float | None:
    if value is None:
        return None
    return round(-value if direction == "SELL" else value, 4)


def _signal_minute(value: str) -> str:
    text = str(value or "")
    time_part = text.split("T", 1)[-1] if "T" in text else text.split(" ", 1)[-1]
    return time_part[:5] if len(time_part) >= 5 else "00:00"
