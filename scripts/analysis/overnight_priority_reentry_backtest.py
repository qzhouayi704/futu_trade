#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""因果回测：前一交易日资金线索与次日低位资金确认。"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import sqlite3
import sys
from typing import Sequence

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import big_order_flow_eval as flow  # noqa: E402
import daily_position_flow_backtest as daily  # noqa: E402
import low_position_accumulation_grid as grid  # noqa: E402


ROUND_TRIP_COST = 0.0025
PRIOR_SPEC = grid.FlowSpec(60, 3.0, 1.0, 0.65, 3, 10)
TRIGGER_SPEC = grid.FlowSpec(15, 2.5, 1.0, 0.70, 2, 5)
PRIOR_SPECS = tuple(
    grid.FlowSpec(60, threshold, scale, ratio, count, span)
    for threshold in (2.0, 3.0, 4.0)
    for scale in (1.0, 1.25)
    for ratio in (0.60, 0.65, 0.75)
    for count, span in ((2, 5), (3, 10), (4, 15))
)
TRIGGER_SPECS = tuple(
    grid.FlowSpec(15, threshold, scale, ratio, count, span)
    for threshold in (2.0, 2.5, 3.0)
    for scale in (1.0, 1.25)
    for ratio in (0.65, 0.70, 0.75)
    for count, span in ((2, 5), (3, 10))
)


def finite(item, field: str) -> float | None:
    try:
        value = float(getattr(item, field))
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def passes_prior(event) -> bool:
    position = finite(event, "pos20")
    extension = finite(event, "extension_atr")
    breadth = finite(event, "breadth")
    vwap = finite(event, "confirm_vwap_distance")
    day_change = finite(event, "day_change")
    return bool(
        position is not None
        and position <= 0.70
        and extension is not None
        and extension <= 1.75
        and breadth is not None
        and breadth >= 0.40
        and vwap is not None
        and vwap >= -0.01
        and day_change is not None
        and day_change <= 0.10
    )


def passes_trigger(event) -> bool:
    position = finite(event, "pos20")
    extension = finite(event, "extension_atr")
    breadth = finite(event, "breadth")
    vwap = finite(event, "confirm_vwap_distance")
    day_change = finite(event, "day_change")
    drawdown = finite(event, "confirm_drawdown")
    return bool(
        event.index <= flow.IDX["11:30"]
        and position is not None
        and position <= 0.80
        and extension is not None
        and extension <= 1.75
        and breadth is not None
        and breadth >= 0.45
        and vwap is not None
        and -0.005 <= vwap <= 0.015
        and day_change is not None
        and -0.04 <= day_change <= 0.06
        and drawdown is not None
        and drawdown >= -0.03
    )


def first_by_stock_day(events: Sequence, predicate) -> dict[tuple[str, str], object]:
    selected = {}
    for event in sorted(events, key=lambda item: (item.day, item.code, item.index)):
        if predicate(event):
            selected.setdefault((event.code, event.day), event)
    return selected


def pair_events(
    prior_events: Sequence,
    trigger_events: Sequence,
    ordered_days: Sequence[str],
) -> list[tuple[object, object]]:
    previous_day = {
        ordered_days[index]: ordered_days[index - 1]
        for index in range(1, len(ordered_days))
    }
    priors = first_by_stock_day(prior_events, passes_prior)
    triggers = first_by_stock_day(trigger_events, passes_trigger)
    pairs = []
    for (code, day), trigger in triggers.items():
        prior_day = previous_day.get(day)
        prior = priors.get((code, prior_day)) if prior_day else None
        if prior is not None:
            pairs.append((prior, trigger))
    return sorted(pairs, key=lambda item: (item[1].day, item[1].code, item[1].index))


