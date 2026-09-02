#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Causal factor backtest for the V2 hot-stock strategy portfolio."""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
import json
import math
from pathlib import Path
import sqlite3
import sys
from typing import Iterable, Sequence

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import big_order_flow_eval as flow  # noqa: E402
import low_position_accumulation_grid as grid  # noqa: E402


ROUND_TRIP_COST = 0.0025
MIN_TRAIN_SAMPLES = 15
MIN_TRAIN_DAYS = 8
MIN_HALF_SAMPLES = 5
MIN_HALF_DAYS = 3


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


def production_baselines() -> dict[str, StrategyConfig]:
    return {
        "capital_absorption_current": StrategyConfig(
            "capital_absorption_current",
            grid.FlowSpec(15, 3.0, 1.0, 0.65, 3, 10),
            (
                _f("position", "pos20", "le", 0.50),
                _f("market_breadth", "breadth", "ge", 0.40),
                _f("vwap", "confirm_vwap_distance", "ge", -0.01),
                _f("drawdown", "confirm_drawdown", "ge", -0.015),
                _f("cutoff", "index", "le", flow.IDX["11:30"]),
            ),
        ),
        "momentum_current_proxy": StrategyConfig(
            "momentum_current_proxy",
            grid.FlowSpec(15, 4.0, 1.5, 0.80, 2, 5),
            (
                _f("activity", "activity_percentile", "ge", 0.50),
                _f("vwap", "confirm_vwap_distance", "ge", -0.005),
                _f("cutoff", "index", "le", flow.IDX["14:30"]),
            ),
        ),
    }


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
        if not result.get("selected"):
            lines.append(f"| {name} | 无有效配置 | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- |")
            continue
        train = result["train"]
        test = result["test"] or {}
        lines.append(
            f"| {name} | `{result['selected']['flow_key']}` | {train['n']} | {train['days']} | {pct(train['net_eod_mean'])} | "
            f"{test.get('n', '--')} | {test.get('days', '--')} | {pct(test.get('net_eod_mean'))} | "
            f"{pct(test.get('target_1_5_mean'))} | {pct(test.get('reached_1_5'))} | {pct(test.get('reached_3'))} | "
            f"{pct(test.get('reached_5'))} | {pct(test.get('mae60_le_minus2'))} |"
        )

    lines.extend((
        "",
        "## 当前生产参数对照",
        "",
        "| 基线 | 流入参数 | 训练样本 | 训练净收益 | 盲测样本 | 盲测日 | 盲测净收益 | 1.5%到价换票 | 盲测达1.5% | 盲测达3% | 盲测达5% |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ))
    for name, result in payload["production_baselines"].items():
        train = result["train"] or {}
        test = result["test"] or {}
        lines.append(
            f"| {name} | `{result['config']['flow_key']}` | {train.get('n', '--')} | {pct(train.get('net_eod_mean'))} | "
            f"{test.get('n', '--')} | {test.get('days', '--')} | {pct(test.get('net_eod_mean'))} | "
            f"{pct(test.get('target_1_5_mean'))} | {pct(test.get('reached_1_5'))} | "
            f"{pct(test.get('reached_3'))} | {pct(test.get('reached_5'))} |"
        )

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
    baselines = production_baselines()
    all_configs = {**configs, "_baselines": list(baselines.values())}
    specs = unique_flow_specs(all_configs)
    events = list(grid.iter_events(conn, context, specs, exit_choices=()))
    events_by_flow: dict[str, list[grid.Event]] = defaultdict(list)
    for event in events:
        events_by_flow[event.flow_key].append(event)

    strategies = {}
    selected_test_events = {}
    for name, choices in configs.items():
        selected, ranked = select_best_config(choices, events_by_flow, train_days)
        if selected is None:
            strategies[name] = {"selected": None, "searched": len(choices)}
            selected_test_events[name] = []
            continue
        source = events_by_flow[selected.flow_spec.key]
        train_events = _events_for_days(source, train_days, selected)
        test_events = _events_for_days(source, test_days, selected)
        selected_test_events[name] = test_events
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
    for name, config in baselines.items():
        source = events_by_flow.get(config.flow_spec.key, [])
        baseline_results[name] = {
            "config": serialize_config(config),
            "train": summarize(_events_for_days(source, train_days, config)),
            "test": summarize(_events_for_days(source, test_days, config)),
        }
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
            "dropped_days": context["dropped"],
        },
        "strategies": strategies,
        "production_baselines": baseline_results,
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
