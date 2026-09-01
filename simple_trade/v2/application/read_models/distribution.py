"""Small dependency-free outcome distribution helpers."""

from math import floor


PERCENTILES = (10, 25, 50, 75, 90, 95)


def percentile(values: list[float], rank: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    point = (len(ordered) - 1) * rank / 100
    lower = floor(point)
    upper = min(lower + 1, len(ordered) - 1)
    weight = point - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 4)


def summary(values: list[float]) -> dict:
    return {
        "count": len(values),
        "percentiles": {f"p{rank}": percentile(values, rank) for rank in PERCENTILES},
        "max": round(max(values), 4) if values else None,
        "min": round(min(values), 4) if values else None,
        "mean": round(sum(values) / len(values), 4) if values else None,
    }


def histogram(values: list[float]) -> list[dict]:
    bands = (
        ("<-3%", None, -3.0),
        ("-3~0%", -3.0, 0.0),
        ("0~1.5%", 0.0, 1.5),
        ("1.5~3%", 1.5, 3.0),
        ("3~5%", 3.0, 5.0),
        (">=5%", 5.0, None),
    )
    result = []
    total = len(values)
    for label, lower, upper in bands:
        count = sum(
            1 for value in values
            if (lower is None or value >= lower) and (upper is None or value < upper)
        )
        result.append({
            "label": label,
            "count": count,
            "ratio": round(count / total, 4) if total else 0.0,
        })
    return result