def summarize(events: Sequence) -> dict | None:
    if not events:
        return None
    eod = np.asarray([event.eod - ROUND_TRIP_COST for event in events], dtype=float)
    mfe = np.asarray([event.mfe_eod for event in events], dtype=float)
    mae = np.asarray([event.mae60 for event in events], dtype=float)
    by_day: dict[str, list[float]] = defaultdict(list)
    for event, value in zip(events, eod):
        by_day[event.day].append(float(value))
    day_returns = np.asarray([np.mean(values) for values in by_day.values()])
    bins = (
        ("<0%", mfe < 0),
        ("0~1.5%", (mfe >= 0) & (mfe < 0.015)),
        ("1.5~3%", (mfe >= 0.015) & (mfe < 0.03)),
        ("3~5%", (mfe >= 0.03) & (mfe < 0.05)),
        (">=5%", mfe >= 0.05),
    )
    return {
        "n": len(events),
        "days": len(by_day),
        "stocks": len({event.code for event in events}),
        "net_eod_mean": float(eod.mean()),
        "net_eod_median": float(np.median(eod)),
        "win_ratio": float((eod > 0).mean()),
        "positive_days": float((day_returns > 0).mean()),
        "day_mean": float(day_returns.mean()),
        "mfe_median": float(np.median(mfe)),
        "mae60_median": float(np.median(mae)),
        "mae60_le_minus2": float((mae <= -0.02).mean()),
        "reached_1_5": float((mfe >= 0.015).mean()),
        "reached_3": float((mfe >= 0.03).mean()),
        "reached_5": float((mfe >= 0.05).mean()),
        "mfe_distribution": {
            label: {"count": int(mask.sum()), "ratio": float(mask.mean())}
            for label, mask in bins
        },
    }


def selection_score(summary: dict) -> float:
    return float(
        summary["day_mean"] * 100
        + summary["reached_1_5"] * 0.25
        + summary["reached_3"] * 0.10
        + summary["positive_days"] * 0.15
        + summary["win_ratio"] * 0.10
        - summary["mae60_le_minus2"] * 0.35
    )


def run(conn: sqlite3.Connection, universe_limit: int) -> dict:
    context = grid.load_context(conn, universe_limit)
    evaluation_days = context["evaluation_days"]
    train_days = set(evaluation_days[:-grid.VALIDATION_DAYS])
    test_days = set(evaluation_days[-grid.VALIDATION_DAYS:])
    selection_end = max(train_days)
    context["universe"] = daily.load_hot_ai_semiconductor_universe(
        conn,
        context["days"][0],
        selection_end,
        universe_limit,
        include_screenshot_codes=False,
    )
    context["allowed"] = {item["code"] for item in context["universe"]}
    specs = tuple(sorted(set(PRIOR_SPECS + TRIGGER_SPECS)))
    events = list(
        grid.iter_events(
            conn,
            context,
            specs,
            exit_choices=(),
        )
    )
    by_flow: dict[str, list] = defaultdict(list)
    for event in events:
        by_flow[event.flow_key].append(event)
    triggers = list(first_by_stock_day(
        by_flow[TRIGGER_SPEC.key], passes_trigger
    ).values())
    pairs = pair_events(
        by_flow[PRIOR_SPEC.key],
        by_flow[TRIGGER_SPEC.key],
        context["days"],
    )
    paired_triggers = [item[1] for item in pairs]
    ranked = []
    for prior_spec in PRIOR_SPECS:
        for trigger_spec in TRIGGER_SPECS:
            candidate_pairs = pair_events(
                by_flow[prior_spec.key],
                by_flow[trigger_spec.key],
                context["days"],
            )
            train_events = [
                item[1] for item in candidate_pairs if item[1].day in train_days
            ]
            train_summary = summarize(train_events)
            if (
                train_summary is None
                or train_summary["n"] < 15
                or train_summary["days"] < 8
            ):
                continue
            ranked.append((
                selection_score(train_summary),
                prior_spec,
                trigger_spec,
                train_summary,
                candidate_pairs,
            ))
    ranked.sort(key=lambda item: item[0], reverse=True)
    selected = ranked[0] if ranked else None
    selected_payload = None
    if selected is not None:
        score, prior_spec, trigger_spec, train_summary, selected_pairs = selected
        test_events = [
            item[1] for item in selected_pairs if item[1].day in test_days
        ]
        selected_payload = {
            "selection_score": score,
            "prior_flow": prior_spec.key,
            "trigger_flow": trigger_spec.key,
            "train": train_summary,
            "test": summarize(test_events),
            "test_events": [
                {
                    "stock_code": trigger.code,
                    "prior_day": prior.day,
                    "signal_day": trigger.day,
                    "signal_time": trigger.minute,
                    "signal_price": trigger.price,
                    "mfe_pct": trigger.mfe_eod * 100,
                    "mae60_pct": trigger.mae60 * 100,
                    "eod_net_pct": (trigger.eod - ROUND_TRIP_COST) * 100,
                }
                for prior, trigger in selected_pairs
                if trigger.day in test_days
            ],
        }
    return {
        "meta": {
            "days": len(context["days"]),
            "train_range": [min(train_days), max(train_days)],
            "test_range": [min(test_days), max(test_days)],
            "universe_size": len(context["universe"]),
            "prior_flow": PRIOR_SPEC.key,
            "trigger_flow": TRIGGER_SPEC.key,
            "searched_combinations": len(PRIOR_SPECS) * len(TRIGGER_SPECS),
        },
        "baseline": {
            "train": summarize([item for item in triggers if item.day in train_days]),
            "test": summarize([item for item in triggers if item.day in test_days]),
        },
        "overnight_priority": {
            "train": summarize([item for item in paired_triggers if item.day in train_days]),
            "test": summarize([item for item in paired_triggers if item.day in test_days]),
            "test_events": [
                {
                    "stock_code": trigger.code,
                    "prior_day": prior.day,
                    "signal_day": trigger.day,
                    "signal_time": trigger.minute,
                    "signal_price": trigger.price,
                    "mfe_pct": trigger.mfe_eod * 100,
                    "mae60_pct": trigger.mae60 * 100,
                    "eod_net_pct": (trigger.eod - ROUND_TRIP_COST) * 100,
                }
                for prior, trigger in pairs
                if trigger.day in test_days
            ],
        },
        "selected": selected_payload,
        "note": (
            "研究回测使用日线位置、VWAP和逐笔资金的因果分钟值；生产规则额外检查"
            "前日尾盘流出、当日资金记忆和日内区间位置，因此生产信号会更少。"
        ),
    }


