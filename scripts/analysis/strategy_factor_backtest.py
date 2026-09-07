#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Causal factor backtest for the V2 hot-stock strategy portfolio."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
import json
import math
from pathlib import Path
import sqlite3
import sys
from typing import Iterable, Sequence

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import big_order_flow_eval as flow  # noqa: E402
import low_position_accumulation_grid as grid  # noqa: E402
from simple_trade.v2.application.strategy.portfolio import (  # noqa: E402
    CandidateSignalRules,
)


ROUND_TRIP_COST = 0.0025
MIN_TRAIN_SAMPLES = 15
MIN_TRAIN_DAYS = 8
MIN_HALF_SAMPLES = 5
MIN_HALF_DAYS = 3
MIN_MATCHED_CONTROLS = 5
MAX_MATCHED_CONTROLS = 8
ACTIVITY_MATCH_WIDTH = 0.20
STRATEGY_LABELS = {
    "capital_absorption": "低位资金吸收",
    "momentum_continuation": "动量延续",
    "early_runner": "前日强势早盘延续",
    "pullback_reacceleration": "回踩再加速",
}


@dataclass(frozen=True)
class FilterSpec:
    name: str
    factor: str
    operation: str
    value: float


@dataclass(frozen=True)
class StrategyConfig:
    strategy: str
    flow_spec: grid.FlowSpec
    filters: tuple[FilterSpec, ...]

    @property
    def key(self) -> str:
        suffix = "-".join(
            f"{item.name}{item.operation}{item.value:g}" for item in self.filters
        )
        return f"{self.strategy}:{self.flow_spec.key}:{suffix}"


@dataclass(frozen=True)
class StrategyLayer:
    layer_id: str
    label: str
    strategy_source: str
    replay_coverage: str
    config: StrategyConfig
    caveats: tuple[str, ...] = ()


@dataclass(frozen=True)
class ControlCandidate:
    code: str
    day: str
    index: int
    position_band: str
    activity_percentile: float | None
    eod: float
    mfe_eod: float
    mae60: float


FACTOR_BINS = {
    "pos20": (
        ("<=20%", None, 0.20),
        ("20~35%", 0.20, 0.35),
        ("35~50%", 0.35, 0.50),
        ("50~80%", 0.50, 0.80),
        (">80%", 0.80, None),
    ),
    "extension_atr": (
        ("<-1ATR", None, -1.0),
        ("-1~0ATR", -1.0, 0.0),
        ("0~1ATR", 0.0, 1.0),
        ("1~2ATR", 1.0, 2.0),
        (">=2ATR", 2.0, None),
    ),
    "prev_ret": (
        ("昨日<-3%", None, -0.03),
        ("昨日-3~0%", -0.03, 0.0),
        ("昨日0~3%", 0.0, 0.03),
        ("昨日3~8%", 0.03, 0.08),
        ("昨日>=8%", 0.08, None),
    ),
    "day_change": (
        ("当日<0%", None, 0.0),
        ("当日0~3%", 0.0, 0.03),
        ("当日3~8%", 0.03, 0.08),
        ("当日8~15%", 0.08, 0.15),
        ("当日>=15%", 0.15, None),
    ),
    "breadth": (
        ("市场<40%", None, 0.40),
        ("市场40~50%", 0.40, 0.50),
        ("市场50~60%", 0.50, 0.60),
        ("市场>=60%", 0.60, None),
    ),
    "sector_breadth": (
        ("热门池<40%", None, 0.40),
        ("热门池40~55%", 0.40, 0.55),
        ("热门池55~70%", 0.55, 0.70),
        ("热门池>=70%", 0.70, None),
    ),
    "relative_strength": (
        ("落后>2%", None, -0.02),
        ("落后0~2%", -0.02, 0.0),
        ("领先0~1.5%", 0.0, 0.015),
        ("领先1.5~3%", 0.015, 0.03),
        ("领先>=3%", 0.03, None),
    ),
    "activity_percentile": (
        ("活跃度后50%", None, 0.50),
        ("活跃度50~70%", 0.50, 0.70),
        ("活跃度70~90%", 0.70, 0.90),
        ("活跃度前10%", 0.90, None),
    ),
    "confirm_vwap_distance": (
        ("VWAP下方>1%", None, -0.01),
        ("VWAP下方0~1%", -0.01, 0.0),
        ("VWAP上方0~1%", 0.0, 0.01),
        ("VWAP上方>=1%", 0.01, None),
    ),
    "watch_max_drawdown": (
        ("回撤<-2%", None, -0.02),
        ("回撤-2~-1%", -0.02, -0.01),
        ("回撤-1~-0.3%", -0.01, -0.003),
        ("回撤>-0.3%", -0.003, None),
    ),
    "index": (
        ("<=10:30", None, float(flow.IDX["10:30"] + 1)),
        ("10:31~11:30", float(flow.IDX["10:30"] + 1), float(flow.IDX["11:30"] + 1)),
        ("11:31~14:30", float(flow.IDX["11:30"] + 1), float(flow.IDX["14:30"] + 1)),
        (">14:30", float(flow.IDX["14:30"] + 1), None),
    ),
}


def finite_value(event: grid.Event, factor: str) -> float | None:
    value = getattr(event, factor, None)
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def matches_filter(event: grid.Event, item: FilterSpec) -> bool:
    value = finite_value(event, item.factor)
    if value is None:
        return False
    if item.operation == "ge":
        return value >= item.value
    if item.operation == "le":
        return value <= item.value
    raise ValueError(f"unsupported operation: {item.operation}")


def matches_config(event: grid.Event, config: StrategyConfig) -> bool:
    return all(matches_filter(event, item) for item in config.filters)


def split_days(days: Sequence[str], validation_days: int = 10) -> tuple[set[str], set[str]]:
    ordered = sorted(set(days))
    if len(ordered) <= validation_days:
        raise ValueError("not enough complete days for a holdout split")
    return set(ordered[:-validation_days]), set(ordered[-validation_days:])


