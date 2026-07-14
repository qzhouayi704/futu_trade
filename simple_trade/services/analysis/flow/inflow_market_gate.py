#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""资金流入提醒的热门度与市场宽度门控。"""

from __future__ import annotations

import math
import os
import statistics
from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Optional


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _float(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _change_pct(quote: dict) -> Optional[float]:
    for key in ("change_percent", "change_pct"):
        if quote.get(key) is not None:
            return _float(quote.get(key))
    last = _float(quote.get("last_price"))
    prev = _float(quote.get("prev_close"))
    if last is None or prev is None or prev <= 0:
        return None
    return (last / prev - 1.0) * 100.0


@dataclass(frozen=True)
class InflowMarketGateConfig:
    enabled: bool = True
    hot_turnover_percentile: float = 0.80
    extreme_hot_turnover_percentile: float = 0.90
    normal_market_breadth: float = 0.55
    weak_market_breadth: float = 0.40
    normal_plate_breadth: float = 0.55
    weak_plate_breadth: float = 0.50
    extreme_plate_breadth: float = 0.70
    normal_relative_strength_pct: float = 0.0
    weak_relative_strength_pct: float = 2.50
    extreme_relative_strength_pct: float = 2.50
    min_universe_size: int = 20
    min_plate_size: int = 5

    @classmethod
    def from_env(cls) -> "InflowMarketGateConfig":
        from ....utils import env_flag

        return cls(
            enabled=env_flag("CAPITAL_INFLOW_HOT_GATE_ENABLED", True),
            hot_turnover_percentile=_env_float(
                "CAPITAL_INFLOW_HOT_TURNOVER_PCT", cls.hot_turnover_percentile
            ),
            extreme_hot_turnover_percentile=_env_float(
                "CAPITAL_INFLOW_EXTREME_HOT_TURNOVER_PCT",
                cls.extreme_hot_turnover_percentile,
            ),
            normal_market_breadth=_env_float(
                "CAPITAL_INFLOW_NORMAL_BREADTH",
                _env_float("CAPITAL_INFLOW_MIN_BREADTH", cls.normal_market_breadth),
            ),
            weak_market_breadth=_env_float(
                "CAPITAL_INFLOW_WEAK_BREADTH", cls.weak_market_breadth
            ),
            normal_plate_breadth=_env_float(
                "CAPITAL_INFLOW_NORMAL_PLATE_BREADTH", cls.normal_plate_breadth
            ),
            weak_plate_breadth=_env_float(
                "CAPITAL_INFLOW_WEAK_PLATE_BREADTH", cls.weak_plate_breadth
            ),
            extreme_plate_breadth=_env_float(
                "CAPITAL_INFLOW_EXTREME_PLATE_BREADTH", cls.extreme_plate_breadth
            ),
            normal_relative_strength_pct=_env_float(
                "CAPITAL_INFLOW_NORMAL_RELATIVE_STRENGTH_PCT",
                cls.normal_relative_strength_pct,
            ),
            weak_relative_strength_pct=_env_float(
                "CAPITAL_INFLOW_WEAK_RELATIVE_STRENGTH_PCT",
                cls.weak_relative_strength_pct,
            ),
            extreme_relative_strength_pct=_env_float(
                "CAPITAL_INFLOW_EXTREME_RELATIVE_STRENGTH_PCT",
                cls.extreme_relative_strength_pct,
            ),
            min_universe_size=_env_int(
                "CAPITAL_INFLOW_MIN_UNIVERSE", cls.min_universe_size
            ),
            min_plate_size=_env_int(
                "CAPITAL_INFLOW_MIN_PLATE_SIZE", cls.min_plate_size
            ),
        )


@dataclass(frozen=True)
class InflowMarketContext:
    stock_code: str
    market: str
    eligible: bool
    is_hot: bool
    change_pct: float
    turnover_rank_percentile: float
    market_breadth: float
    market_universe_size: int
    risk_mode: str
    plate_name: str
    plate_breadth: float
    plate_universe_size: int
    plate_median_change_pct: float
    relative_strength_pct: float
    required_confirmations: int
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


class InflowMarketGate:
    """按市场状态、板块强度和成交额热门度筛选资金流候选。"""

    def __init__(self, config: Optional[InflowMarketGateConfig] = None):
        self.cfg = config or InflowMarketGateConfig.from_env()

    def evaluate(self, quotes: Iterable[dict]) -> Dict[str, dict]:
        grouped: Dict[str, List[dict]] = {}
        for quote in quotes or []:
            code = str(quote.get("code") or "")
            change = _change_pct(quote)
            if not code or change is None:
                continue
            market = "US" if code.startswith("US.") else "HK"
            grouped.setdefault(market, []).append({
                "code": code,
                "change": change,
                "turnover": max(_float(quote.get("turnover")) or 0.0, 0.0),
                "plate_name": str(quote.get("plate_name") or "").strip(),
            })

        result: Dict[str, dict] = {}
        for market, rows in grouped.items():
            universe_size = len(rows)
            breadth = (sum(1 for row in rows if row["change"] > 0) / universe_size
                       if universe_size else 0.0)
            ranked = sorted(rows, key=lambda row: row["turnover"], reverse=True)
            turnover_count = sum(1 for row in ranked if row["turnover"] > 0)
            hot_count = max(
                1,
                math.ceil(turnover_count * (1.0 - self.cfg.hot_turnover_percentile)),
            ) if turnover_count else 0
            rank_by_code = {
                row["code"]: 1.0 - (index / turnover_count)
                for index, row in enumerate(ranked[:turnover_count])
            }
            hot_codes = {row["code"] for row in ranked[:hot_count]}
            extreme_hot_count = max(
                1,
                math.ceil(
                    turnover_count * (1.0 - self.cfg.extreme_hot_turnover_percentile)
                ),
            ) if turnover_count else 0
            extreme_hot_codes = {row["code"] for row in ranked[:extreme_hot_count]}

            plates: Dict[str, List[dict]] = {}
            for row in rows:
                if row["plate_name"]:
                    plates.setdefault(row["plate_name"], []).append(row)

            if breadth >= self.cfg.normal_market_breadth:
                risk_mode = "NORMAL"
                required_confirmations = 2
            elif breadth >= self.cfg.weak_market_breadth:
                risk_mode = "WEAK"
                required_confirmations = 2
            else:
                risk_mode = "EXTREME"
                required_confirmations = 3

            for row in rows:
                code = row["code"]
                rank_pct = rank_by_code.get(code, 0.0)
                plate_rows = plates.get(row["plate_name"], [])
                plate_size = len(plate_rows)
                plate_breadth = (
                    sum(1 for member in plate_rows if member["change"] > 0) / plate_size
                    if plate_size else 0.0
                )
                plate_median = (
                    float(statistics.median(member["change"] for member in plate_rows))
                    if plate_rows else 0.0
                )
                relative_strength = row["change"] - plate_median
                is_hot = code in (
                    extreme_hot_codes if risk_mode == "EXTREME" else hot_codes
                )
                enough_quotes = universe_size >= self.cfg.min_universe_size
                enough_plate = plate_size >= self.cfg.min_plate_size

                if risk_mode == "NORMAL":
                    market_condition_ok = (
                        enough_plate
                        and plate_breadth >= self.cfg.normal_plate_breadth
                        and relative_strength >= self.cfg.normal_relative_strength_pct
                    )
                elif risk_mode == "WEAK":
                    market_condition_ok = (
                        enough_plate
                        and plate_breadth >= self.cfg.weak_plate_breadth
                        and relative_strength >= self.cfg.weak_relative_strength_pct
                    )
                else:
                    market_condition_ok = (
                        enough_plate
                        and plate_breadth >= self.cfg.extreme_plate_breadth
                        and relative_strength >= self.cfg.extreme_relative_strength_pct
                    )
                eligible = (
                    (not self.cfg.enabled)
                    or (enough_quotes and is_hot and market_condition_ok)
                )

                if not self.cfg.enabled:
                    reason = "市场/板块门控已关闭"
                elif not enough_quotes:
                    reason = f"报价样本不足({universe_size}<{self.cfg.min_universe_size})"
                elif not is_hot:
                    threshold = (
                        self.cfg.extreme_hot_turnover_percentile
                        if risk_mode == "EXTREME"
                        else self.cfg.hot_turnover_percentile
                    )
                    top_pct = max(0.0, (1.0 - threshold) * 100)
                    reason = f"成交额未进入市场前{top_pct:.0f}%"
                elif not enough_plate:
                    reason = f"{risk_mode}市场板块样本不足({plate_size}<{self.cfg.min_plate_size})"
                elif risk_mode == "NORMAL" and plate_breadth < self.cfg.normal_plate_breadth:
                    reason = (
                        f"正常市场板块宽度不足({plate_breadth:.0%}"
                        f"<{self.cfg.normal_plate_breadth:.0%})"
                    )
                elif risk_mode == "WEAK" and plate_breadth < self.cfg.weak_plate_breadth:
                    reason = (
                        f"弱市板块宽度不足({plate_breadth:.0%}"
                        f"<{self.cfg.weak_plate_breadth:.0%})"
                    )
                elif risk_mode == "EXTREME" and plate_breadth < self.cfg.extreme_plate_breadth:
                    reason = (
                        f"极弱市板块宽度不足({plate_breadth:.0%}"
                        f"<{self.cfg.extreme_plate_breadth:.0%})"
                    )
                elif (risk_mode == "NORMAL"
                      and relative_strength < self.cfg.normal_relative_strength_pct):
                    reason = (
                        f"正常市场相对板块强度不足({relative_strength:+.2f}"
                        f"<{self.cfg.normal_relative_strength_pct:+.2f}个百分点)"
                    )
                elif risk_mode == "WEAK" and relative_strength < self.cfg.weak_relative_strength_pct:
                    reason = (
                        f"弱市相对板块强度不足({relative_strength:+.2f}"
                        f"<{self.cfg.weak_relative_strength_pct:+.2f}个百分点)"
                    )
                elif risk_mode == "EXTREME" and relative_strength < self.cfg.extreme_relative_strength_pct:
                    reason = (
                        f"极弱市相对板块强度不足({relative_strength:+.2f}"
                        f"<{self.cfg.extreme_relative_strength_pct:+.2f}个百分点)"
                    )
                else:
                    reason = {
                        "NORMAL": "正常市场热门股通过",
                        "WEAK": "弱市强板块逆势候选通过",
                        "EXTREME": "极弱市强板块逆势候选通过",
                    }[risk_mode]

                result[code] = InflowMarketContext(
                    stock_code=code,
                    market=market,
                    eligible=eligible,
                    is_hot=is_hot,
                    change_pct=round(row["change"], 4),
                    turnover_rank_percentile=round(rank_pct, 4),
                    market_breadth=round(breadth, 4),
                    market_universe_size=universe_size,
                    risk_mode=risk_mode,
                    plate_name=row["plate_name"],
                    plate_breadth=round(plate_breadth, 4),
                    plate_universe_size=plate_size,
                    plate_median_change_pct=round(plate_median, 4),
                    relative_strength_pct=round(relative_strength, 4),
                    required_confirmations=required_confirmations,
                    reason=reason,
                ).to_dict()
        return result