def render(payload: dict) -> str:
    def pct(value):
        return "--" if value is None else f"{value * 100:.2f}%"

    lines = [
        "# 跨日优先池与次日低位确认回测",
        "",
        f"- 训练区间：{payload['meta']['train_range'][0]} 至 {payload['meta']['train_range'][1]}",
        f"- 盲测区间：{payload['meta']['test_range'][0]} 至 {payload['meta']['test_range'][1]}",
        f"- 热门 AI/半导体股票：{payload['meta']['universe_size']} 只",
        "",
        "| 方案 | 样本 | 收盘净收益 | 胜率 | 达1.5% | 达3% | 达5% | 60分钟亏2% |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, label in (("baseline", "仅当日低位确认"), ("overnight_priority", "前日优先+次日确认")):
        item = payload[key]["test"] or {}
        lines.append(
            f"| {label} | {item.get('n', 0)} | {pct(item.get('net_eod_mean'))} | "
            f"{pct(item.get('win_ratio'))} | {pct(item.get('reached_1_5'))} | "
            f"{pct(item.get('reached_3'))} | {pct(item.get('reached_5'))} | "
            f"{pct(item.get('mae60_le_minus2'))} |"
        )
    selected = payload.get("selected") or {}
    selected_test = selected.get("test") or {}
    lines.extend((
        "",
        f"- 有限搜索组合：{payload['meta']['searched_combinations']} 组（仅用训练期排序）",
        f"- 训练期选中前日条件：`{selected.get('prior_flow', '--')}`",
        f"- 训练期选中次日条件：`{selected.get('trigger_flow', '--')}`",
        f"- 选中配置盲测：{selected_test.get('n', 0)} 个样本，"
        f"收盘净收益 {pct(selected_test.get('net_eod_mean'))}，"
        f"达1.5% {pct(selected_test.get('reached_1_5'))}，"
        f"60分钟亏2% {pct(selected_test.get('mae60_le_minus2'))}",
    ))
    lines.extend(("", payload["note"], ""))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--universe-limit", type=int, default=40)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    conn = sqlite3.connect(args.db, uri=args.db.startswith("file:"))
    try:
        payload = run(conn, max(1, args.universe_limit))
    finally:
        conn.close()
    report = render(payload)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