def summarize(events: Sequence[grid.Event]) -> dict | None:
    if not events:
        return None
    eod = np.asarray([event.eod - ROUND_TRIP_COST for event in events], dtype=float)
    mfe60 = np.asarray([event.mfe60 for event in events], dtype=float)
    mfe_eod = np.asarray([event.mfe_eod for event in events], dtype=float)
    mae60 = np.asarray([event.mae60 for event in events], dtype=float)
    target_1_5 = np.where(mfe_eod >= 0.015, 0.015 - ROUND_TRIP_COST, eod)
    by_day: dict[str, list[float]] = defaultdict(list)
    for event, value in zip(events, eod):
        by_day[event.day].append(float(value))
    day_returns = np.asarray([np.mean(values) for values in by_day.values()])
    result = {
        "n": len(events),
        "days": len(by_day),
        "stocks": len({event.code for event in events}),
        "net_eod_mean": float(eod.mean()),
        "net_eod_median": float(np.median(eod)),
        "net_eod_p10": float(np.percentile(eod, 10)),
        "net_eod_p90": float(np.percentile(eod, 90)),
        "win_ratio": float((eod > 0).mean()),
        "day_mean": float(day_returns.mean()),
        "positive_days": float((day_returns > 0).mean()),
        "mfe60_median": float(np.median(mfe60)),
        "mfe_eod_median": float(np.median(mfe_eod)),
        "mfe_eod_p90": float(np.percentile(mfe_eod, 90)),
        "mfe_eod_max": float(mfe_eod.max()),
        "mae60_median": float(np.median(mae60)),
        "mae60_le_minus2": float((mae60 <= -0.02).mean()),
        "target_1_5_mean": float(target_1_5.mean()),
        "reached_1_5": float((mfe_eod >= 0.015).mean()),
        "reached_3": float((mfe_eod >= 0.03).mean()),
        "reached_5": float((mfe_eod >= 0.05).mean()),
    }
    result["score"] = float(
        result["day_mean"] * 100.0
        + 0.35 * result["reached_1_5"]
        + 0.15 * result["reached_3"]
        + 0.10 * result["positive_days"]
        + 0.10 * result["win_ratio"]
        - 0.35 * result["mae60_le_minus2"]
    )
    return result


def serialize_event(event: grid.Event) -> dict:
    return {
        "code": event.code,
        "day": event.day,
        "minute": event.minute,
        "price": event.price,
        "pos20": finite_value(event, "pos20"),
        "extension_atr": finite_value(event, "extension_atr"),
        "prev_ret": finite_value(event, "prev_ret"),
        "day_change": finite_value(event, "day_change"),
        "market_breadth": finite_value(event, "breadth"),
        "sector_breadth": finite_value(event, "sector_breadth"),
        "relative_strength": finite_value(event, "relative_strength"),
        "activity_percentile": finite_value(event, "activity_percentile"),
        "confirm_vwap_distance": finite_value(event, "confirm_vwap_distance"),
        "watch_max_drawdown": finite_value(event, "watch_max_drawdown"),
        "mfe60": event.mfe60,
        "mae60": event.mae60,
        "mfe_eod": event.mfe_eod,
        "eod_net": event.eod - ROUND_TRIP_COST,
        "time_to_1_5": event.time_to_1_5,
    }


def valid_training(summary: dict | None, *, half: bool = False) -> bool:
    if not summary:
        return False
    if half:
        return summary["n"] >= MIN_HALF_SAMPLES and summary["days"] >= MIN_HALF_DAYS
    return summary["n"] >= MIN_TRAIN_SAMPLES and summary["days"] >= MIN_TRAIN_DAYS


def selection_score(full: dict, early: dict, late: dict) -> float:
    scores = [full["score"], early["score"], late["score"]]
    return float(min(scores) - 0.15 * (max(scores) - min(scores)))


def _f(name: str, factor: str, operation: str, value: float) -> FilterSpec:
    return FilterSpec(name, factor, operation, float(value))


def strategy_configs() -> dict[str, list[StrategyConfig]]:
    result: dict[str, list[StrategyConfig]] = defaultdict(list)

    absorption_flows = [
        grid.FlowSpec(15, threshold, scale, ratio, count, span)
        for threshold in (2.0, 3.0, 4.0)
        for scale in (1.0, 1.25)
        for ratio in (0.60, 0.65, 0.75)
        for count, span in ((2, 5), (3, 10), (4, 15))
    ]
    for spec in absorption_flows:
        for position in (0.35, 0.50, 0.70):
            for breadth in (0.35, 0.40, 0.50):
                for vwap in (-0.01, -0.005, 0.0):
                    result["capital_absorption"].append(StrategyConfig(
                        "capital_absorption", spec, (
                            _f("position", "pos20", "le", position),
                            _f("market_breadth", "breadth", "ge", breadth),
                            _f("vwap", "confirm_vwap_distance", "ge", vwap),
                            _f("drawdown", "confirm_drawdown", "ge", -0.015),
                            _f("cutoff", "index", "le", flow.IDX["11:30"]),
                        )
                    ))

    momentum_flows = [
        grid.FlowSpec(window, threshold, scale, ratio, count, span)
        for window in (10, 15)
        for threshold in (3.0, 4.0)
        for scale in (1.25, 1.5)
        for ratio in (0.75, 0.80)
        for count, span in ((2, 5), (3, 10))
    ]
    for spec in momentum_flows:
        for day_change in (0.0, 0.03):
            for extension in (1.0, 2.0):
                for relative in (0.0, 0.015):
                    for activity in (0.50, 0.70):
                        result["momentum_continuation"].append(StrategyConfig(
                            "momentum_continuation", spec, (
                                _f("day_change", "day_change", "ge", day_change),
                                _f("extension", "extension_atr", "le", extension),
                                _f("relative_strength", "relative_strength", "ge", relative),
                                _f("activity", "activity_percentile", "ge", activity),
                                _f("vwap", "confirm_vwap_distance", "ge", -0.005),
                                _f("cutoff", "index", "le", flow.IDX["14:30"]),
                            )
                        ))

    early_flows = [
        grid.FlowSpec(window, threshold, scale, ratio, 2, 5)
        for window in (10, 15)
        for threshold in (2.0, 3.0)
        for scale in (1.0, 1.25)
        for ratio in (0.65, 0.75)
    ]
    for spec in early_flows:
        for previous in (0.0, 0.03):
            for extension in (1.0, 2.0):
                for relative in (0.0, 0.015):
                    for activity in (0.50, 0.70):
                        result["early_runner"].append(StrategyConfig(
                            "early_runner", spec, (
                                _f("previous_day", "prev_ret", "ge", previous),
                                _f("extension", "extension_atr", "le", extension),
                                _f("relative_strength", "relative_strength", "ge", relative),
                                _f("activity", "activity_percentile", "ge", activity),
                                _f("vwap", "confirm_vwap_distance", "ge", -0.005),
                                _f("cutoff", "index", "le", flow.IDX["10:30"]),
                            )
                        ))

    pullback_flows = [
        grid.FlowSpec(window, threshold, scale, ratio, count, span)
        for window in (15, 30)
        for threshold in (2.0, 3.0)
        for scale in (1.0, 1.25)
        for ratio in (0.60, 0.65)
        for count, span in ((3, 10), (4, 15))
    ]
    for spec in pullback_flows:
        for floor in (-0.02, -0.015):
            for present in (-0.005, -0.003):
                for confirm in (-0.01, -0.005):
                    for relative in (0.0, 0.015):
                        result["pullback_reacceleration"].append(StrategyConfig(
                            "pullback_reacceleration", spec, (
                                _f("pullback_floor", "watch_max_drawdown", "ge", floor),
                                _f("pullback_present", "watch_max_drawdown", "le", present),
                                _f("peak_recovery", "confirm_drawdown", "ge", confirm),
                                _f("vwap", "confirm_vwap_distance", "ge", -0.005),
                                _f("relative_strength", "relative_strength", "ge", relative),
                                _f("cutoff", "index", "le", flow.IDX["14:30"]),
                            )
                        ))
    return dict(result)


