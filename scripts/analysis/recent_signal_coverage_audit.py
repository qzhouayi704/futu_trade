"""Read-only audit of liquid gainers against the production V2 signal funnel."""

from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import json
import re
import sqlite3
import statistics
import time


HK = timezone(timedelta(hours=8))
EVENT_TYPES = (
    "CANDIDATE_ENTERED", "CANDIDATE_UPDATED", "CANDIDATE_REJECTED",
    "CANDIDATE_INVALIDATED", "BUY_CONFIRMED", "BUY_INVALIDATED",
)


@dataclass
class Point:
    event_id: str
    time: str
    price: float
    reason: str
    eligible: bool
    risk: str | None
    risk_reasons: list[str]
    delivered: bool
    version: str


@dataclass
class Track:
    points: dict[str, Point] = field(default_factory=dict)
    confirmations: list[Point] = field(default_factory=list)
    reasons: Counter = field(default_factory=Counter)
    blocking_reasons: Counter = field(default_factory=Counter)
    quote: dict = field(default_factory=dict)
    quote_time: str = ""
    last_status: str = ""


def number(value) -> float:
    return float(value or 0.0)


def pct(price: float, base: float) -> float | None:
    return round((price / base - 1) * 100, 3) if min(price, base) > 0 else None


def regular(moment: datetime) -> bool:
    clock = moment.strftime("%H:%M:%S")
    return "09:30:00" <= clock <= "12:00:00" or "13:00:00" <= clock <= "16:00:00"


def record_first(track, stage, point):
    prior = track.points.get(stage)
    if prior is None or point.time < prior.time:
        track.points[stage] = point


def query(conn, sql, args=()):
    started = time.monotonic()
    conn.set_progress_handler(lambda: time.monotonic() - started > 30, 10000)
    yield from conn.execute(sql, args)


def load_tracks(conn, start, end):
    risks = {}
    for event_id, risk, reasons, delivered in query(conn,
        "SELECT e.event_id,i.risk_result,i.risk_reason_json,"
        "EXISTS(SELECT 1 FROM v2_notification_log n WHERE n.decision_event_id=e.event_id "
        "AND n.channel='WECHAT' AND n.status='DELIVERED') "
        "FROM v2_decision_events e LEFT JOIN v2_trade_intents i ON i.source_event_id=e.event_id "
        "WHERE e.event_type='BUY_CONFIRMED' AND e.exchange_time>=? AND e.exchange_time<?",
        (start, end)):
        risks[event_id] = (risk, json.loads(reasons or "[]"), bool(delivered))
    tracks = defaultdict(Track)
    event_counts = Counter()
    placeholders = ",".join("?" for _ in EVENT_TYPES)
    rows = query(conn,
        "SELECT event_id,event_type,stock_code,exchange_time,reason_code,new_state,"
        "strategy_version,payload_json FROM v2_decision_events "
        f"WHERE event_type IN ({placeholders}) AND exchange_time>=? AND exchange_time<? "
        "ORDER BY exchange_time,id", (*EVENT_TYPES, start, end))
    for event_id, kind, code, timestamp, reason, state, version, raw in rows:
        moment = datetime.fromisoformat(timestamp).astimezone(HK)
        if not regular(moment):
            continue
        day = moment.date().isoformat()
        if not start <= day < end:
            continue
        track = tracks[(day, code)]
        data = json.loads(raw)
        quote = (data.get("feature_snapshot") or {}).get("quote") or {}
        price = number(quote.get("last_price"))
        risk, risk_reasons, delivered = risks.get(event_id, (None, [], False))
        point = Point(event_id, moment.isoformat(), price, reason,
                      data.get("alert_eligible") is True, risk, risk_reasons,
                      delivered and risk == "APPROVED", version)
        track.reasons[reason] += 1
        if kind in {"CANDIDATE_REJECTED", "CANDIDATE_INVALIDATED", "BUY_INVALIDATED"}:
            track.blocking_reasons[reason] += 1
        track.last_status = state
        event_counts[(day, kind)] += 1
        if price > 0 and point.time >= track.quote_time:
            track.quote = quote
            track.quote_time = point.time
        if kind in {"CANDIDATE_ENTERED", "CANDIDATE_UPDATED", "BUY_CONFIRMED"}:
            if state in {"SETUP", "WATCHING", "CONFIRMED"} and price > 0:
                record_first(track, "candidate", point)
            if state in {"WATCHING", "CONFIRMED"} and price > 0:
                record_first(track, "watching", point)
        if kind == "BUY_CONFIRMED" and price > 0:
            track.confirmations.append(point)
            record_first(track, "confirmed", point)
            if point.eligible:
                record_first(track, "eligible", point)
            if point.delivered:
                record_first(track, "delivered", point)
    return tracks, event_counts


