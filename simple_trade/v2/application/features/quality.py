"""Shared quality and numeric helpers for pure feature calculators."""

from ...domain.enums import DataQuality


_QUALITY_RANK = {
    DataQuality.GOOD: 0,
    DataQuality.DEGRADED: 1,
    DataQuality.INVALID: 2,
}


def worst_quality(*values: DataQuality) -> DataQuality:
    if not values:
        return DataQuality.INVALID
    return max(values, key=_QUALITY_RANK.__getitem__)


def clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))