def strategy_layers() -> dict[str, StrategyLayer]:
    rules = CandidateSignalRules
    window_minutes = getattr(rules, "FLOW_WINDOW_SECONDS", 900) // 60
    return {
        "S1": StrategyLayer(
            layer_id="S1",
            label="低位资金吸收",
            strategy_source="capital_absorption",
            replay_coverage="主规则等价",
            config=StrategyConfig(
                "capital_absorption",
                grid.FlowSpec(
                    window_minutes,
                    getattr(rules, "ABSORPTION_MIN_THRESHOLD_MULTIPLE", 3.0),
                    getattr(rules, "ABSORPTION_MIN_SCALE_MULTIPLE", 1.0),
                    getattr(rules, "ABSORPTION_MIN_BUY_RATIO", 0.65),
                    getattr(rules, "ABSORPTION_MIN_BUY_EVENTS", 3),
                    getattr(rules, "ABSORPTION_MIN_EVENT_SPAN_SECONDS", 600) // 60,
                ),
                (
                    _f(
                        "position", "pos20", "le",
                        rules.LOW_POSITION_MAX_PERCENTILE,
                    ),
                    _f(
                        "market_breadth", "breadth", "ge",
                        rules.MIN_MARKET_BREADTH,
                    ),
                    _f("vwap", "confirm_vwap_distance", "ge", -0.01),
                    _f("drawdown", "confirm_drawdown", "ge", -0.015),
                    _f(
                        "cutoff", "index", "le",
                        flow.IDX[rules.ENTRY_CUTOFF.strftime("%H:%M")],
                    ),
                ),
            ),
            caveats=("未重放运行时数据质量与流动性对象，只使用完整归档日。",),
        ),
        "S2": StrategyLayer(
            layer_id="S2",
            label="趋势回踩再启动",
            strategy_source="strong_trend_reentry",
            replay_coverage="保守代理",
            config=StrategyConfig(
                "strong_trend_reentry",
                grid.FlowSpec(
                    window_minutes,
                    getattr(rules, "STRONG_TREND_MIN_THRESHOLD_MULTIPLE", 4.0),
                    getattr(rules, "STRONG_TREND_MIN_SCALE_MULTIPLE", 1.5),
                    getattr(rules, "STRONG_TREND_MIN_BUY_RATIO", 0.72),
                    getattr(rules, "STRONG_TREND_MIN_BUY_EVENTS", 3),
                    getattr(rules, "STRONG_TREND_MIN_EVENT_SPAN_SECONDS", 120) // 60,
                ),
                (
                    _f(
                        "position", "pos20", "ge",
                        rules.STRONG_TREND_MIN_DAILY_PERCENTILE,
                    ),
                    _f(
                        "extension", "extension_atr", "le",
                        rules.STRONG_TREND_MAX_EXTENSION_ATR,
                    ),
                    _f(
                        "relative_strength", "relative_strength", "ge",
                        rules.STRONG_TREND_MIN_RELATIVE_STRENGTH / 100.0,
                    ),
                    _f(
                        "activity", "activity_percentile", "ge",
                        rules.STRONG_TREND_MIN_ACTIVITY_PERCENTILE,
                    ),
                    _f("day_flow", "day_main_net", "ge", 0.0),
                    _f("vwap_floor", "confirm_vwap_distance", "ge", -0.003),
                    _f("vwap_ceiling", "confirm_vwap_distance", "le", 0.03),
                    _f(
                        "cutoff", "index", "le",
                        flow.IDX[rules.MEMORY_WATCH_CUTOFF.strftime("%H:%M")],
                    ),
                ),
            ),
            caveats=(
                "分钟归档不能完整重建跨日资金记忆分数与状态，因此不得据此直接升级权限。",
                "活跃度或极强相对强势的线上 OR 条件以更严格的活跃度门槛代理。",
            ),
        ),
        "S3": StrategyLayer(
            layer_id="S3",
            label="严格动量",
            strategy_source="momentum_continuation",
            replay_coverage="主规则等价",
            config=StrategyConfig(
                "momentum_continuation",
                grid.FlowSpec(
                    window_minutes,
                    getattr(rules, "MOMENTUM_MIN_THRESHOLD_MULTIPLE", 3.0),
                    getattr(rules, "MOMENTUM_MIN_SCALE_MULTIPLE", 1.25),
                    getattr(rules, "MOMENTUM_MIN_BUY_RATIO", 0.80),
                    getattr(rules, "MOMENTUM_MIN_BUY_EVENTS", 3),
                    getattr(rules, "MOMENTUM_MIN_EVENT_SPAN_SECONDS", 600) // 60,
                ),
                (
                    _f(
                        "day_change", "day_change", "ge",
                        getattr(rules, "MOMENTUM_MIN_DAILY_CHANGE", 3.0) / 100.0,
                    ),
                    _f(
                        "extension", "extension_atr", "le",
                        rules.MOMENTUM_MAX_EXTENSION_ATR,
                    ),
                    _f(
                        "relative_strength", "relative_strength", "ge",
                        rules.MOMENTUM_MIN_RELATIVE_STRENGTH / 100.0,
                    ),
                    _f(
                        "activity", "activity_percentile", "ge",
                        rules.MOMENTUM_MIN_ACTIVITY_PERCENTILE,
                    ),
                    _f("vwap", "confirm_vwap_distance", "ge", -0.005),
                ),
            ),
            caveats=("未重放运行时数据质量、流动性和价格接受对象。",),
        ),
    }


