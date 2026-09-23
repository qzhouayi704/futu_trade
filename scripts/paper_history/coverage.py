"""Post-signal archive availability diagnostics; never an entry selection filter."""

from collections import Counter, defaultdict
from datetime import timedelta

from .data import Minute, moment, regular


def coverage(decisions: list[dict], minutes: list[Minute]) -> dict:
    observed = defaultdict(set)
    for bar in minutes:
        if regular(bar.start):
            observed[(bar.stock_code, bar.start.date())].add(bar.start)
    cases = []
    for row in decisions:
        when = moment(row["received_time"])
        minute = when.replace(second=0, microsecond=0)
        if minute < when:
            minute += timedelta(minutes=1)
        end = when.replace(hour=16, minute=0, second=0, microsecond=0)
        expected = []
        while minute < end:
            if regular(minute):
                expected.append(minute)
            minute += timedelta(minutes=1)
        available = observed[(row["stock_code"], when.date())]
        later = [time for time in expected if time in available]
        run = longest = 0
        for time in expected:
            run = 0 if time in available else run + 1
            longest = max(longest, run)
        cases.append({
            "source_event_id": row["event_id"], "stock_code": row["stock_code"], "name": row["name"],
            "signal_at": when.isoformat(), "expected_regular_minutes": len(expected),
            "observed_regular_minutes": len(later),
            "coverage_fraction": len(later) / len(expected) if expected else None,
            "longest_missing_trading_minutes": longest,
            "first_later_minute": later[0].isoformat() if later else None,
            "last_later_minute": later[-1].isoformat() if later else None,
            "minutes_in_assumed_exit_window": sum(time.hour == 15 and time.minute >= 50 for time in later),
        })
    counts = Counter({"full_coverage": 0, "at_least_90pct": 0,
                      "missing_more_than_5_trading_minutes_in_a_row": 0, "no_exit_window_minutes": 0})
    for row in cases:
        counts["full_coverage"] += row["coverage_fraction"] == 1
        counts["at_least_90pct"] += (row["coverage_fraction"] or 0) >= .9
        counts["missing_more_than_5_trading_minutes_in_a_row"] += row["longest_missing_trading_minutes"] > 5
        counts["no_exit_window_minutes"] += row["minutes_in_assumed_exit_window"] == 0
    return {"samples": len(cases), "counts": dict(counts), "cases": cases,
            "meaning": "Missing recorded minutes cannot distinguish inactivity, suspension and collection gaps."}