def load_bars(conn, start, end):
    bars = defaultdict(dict)
    for code, timestamp, opening, close, high, low, turnover in query(conn,
        "SELECT stock_code,time_key,open_price,close_price,high_price,low_price,turnover "
        "FROM kline_data WHERE time_key>=? AND time_key<? ORDER BY time_key,id",
        ((datetime.fromisoformat(start) - timedelta(days=10)).date().isoformat(), end)):
        bars[code][timestamp[:10]] = {
            "open": number(opening), "close": number(close), "high": number(high),
            "low": number(low), "turnover": number(turnover),
        }
    return bars


def equity(code, name):
    if not code.startswith("HK.") or not code[3:].isdigit() or int(code[3:]) >= 10000:
        return False
    return not re.search(r"ETF|\u4e24\u500d|\u4e09\u500d|\u53cd\u5411|\u76c8\u5bcc\u57fa\u91d1|\u5b89\u7855|\u5357\u65b9\u6052|\u6052\u751f\u6307\u6570|\u534e\u590f\u6052\u751f", name, re.I)


def outcome(point, bar, tape):
    result = {"close_ref_pct": pct(bar.get("close", 0), point.price)}
    if not tape:
        return result
    minutes = [item[0] for item in tape]
    # Only later minutes qualify: the signal minute high may precede the signal.
    index = bisect_right(minutes, point.time[11:16])
    if index == len(tape):
        return result
    later = tape[index:]
    result.update({
        "mfe_ref_pct": pct(max(row[2] for row in later), point.price),
        "mae_ref_pct": pct(min(row[3] for row in later), point.price),
        "next_observed_minute": later[0][0], "next_minute_mean_price": later[0][1],
        "last_tape_minute": tape[-1][0],
        "tape_reaches_close": tape[-1][0] >= "16:00",
        "observed_later_minutes": len(later),
    })
    signal_minute = datetime.strptime(point.time[11:16], "%H:%M")
    entry_minute = datetime.strptime(later[0][0], "%H:%M")
    gap = (entry_minute - signal_minute).total_seconds() / 60
    if gap <= 5:
        result["close_next_minute_mean_pct"] = pct(bar.get("close", 0), later[0][1])
    return result


def summarize_outcomes(items):
    summary = {"samples": len(items), "tape_reaches_close": sum(row.get("tape_reaches_close", False) for row in items)}
    for key in ("close_ref_pct", "close_next_minute_mean_pct", "mfe_ref_pct", "next1_close_pct", "next3_close_pct"):
        values = [row[key] for row in items if row.get(key) is not None]
        summary[key] = {
            "n": len(values), "mean": round(statistics.mean(values), 3) if values else None,
            "median": round(statistics.median(values), 3) if values else None,
            "positive": sum(value > 0 for value in values),
            "gte3": sum(value >= 3 for value in values),
            "gte5": sum(value >= 5 for value in values),
        }
    return summary