def production_baselines() -> dict[str, StrategyConfig]:
    return {name: layer.config for name, layer in strategy_layers().items()}


def with_filter(config: StrategyConfig, item: FilterSpec) -> StrategyConfig:
    return replace(
        config,
        filters=tuple(
            existing for existing in config.filters if existing.name != item.name
        ) + (item,),
    )


def without_filter(config: StrategyConfig, name: str) -> StrategyConfig:
    return replace(
        config,
        filters=tuple(item for item in config.filters if item.name != name),
    )


def rule_experiments(
    baselines: dict[str, StrategyConfig],
    selected: dict[str, StrategyConfig],
) -> dict[str, tuple[str, StrategyConfig]]:
    experiments: dict[str, tuple[str, StrategyConfig]] = {}
    selected_absorption = selected.get("capital_absorption")
    if selected_absorption is not None:
        strict_flow = replace(
            baselines["S1"], flow_spec=selected_absorption.flow_spec
        )
        experiments["S1_STRICT_FLOW"] = (
            "S1 仅收紧资金流",
            strict_flow,
        )
        experiments["S1_STRICT_FLOW_VWAP"] = (
            "S1 收紧资金流且站上VWAP",
            with_filter(
                strict_flow,
                _f("vwap", "confirm_vwap_distance", "ge", 0.0),
            ),
        )

    momentum = baselines["S3"]
    experiments["S3_LEGACY_NO_DAY_CHANGE"] = (
        "S3 对照：移除3%强势门槛",
        without_filter(momentum, "day_change"),
    )
    experiments["S3_CUTOFF"] = (
        "S3 新规则再限制14:30前",
        with_filter(momentum, _f("cutoff", "index", "le", flow.IDX["14:30"])),
    )
    return experiments


def unique_flow_specs(configs: dict[str, Sequence[StrategyConfig]]) -> list[grid.FlowSpec]:
    return sorted({item.flow_spec for rows in configs.values() for item in rows})


def _events_for_days(
    events: Sequence[grid.Event], days: set[str], config: StrategyConfig | None = None
) -> list[grid.Event]:
    return [
        event for event in events
        if event.day in days and (config is None or matches_config(event, config))
    ]


