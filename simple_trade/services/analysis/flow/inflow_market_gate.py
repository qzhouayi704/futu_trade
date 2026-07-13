#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""资金流入提醒的热门度与市场宽度门控。"""

from __future__ import annotations

import math
import os
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
    hot_min_change_pct: float = 3.0
    min_market_breadth: float = 0.55
    min_universe_size: int = 20

    @classmethod
    def from_env(cls) -> "InflowMarketGateConfig":
        from ....utils import env_flag

        return cls(
            enabled=env_flag("CAPITAL_INFLOW_HOT_GATE_ENABLED", True),
            hot_turnover_percentile=_env_float(
                "CAPITAL_INFLOW_HOT_TURNOVER_PCT", cls.hot_turnover_percentile
            ),
            hot_min_change_pct=_env_float(
                "CAPITAL_INFLOW_HOT_MIN_CHANGE", cls.hot_min_change_pct
            ),
            min_market_breadth=_env_float(
                "CAPITAL_INFLOW_MIN_BREADTH", cls.min_market_breadth
            ),
            min_universe_size=_env_int(
                "CAPITAL_INFLOW_MIN_UNIVERSE", cls.min_universe_size
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
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


class InflowMarketGate:
    """用全报价横截面筛出热门且处于进攻市场的资金流入候选。"""

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

            for row in rows:
                code = row["code"]
                rank_pct = rank_by_code.get(code, 0.0)
                is_hot = code in hot_codes and row["change"] >= self.cfg.hot_min_change_pct
                enough_quotes = universe_size >= self.cfg.min_universe_size
                breadth_ok = breadth >= self.cfg.min_market_breadth
                eligible = (not self.cfg.enabled) or (enough_quotes and breadth_ok and is_hot)

                if not self.cfg.enabled:
                    reason = "热门度/市场宽度门控已关闭"
                elif not enough_quotes:
                    reason = f"报价样本不足({universe_size}<{self.cfg.min_universe_size})"
                elif not breadth_ok:
                    reason = (f"市场宽度不足({breadth:.0%}"
                              f"<{self.cfg.min_market_breadth:.0%})")
                elif row["change"] < self.cfg.hot_min_change_pct:
                    reason = (f"日内涨幅不足({row['change']:+.2f}%"
                              f"<{self.cfg.hot_min_change_pct:.2f}%)")
                elif code not in hot_codes:
                    top_pct = max(0.0, (1.0 - self.cfg.hot_turnover_percentile) * 100)
                    reason = f"成交额未进入市场前{top_pct:.0f}%"
                else:
                    reason = "热门股且市场宽度通过"

                result[code] = InflowMarketContext(
                    stock_code=code,
                    market=market,
                    eligible=eligible,
                    is_hot=is_hot,
                    change_pct=round(row["change"], 4),
                    turnover_rank_percentile=round(rank_pct, 4),
                    market_breadth=round(breadth, 4),
                    market_universe_size=universe_size,
                    reason=reason,
                ).to_dict()
        return result