def audit(conn, start, end, minimum_turnover):
    names = dict(query(conn, "SELECT code,name FROM stocks WHERE market='HK'"))
    lookback = (datetime.fromisoformat(start) - timedelta(days=7)).date().isoformat()
    tracks, event_counts = load_tracks(conn, lookback, end)
    bars = load_bars(conn, start, end)
    dates = sorted({day for stock_days in bars.values() for day in stock_days})
    tapes = defaultdict(list)
    for code, day, minute, price, high, low in query(conn,
        "SELECT stock_code,trade_date,minute,price,high,low FROM ticker_minute "
        "WHERE trade_date>=? AND trade_date<? AND price>0 ORDER BY trade_date,stock_code,minute",
        (start, end)):
        tapes[(day, code)].append((minute, number(price), number(high), number(low)))
    daily = {}
    samples = []
    for day in dates:
        if not start <= day < end:
            continue
        previous = dates[dates.index(day)-1] if dates.index(day) else None
        population = []
        for code, stock_days in bars.items():
            bar = stock_days.get(day)
            if not bar or not equity(code, names.get(code, "")):
                continue
            track = tracks.get((day, code), Track())
            prev = number(track.quote.get("prev_close")) or stock_days.get(previous, {}).get("close", 0)
            change = pct(bar["close"], prev)
            if change is None or bar["close"] < 1 or bar["turnover"] < minimum_turnover:
                continue
            item = {"day": day, "code": code, "name": names.get(code, ""), **bar,
                    "prev_close": prev, "change_pct": change, "points": {},
                    "reasons": track.reasons.most_common(6), "last_status": track.last_status,
                    "blocking_reasons": track.blocking_reasons.most_common(),
                    "minute_rows": len(tapes.get((day, code), []))}
            for stage, point in track.points.items():
                item["points"][stage] = {**asdict(point),
                    "change_at_signal_pct": pct(point.price, prev),
                    **outcome(point, bar, tapes.get((day, code)))}
            recent_days = [d for d in dates if d < day][-2:]
            item["previous_signals"] = [
                {"day": d, "stage": stage, "time": point.time, "price": point.price,
                 "to_current_close_pct": pct(bar["close"], point.price)}
                for d in recent_days for stage, point in tracks.get((d, code), Track()).points.items()
                if stage in {"confirmed", "delivered"}
            ]
            population.append(item)
        population.sort(key=lambda item: item["change_pct"], reverse=True)
        gainers = [item for item in population if item["change_pct"] >= 5]
        coverage = {stage: sum(stage in item["points"] for item in gainers)
                    for stage in ("candidate", "watching", "confirmed", "eligible", "delivered")}
        coverage["delivered_today_or_previous2"] = sum(
            "delivered" in item["points"] or any(p["stage"] == "delivered" for p in item["previous_signals"])
            for item in gainers)
        day_tracks = {code: track for (d, code), track in tracks.items() if d == day}
        day_signals = {stage: sum(stage in track.points for track in day_tracks.values())
                       for stage in ("candidate", "watching", "confirmed", "eligible", "delivered")}
        daily[day] = {"daily_bar_stocks": sum(day in d for d in bars.values()),
            "liquid_equity_stocks": len(population), "gainers_ge5": len(gainers),
            "coverage": coverage, "signal_stocks": day_signals,
            "top10": population[:10], "gainers": gainers}
        for code, track in day_tracks.items():
            bar = bars.get(code, {}).get(day, {})
            for stage in ("confirmed", "delivered"):
                point = track.points.get(stage)
                if point:
                    samples.append({"day": day, "code": code, "name": names.get(code, ""),
                        "stage": stage, **asdict(point), **outcome(point, bar, tapes.get((day, code)))})
            blocked = next((point for point in track.confirmations if point.risk == "REJECTED"), None)
            if blocked:
                samples.append({"day": day, "code": code, "name": names.get(code, ""),
                    "stage": "risk_rejected", **asdict(blocked),
                    **outcome(blocked, bar, tapes.get((day, code)))})
    complete_days = sorted(d for d in daily if any(k[0] == d for k in tapes))
    groups = defaultdict(list)
    for sample in samples:
        if sample["day"] in complete_days:
            for horizon in (1, 3):
                target = dates.index(sample["day"]) + horizon
                if target < len(dates) and dates[target] in complete_days:
                    close = bars.get(sample["code"], {}).get(dates[target], {}).get("close", 0)
                    sample[f"next{horizon}_close_pct"] = pct(close, sample["price"])
            groups[sample["stage"]].append(sample)
            if equity(sample["code"], sample["name"]):
                groups[sample["stage"] + "_equities"].append(sample)
            if sample["stage"] == "confirmed" and not sample["eligible"]:
                groups["shadow_confirmed"].append(sample)
            if sample["stage"] == "risk_rejected":
                groups["risk_rejected:" + sample["reason"]].append(sample)
            if sample["stage"] == "delivered":
                groups[sample["reason"]].append(sample)
    missing = Counter()
    for day in complete_days:
        for item in daily[day]["gainers"]:
            if "delivered" not in item["points"]:
                missing.update(reason for reason, _ in item["blocking_reasons"])
    return {"as_of": datetime.now(HK).isoformat(), "start": start, "end_exclusive": end,
        "minimum_turnover_hkd": minimum_turnover, "minimum_price": 1,
        "complete_minute_days": complete_days, "daily": daily,
        "outcome_summary": {key: summarize_outcomes(values) for key, values in groups.items()},
        "missed_gainer_reason_stock_days": missing.most_common(), "samples": samples,
        "event_counts": [{"day": key[0], "type": key[1], "count": n} for key, n in event_counts.items()]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="/data/futu_trade_data/trade.db")
    parser.add_argument("--start", default="2026-09-14")
    parser.add_argument("--end", default="2026-09-22")
    parser.add_argument("--minimum-turnover", type=float, default=30_000_000)
    args = parser.parse_args()
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True, timeout=5)
    conn.execute("PRAGMA query_only=ON")
    conn.execute("BEGIN")
    try:
        print(json.dumps(audit(conn, args.start, args.end, args.minimum_turnover), ensure_ascii=False))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