def select_best_config(
    configs: Sequence[StrategyConfig],
    events_by_flow: dict[str, list[grid.Event]],
    train_days: set[str],
) -> tuple[StrategyConfig | None, list[dict]]:
    ordered_days = sorted(train_days)
    middle = max(1, len(ordered_days) // 2)
    early_days = set(ordered_days[:middle])
    late_days = set(ordered_days[middle:])
    ranked = []
    for config in configs:
        source = events_by_flow.get(config.flow_spec.key, [])
        full = summarize(_events_for_days(source, train_days, config))
        early = summarize(_events_for_days(source, early_days, config))
        late = summarize(_events_for_days(source, late_days, config))
        if not valid_training(full) or not valid_training(early, half=True) or not valid_training(late, half=True):
            continue
        ranked.append({
            "config": config,
            "train": full,
            "train_early": early,
            "train_late": late,
            "selection_score": selection_score(full, early, late),
        })
    ranked.sort(
        key=lambda row: (
            row["selection_score"],
            row["train"]["days"],
            row["train"]["n"],
        ),
        reverse=True,
    )
    return (ranked[0]["config"] if ranked else None), ranked


def bucket_label(value: float, bins: Sequence[tuple[str, float | None, float | None]]) -> str | None:
    for label, lower, upper in bins:
        if lower is not None and value < lower:
            continue
        if upper is not None and value >= upper:
            continue
        return label
    return None


def factor_buckets(events: Sequence[grid.Event], days: set[str]) -> dict[str, list[dict]]:
    output = {}
    for factor, bins in FACTOR_BINS.items():
        grouped: dict[str, list[grid.Event]] = defaultdict(list)
        for event in events:
            if event.day not in days:
                continue
            value = finite_value(event, factor)
            if value is None:
                continue
            label = bucket_label(value, bins)
            if label is not None:
                grouped[label].append(event)
        rows = []
        for label, _lower, _upper in bins:
            metrics = summarize(grouped.get(label, []))
            if metrics:
                rows.append({"bucket": label, **metrics})
        output[factor] = rows
    return output


def serialize_config(config: StrategyConfig) -> dict:
    return {
        "strategy": config.strategy,
        "flow_spec": asdict(config.flow_spec),
        "flow_key": config.flow_spec.key,
        "filters": [asdict(item) for item in config.filters],
        "key": config.key,
    }


def serialize_layer(layer: StrategyLayer) -> dict:
    return {
        "layer_id": layer.layer_id,
        "label": layer.label,
        "strategy_source": layer.strategy_source,
        "replay_coverage": layer.replay_coverage,
        "caveats": list(layer.caveats),
    }


def position_band(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "unknown"
    if value <= 0.50:
        return "low"
    if value <= 0.80:
        return "middle"
    return "high"


def select_matched_controls(
    event: grid.Event,
    candidates: Sequence[ControlCandidate],
) -> tuple[list[ControlCandidate], str]:
    available = [item for item in candidates if item.code != event.code]
    event_activity = finite_value(event, "activity_percentile")
    event_band = position_band(finite_value(event, "pos20"))
    same_band = [item for item in available if item.position_band == event_band]
    strict = [
        item for item in same_band
        if event_activity is not None
        and item.activity_percentile is not None
        and abs(item.activity_percentile - event_activity) <= ACTIVITY_MATCH_WIDTH
    ]
    if len(strict) >= MIN_MATCHED_CONTROLS:
        selected, mode = strict, "同位置且活跃度相近"
    elif len(same_band) >= MIN_MATCHED_CONTROLS:
        selected, mode = same_band, "同位置"
    else:
        selected, mode = available, "同分钟热门池"
    if len(selected) < MIN_MATCHED_CONTROLS:
        return [], "样本不足"

    def distance(item: ControlCandidate) -> tuple[float, str]:
        if event_activity is None or item.activity_percentile is None:
            return math.inf, item.code
        return abs(item.activity_percentile - event_activity), item.code

    return sorted(selected, key=distance)[:MAX_MATCHED_CONTROLS], mode


def build_control_pools(
    conn: sqlite3.Connection,
    context: dict,
    events: Sequence[grid.Event],
) -> dict[tuple[str, int], list[ControlCandidate]]:
    requested: dict[str, set[int]] = defaultdict(set)
    for event in events:
        requested[event.day].add(event.index)
    pools: dict[tuple[str, int], list[ControlCandidate]] = {}
    for day, indexes in sorted(requested.items()):
        records = flow.load_day(conn, day)
        derived = {
            code: flow.derive(record, code, day, context["next_close"])
            for code, record in records.items()
        }
        intraday = grid.build_universe_intraday_context(
            records,
            derived,
            day,
            context["previous_close"],
            context["allowed"],
        )
        for index in sorted(indexes):
            candidates = []
            for code in sorted(context["allowed"]):
                base = derived.get(code)
                if base is None:
                    continue
                prices = base["p"]
                price = float(prices[index])
                if not math.isfinite(price) or price <= 0:
                    continue
                feature = grid.daily.daily_feature(code, day, price, context["bars"])
                if feature is None:
                    continue
                code_context = intraday.get(code) or {}
                activity_values = code_context.get("activity_percentile")
                activity = (
                    float(activity_values[index])
                    if activity_values is not None
                    and math.isfinite(float(activity_values[index]))
                    else None
                )
                high_eod = grid.future_extreme(prices, index, None, np.max)
                low60 = grid.future_extreme(prices, index, 60, np.min)
                candidates.append(ControlCandidate(
                    code=code,
                    day=day,
                    index=index,
                    position_band=position_band(float(feature.pos20)),
                    activity_percentile=activity,
                    eod=float(prices[-1] / price - 1.0),
                    mfe_eod=float(high_eod / price - 1.0),
                    mae60=float(low60 / price - 1.0),
                ))
            pools[(day, index)] = candidates
    return pools


def matched_control_rows(
    events: Sequence[grid.Event],
    pools: dict[tuple[str, int], list[ControlCandidate]],
) -> list[dict]:
    rows = []
    for event in events:
        controls, mode = select_matched_controls(
            event, pools.get((event.day, event.index), [])
        )
        if not controls:
            continue
        control_eod = float(np.median([item.eod for item in controls]))
        control_mfe = float(np.median([item.mfe_eod for item in controls]))
        control_mae60 = float(np.median([item.mae60 for item in controls]))
        rows.append({
            "code": event.code,
            "day": event.day,
            "minute": event.minute,
            "control_count": len(controls),
            "match_mode": mode,
            "signal_net_eod": float(event.eod - ROUND_TRIP_COST),
            "control_net_eod": float(control_eod - ROUND_TRIP_COST),
            "excess_eod": float(event.eod - control_eod),
            "signal_mfe_eod": float(event.mfe_eod),
            "control_mfe_eod": control_mfe,
            "signal_mae60": float(event.mae60),
            "control_mae60": control_mae60,
            "signal_reached_1_5": bool(event.mfe_eod >= 0.015),
            "control_reached_1_5": float(np.mean([
                item.mfe_eod >= 0.015 for item in controls
            ])),
        })
    return rows


def matched_control_summary(rows: Sequence[dict]) -> dict | None:
    if not rows:
        return None
    signal = np.asarray([row["signal_net_eod"] for row in rows], dtype=float)
    control = np.asarray([row["control_net_eod"] for row in rows], dtype=float)
    excess = signal - control
    signal_hits = np.asarray(
        [row["signal_reached_1_5"] for row in rows], dtype=float
    )
    control_hits = np.asarray(
        [row["control_reached_1_5"] for row in rows], dtype=float
    )
    by_day: dict[str, list[float]] = defaultdict(list)
    for row, value in zip(rows, excess):
        by_day[row["day"]].append(float(value))
    day_excess = {
        day: float(np.mean(values)) for day, values in by_day.items()
    }
    best_day = max(day_excess, key=day_excess.get)
    leave_best_day = np.asarray([
        value for row, value in zip(rows, excess) if row["day"] != best_day
    ], dtype=float)
    ordered_excess = np.sort(excess)
    trimmed_excess = (
        ordered_excess[1:-1] if len(ordered_excess) >= 5 else ordered_excess
    )
    return {
        "n": len(rows),
        "days": len({row["day"] for row in rows}),
        "stocks": len({row["code"] for row in rows}),
        "signal_net_eod_mean": float(signal.mean()),
        "control_net_eod_mean": float(control.mean()),
        "excess_eod_mean": float(excess.mean()),
        "excess_eod_median": float(np.median(excess)),
        "excess_eod_trimmed_mean": float(trimmed_excess.mean()),
        "excess_eod_p10": float(np.percentile(excess, 10)),
        "excess_eod_p90": float(np.percentile(excess, 90)),
        "outperform_ratio": float((excess > 0).mean()),
        "positive_day_ratio": float(np.mean([
            value > 0 for value in day_excess.values()
        ])),
        "best_day": best_day,
        "best_day_excess": day_excess[best_day],
        "worst_day_excess": min(day_excess.values()),
        "leave_best_day_out_excess_mean": (
            float(leave_best_day.mean()) if leave_best_day.size else None
        ),
        "signal_reached_1_5": float(signal_hits.mean()),
        "control_reached_1_5": float(control_hits.mean()),
        "incremental_reached_1_5": float((signal_hits - control_hits).mean()),
        "median_control_count": float(np.median([
            row["control_count"] for row in rows
        ])),
        "match_modes": dict(sorted(Counter(
            row["match_mode"] for row in rows
        ).items())),
    }


def matched_control_windows(
    rows: Sequence[dict],
    ordered_days: Sequence[str],
    window_days: int = 5,
) -> list[dict]:
    if window_days <= 0:
        raise ValueError("window_days must be positive")
    windows = []
    days = sorted(set(ordered_days))
    for start in range(0, len(days), window_days):
        window = days[start:start + window_days]
        if not window:
            continue
        window_set = set(window)
        metrics = matched_control_summary([
            row for row in rows if row["day"] in window_set
        ])
        windows.append({
            "start": window[0],
            "end": window[-1],
            "trading_days": len(window),
            "metrics": metrics,
        })
    return windows


def ablation_results(
    config: StrategyConfig,
    source: Sequence[grid.Event],
    train_days: set[str],
    test_days: set[str],
) -> list[dict]:
    variants = [("完整规则", config)] + [
        (
            f"删除:{item.name}",
            replace(config, filters=tuple(value for value in config.filters if value != item)),
        )
        for item in config.filters
    ]
    return [
        {
            "variant": label,
            "train": summarize(_events_for_days(source, train_days, variant)),
            "test": summarize(_events_for_days(source, test_days, variant)),
        }
        for label, variant in variants
    ]


def overlap_results(selected_events: dict[str, Sequence[grid.Event]]) -> list[dict]:
    sets = {
        name: {(event.code, event.day) for event in events}
        for name, events in selected_events.items()
    }
    names = sorted(sets)
    rows = []
    for left_index, left in enumerate(names):
        for right in names[left_index + 1:]:
            union = sets[left] | sets[right]
            overlap = sets[left] & sets[right]
            rows.append({
                "left": left,
                "right": right,
                "left_n": len(sets[left]),
                "right_n": len(sets[right]),
                "overlap": len(overlap),
                "jaccard": len(overlap) / len(union) if union else 0.0,
            })
    return rows


def flow_sequence_sweep(
    events_by_flow: dict[str, list[grid.Event]],
    train_days: set[str],
    test_days: set[str],
) -> list[dict]:
    rows = []
    for count, span in ((2, 5), (3, 10), (4, 15)):
        spec = grid.FlowSpec(15, 2.0, 1.0, 0.60, count, span)
        source = events_by_flow.get(spec.key, [])
        rows.append({
            "flow_key": spec.key,
            "event_count": count,
            "min_span": span,
            "train": summarize(_events_for_days(source, train_days)),
            "test": summarize(_events_for_days(source, test_days)),
        })
    return rows


def pct(value: float | None) -> str:
    return "--" if value is None else f"{value * 100:.2f}%"


def render_metrics(summary: dict | None) -> str:
    if not summary:
        return "-- | -- | -- | -- | -- | -- | --"
    return " | ".join((
        str(summary["n"]),
        str(summary["days"]),
        pct(summary["net_eod_mean"]),
        pct(summary["reached_1_5"]),
        pct(summary["reached_3"]),
        pct(summary["reached_5"]),
        pct(summary["mae60_le_minus2"]),
    ))


def render_report(payload: dict) -> str:
    meta = payload["meta"]
    lines = [
        "# 热门股多策略因子回测",
        "",
        f"- 完整交易日：{meta['complete_days']}；训练：{meta['train_days']}；最后 {meta['test_days']} 日盲测。",
        f"- 热门股票：{meta['universe_size']} 只；事件统一按确认分钟价格生成，往返成本 {pct(ROUND_TRIP_COST)}。",
        "- 配置只按训练集前后半段稳健分数选择；盲测结果不参与排序。",
        "",
        "## 各策略训练选参及盲测",
        "",
        "| 策略 | 流入参数 | 训练样本 | 训练日 | 训练收盘净收益 | 盲测样本 | 盲测日 | 盲测收盘净收益 | 1.5%到价换票 | 盲测达1.5% | 盲测达3% | 盲测达5% | 盲测60m亏2% |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, result in payload["strategies"].items():
        label = STRATEGY_LABELS.get(name, name)
        if not result.get("selected"):
            lines.append(f"| {label} | 无有效配置 | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- |")
            continue
        train = result["train"]
        test = result["test"] or {}
        lines.append(
            f"| {label} | `{result['selected']['flow_key']}` | {train['n']} | {train['days']} | {pct(train['net_eod_mean'])} | "
            f"{test.get('n', '--')} | {test.get('days', '--')} | {pct(test.get('net_eod_mean'))} | "
            f"{pct(test.get('target_1_5_mean'))} | {pct(test.get('reached_1_5'))} | {pct(test.get('reached_3'))} | "
            f"{pct(test.get('reached_5'))} | {pct(test.get('mae60_le_minus2'))} |"
        )

    lines.extend((
        "",
        "## S1/S2/S3 当前规则回放",
        "",
        "| 策略层 | 回放完整度 | 流入参数 | 训练样本 | 训练净收益 | 盲测样本 | 盲测日 | 盲测净收益 | 1.5%到价换票 | 盲测达1.5% | 盲测达3% | 盲测达5% |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ))
    for name, result in payload["production_baselines"].items():
        train = result["train"] or {}
        test = result["test"] or {}
        layer = result["layer"]
        lines.append(
            f"| {name} {layer['label']} | {layer['replay_coverage']} | `{result['config']['flow_key']}` | {train.get('n', '--')} | {pct(train.get('net_eod_mean'))} | "
            f"{test.get('n', '--')} | {test.get('days', '--')} | {pct(test.get('net_eod_mean'))} | "
            f"{pct(test.get('target_1_5_mean'))} | {pct(test.get('reached_1_5'))} | "
            f"{pct(test.get('reached_3'))} | {pct(test.get('reached_5'))} |"
        )

    lines.extend((
        "",
        "## 同分钟热门股匹配对照",
        "",
        "每个信号优先匹配同一分钟、同一20日位置区间且盘中活跃度相差不超过20个百分点的其他热门股；不足5只时依次放宽为同位置、同分钟热门池。信号和对照均扣除相同往返成本。",
        "",
        "### 当前 S1/S2/S3 规则",
        "",
        "| 策略层 | 匹配信号 | 交易日 | 股票数 | 信号净收益 | 对照净收益 | 平均超额 | 超额中位数 | 去极值超额 | 去最佳日超额 | 正超额日 | 跑赢对照 | 命中增量 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ))
    for name, result in payload["production_baselines"].items():
        matched = result["matched_control"]["test"] or {}
        layer = result["layer"]
        lines.append(
            f"| {name} {layer['label']} | {matched.get('n', '--')} | {matched.get('days', '--')} | "
            f"{matched.get('stocks', '--')} | {pct(matched.get('signal_net_eod_mean'))} | "
            f"{pct(matched.get('control_net_eod_mean'))} | {pct(matched.get('excess_eod_mean'))} | "
            f"{pct(matched.get('excess_eod_median'))} | {pct(matched.get('excess_eod_trimmed_mean'))} | "
            f"{pct(matched.get('leave_best_day_out_excess_mean'))} | {pct(matched.get('positive_day_ratio'))} | "
            f"{pct(matched.get('outperform_ratio'))} | {pct(matched.get('incremental_reached_1_5'))} |"
        )

    lines.extend((
        "",
        "### 训练期选参策略",
        "",
        "| 策略 | 匹配信号 | 交易日 | 股票数 | 信号净收益 | 对照净收益 | 平均超额 | 超额中位数 | 去极值超额 | 去最佳日超额 | 正超额日 | 跑赢对照 | 命中增量 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ))
    for name, result in payload["strategies"].items():
        matched = (result.get("matched_control") or {}).get("test") or {}
        label = STRATEGY_LABELS.get(name, name)
        lines.append(
            f"| {label} | {matched.get('n', '--')} | {matched.get('days', '--')} | "
            f"{matched.get('stocks', '--')} | {pct(matched.get('signal_net_eod_mean'))} | "
            f"{pct(matched.get('control_net_eod_mean'))} | {pct(matched.get('excess_eod_mean'))} | "
            f"{pct(matched.get('excess_eod_median'))} | {pct(matched.get('excess_eod_trimmed_mean'))} | "
            f"{pct(matched.get('leave_best_day_out_excess_mean'))} | {pct(matched.get('positive_day_ratio'))} | "
            f"{pct(matched.get('outperform_ratio'))} | {pct(matched.get('incremental_reached_1_5'))} |"
        )

    lines.extend((
        "",
        "## 规则变更探索",
        "",
        "以下变更用于拆分条件贡献。由于本轮已经观察过同一盲测区间，它们属于探索结果，不能再视为独立盲测，也不能据此直接升级正式提醒权限。",
        "",
        "| 变更 | 盲测样本 | 交易日 | 信号净收益 | 对照净收益 | 平均超额 | 超额中位数 | 去极值超额 | 去最佳日超额 | 正超额日 | 跑赢对照 | 命中增量 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ))
    for result in payload["rule_experiments"].values():
        matched = (result.get("matched_control") or {}).get("test") or {}
        lines.append(
            f"| {result['label']} | {matched.get('n', '--')} | {matched.get('days', '--')} | "
            f"{pct(matched.get('signal_net_eod_mean'))} | {pct(matched.get('control_net_eod_mean'))} | "
            f"{pct(matched.get('excess_eod_mean'))} | {pct(matched.get('excess_eod_median'))} | "
            f"{pct(matched.get('excess_eod_trimmed_mean'))} | "
            f"{pct(matched.get('leave_best_day_out_excess_mean'))} | {pct(matched.get('positive_day_ratio'))} | "
            f"{pct(matched.get('outperform_ratio'))} | {pct(matched.get('incremental_reached_1_5'))} |"
        )

    lines.extend((
        "",
        "## 5交易日分段稳定性",
        "",
        "分段只用于观察盲测期内的跨日期一致性；没有信号的窗口保留显示，不用后段结果反向选参数。",
        "",
        "| 规则 | 区间 | 信号数 | 信号净收益 | 对照净收益 | 平均超额 | 超额中位数 | 正超额日 | 跑赢对照 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ))
    stability_groups = [
        (
            f"{name} {result['layer']['label']}",
            result.get("test_windows") or [],
        )
        for name, result in payload["production_baselines"].items()
    ]
    stability_groups.extend(
        (
            f"选参-{STRATEGY_LABELS.get(name, name)}",
            result.get("test_windows") or [],
        )
        for name, result in payload["strategies"].items()
    )
    stability_groups.extend(
        (result["label"], result.get("test_windows") or [])
        for result in payload["rule_experiments"].values()
    )
    for label, windows in stability_groups:
        for window in windows:
            metrics = window["metrics"] or {}
            lines.append(
                f"| {label} | {window['start']}~{window['end']} | "
                f"{metrics.get('n', 0)} | {pct(metrics.get('signal_net_eod_mean'))} | "
                f"{pct(metrics.get('control_net_eod_mean'))} | {pct(metrics.get('excess_eod_mean'))} | "
                f"{pct(metrics.get('excess_eod_median'))} | {pct(metrics.get('positive_day_ratio'))} | "
                f"{pct(metrics.get('outperform_ratio'))} |"
            )

    lines.extend(("", "### 回放限制", ""))
    for name, result in payload["production_baselines"].items():
        layer = result["layer"]
        for caveat in layer["caveats"]:
            lines.append(f"- {name} {layer['label']}：{caveat}")

    lines.extend((
        "",
        "## 多次流入次数",
        "",
        "| 独立流入 | 训练样本 | 训练日 | 训练净收益 | 训练达1.5% | 训练达3% | 训练达5% | 盲测样本 | 盲测净收益 | 盲测达1.5% |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ))
    for row in payload["flow_sequence_sweep"]:
        train = row["train"] or {}
        test = row["test"] or {}
        lines.append(
            f"| {row['event_count']}次/{row['min_span']}分钟 | {train.get('n', '--')} | {train.get('days', '--')} | {pct(train.get('net_eod_mean'))} | "
            f"{pct(train.get('reached_1_5'))} | {pct(train.get('reached_3'))} | {pct(train.get('reached_5'))} | "
            f"{test.get('n', '--')} | {pct(test.get('net_eod_mean'))} | {pct(test.get('reached_1_5'))} |"
        )

    lines.extend((
        "",
        "## 因子消融",
        "",
        "以下结果使用训练集选出的唯一配置，删除一个因子后重新统计；用于判断该因子是否真的贡献增量。",
    ))
    for name, result in payload["strategies"].items():
        if not result.get("selected"):
            continue
        lines.extend((
            "",
            f"### {name}",
            "",
            "| 规则 | 训练样本 | 训练日 | 训练净收益 | 训练达1.5% | 训练达3% | 训练达5% | 训练60m亏2% | 盲测样本 | 盲测日 | 盲测净收益 | 盲测达1.5% | 盲测达3% | 盲测达5% | 盲测60m亏2% |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ))
        for row in result["ablation"]:
            lines.append(
                f"| {row['variant']} | {render_metrics(row['train'])} | {render_metrics(row['test'])} |"
            )

    lines.extend((
        "",
        "## 说明",
        "",
        "- `达1.5%/3%/5%` 使用买入确认后的日内最高价，只衡量买点潜力，不等同于真实已实现收益。",
        "- `收盘净收益` 使用确认价到收盘价并扣除 0.25% 往返成本，未假设能卖在最高点。",
        "- `平均超额` 比较信号与同分钟匹配热门股的收盘净收益；只有持续为正，才能说明策略不只是跟随当日市场。",
        "- 样本不足的策略保留为观察，不应直接上线为正式买入提醒。",
    ))
    return "\n".join(lines) + "\n"


def run(conn: sqlite3.Connection, universe_limit: int) -> dict:
    context = grid.load_context(conn, universe_limit)
    train_days, test_days = split_days(context["evaluation_days"], grid.VALIDATION_DAYS)
    context["train_days"] = train_days
    context["test_days"] = test_days
    universe_selection_end = max(train_days)
    context["universe"] = grid.daily.load_hot_ai_semiconductor_universe(
        conn,
        context["days"][0],
        universe_selection_end,
        universe_limit,
        include_screenshot_codes=False,
    )
    context["allowed"] = {item["code"] for item in context["universe"]}
    configs = strategy_configs()
    layers = strategy_layers()
    baselines = production_baselines()
    all_configs = {**configs, "_baselines": list(baselines.values())}
    specs = unique_flow_specs(all_configs)
    events = list(grid.iter_events(conn, context, specs, exit_choices=()))
    events_by_flow: dict[str, list[grid.Event]] = defaultdict(list)
    for event in events:
        events_by_flow[event.flow_key].append(event)

    strategies = {}
    selected_test_events = {}
    selected_event_sets = {}
    selected_configs = {}
    for name, choices in configs.items():
        selected, ranked = select_best_config(choices, events_by_flow, train_days)
        if selected is None:
            strategies[name] = {"selected": None, "searched": len(choices)}
            selected_test_events[name] = []
            selected_event_sets[name] = {"train": [], "test": []}
            continue
        source = events_by_flow[selected.flow_spec.key]
        selected_configs[name] = selected
        train_events = _events_for_days(source, train_days, selected)
        test_events = _events_for_days(source, test_days, selected)
        selected_test_events[name] = test_events
        selected_event_sets[name] = {
            "train": train_events,
            "test": test_events,
        }
        strategies[name] = {
            "selected": serialize_config(selected),
            "searched": len(choices),
            "selection_score": ranked[0]["selection_score"],
            "train": summarize(train_events),
            "train_early": ranked[0]["train_early"],
            "train_late": ranked[0]["train_late"],
            "test": summarize(test_events),
            "test_events": [serialize_event(event) for event in test_events],
            "ablation": ablation_results(selected, source, train_days, test_days),
        }

    research_spec = grid.FlowSpec(15, 2.0, 1.0, 0.60, 2, 5)
    research_events = events_by_flow.get(research_spec.key, [])
    baseline_results = {}
    baseline_event_sets = {}
    for name, config in baselines.items():
        source = events_by_flow.get(config.flow_spec.key, [])
        train_events = _events_for_days(source, train_days, config)
        test_events = _events_for_days(source, test_days, config)
        baseline_event_sets[name] = {
            "train": train_events,
            "test": test_events,
        }
        baseline_results[name] = {
            "layer": serialize_layer(layers[name]),
            "config": serialize_config(config),
            "train": summarize(train_events),
            "test": summarize(test_events),
        }
    experiment_results = {}
    experiment_event_sets = {}
    for name, (label, config) in rule_experiments(
        baselines, selected_configs
    ).items():
        source = events_by_flow.get(config.flow_spec.key, [])
        train_events = _events_for_days(source, train_days, config)
        test_events = _events_for_days(source, test_days, config)
        experiment_event_sets[name] = {
            "train": train_events,
            "test": test_events,
        }
        experiment_results[name] = {
            "label": label,
            "config": serialize_config(config),
            "train": summarize(train_events),
            "test": summarize(test_events),
        }
    all_control_events = [
        event
        for event_sets in (
            baseline_event_sets,
            selected_event_sets,
            experiment_event_sets,
        )
        for split_events in event_sets.values()
        for events_in_split in split_events.values()
        for event in events_in_split
    ]
    control_pools = build_control_pools(conn, context, all_control_events)
    ordered_test_days = sorted(test_days)
    for name, split_events in selected_event_sets.items():
        train_rows = matched_control_rows(split_events["train"], control_pools)
        test_rows = matched_control_rows(split_events["test"], control_pools)
        strategies[name]["matched_control"] = {
            "train": matched_control_summary(train_rows),
            "test": matched_control_summary(test_rows),
        }
        strategies[name]["test_matched_events"] = test_rows
        strategies[name]["test_windows"] = matched_control_windows(
            test_rows, ordered_test_days
        )
    for name, split_events in baseline_event_sets.items():
        train_rows = matched_control_rows(split_events["train"], control_pools)
        test_rows = matched_control_rows(split_events["test"], control_pools)
        baseline_results[name]["matched_control"] = {
            "train": matched_control_summary(train_rows),
            "test": matched_control_summary(test_rows),
        }
        baseline_results[name]["test_matched_events"] = test_rows
        baseline_results[name]["test_windows"] = matched_control_windows(
            test_rows, ordered_test_days
        )
    for name, split_events in experiment_event_sets.items():
        train_rows = matched_control_rows(split_events["train"], control_pools)
        test_rows = matched_control_rows(split_events["test"], control_pools)
        experiment_results[name]["matched_control"] = {
            "train": matched_control_summary(train_rows),
            "test": matched_control_summary(test_rows),
        }
        experiment_results[name]["test_matched_events"] = test_rows
        experiment_results[name]["test_windows"] = matched_control_windows(
            test_rows, ordered_test_days
        )
    return {
        "meta": {
            "complete_days": len(context["days"]),
            "evaluation_days": len(context["evaluation_days"]),
            "train_days": len(train_days),
            "test_days": len(test_days),
            "train_range": [min(train_days), max(train_days)],
            "test_range": [min(test_days), max(test_days)],
            "universe_size": len(context["universe"]),
            "universe_selection_end": universe_selection_end,
            "universe": context["universe"],
            "flow_specs": len(specs),
            "events": len(events),
            "matched_control_pools": len(control_pools),
            "dropped_days": context["dropped"],
        },
        "strategies": strategies,
        "production_baselines": baseline_results,
        "rule_experiments": experiment_results,
        "factor_buckets": {
            "train": factor_buckets(research_events, train_days),
            "test": factor_buckets(research_events, test_days),
        },
        "flow_sequence_sweep": flow_sequence_sweep(events_by_flow, train_days, test_days),
        "test_overlap": overlap_results(selected_test_events),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--universe-limit", type=int, default=40)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    conn = sqlite3.connect(args.db, uri=args.db.startswith("file:"))
    try:
        payload = run(conn, max(1, args.universe_limit))
    finally:
        conn.close()
    rendered_json = json.dumps(payload, ensure_ascii=False, indent=2)
    report = render_report(payload)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(rendered_json + "\n", encoding="utf-8")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
