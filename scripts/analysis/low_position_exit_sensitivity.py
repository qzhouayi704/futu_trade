#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Focused exit-parameter scan for the validated accumulation entry."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import sys

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import big_order_flow_eval as flow  # noqa: E402
import low_position_accumulation_grid as grid  # noqa: E402


FLOW_SPEC = grid.FlowSpec(15, 3.0, 1.0, 0.65, 3, 10)
OVERLAY = grid.OverlaySpec(0.50, 0.40, "balanced", "11:30")
SENSITIVE_EXIT = grid.ExitSpec(
    stop_loss=0.015,
    trail_pullback=0.0075,
    take_profit=0.015,
    outflow_events=0,
    outflow_span=0,
    trail_activation=0.015,
)


def exit_choices() -> tuple[grid.ExitSpec, ...]:
    choices = {
        grid.ExitSpec(
            stop_loss=stop,
            trail_pullback=pullback,
            take_profit=take_profit,
            outflow_events=outflow_events,
            outflow_span=outflow_span,
            trail_activation=activation,
        )
        for stop in (0.015, 0.02, 0.025, 0.03)
        for activation in (0.02, 0.025, 0.03)
        for pullback in (0.01, 0.0125, 0.015, 0.02)
        for take_profit in (None, 0.03, 0.05)
        for outflow_events, outflow_span in ((0, 0), (3, 5))
    }
    choices.add(SENSITIVE_EXIT)
    return tuple(sorted(choices, key=lambda item: item.key))


def tail_metrics(events: list[grid.Event], days: set[str], exit_spec: grid.ExitSpec) -> dict:
    values = np.asarray(
        [event.exits[exit_spec.key] for event in events if event.day in days], dtype=float
    )
    if not len(values):
        return {"net_p10": None, "net_min": None, "loss_2": None}
    return {
        "net_p10": float(np.quantile(values, 0.10)),
        "net_min": float(values.min()),
        "loss_2": float((values <= -0.02).mean()),
    }


def result_row(
    events: list[grid.Event], context: dict, exit_spec: grid.ExitSpec
) -> dict:
    summary = grid.summarize_split(events, context, OVERLAY, exit_spec)
    train = summary["train"]
    test = summary["test"]
    if train:
        train.update(tail_metrics(events, context["train_days"], exit_spec))
    if test:
        test.update(tail_metrics(events, context["test_days"], exit_spec))
    row = {
        "flow": asdict(FLOW_SPEC),
        "flow_key": FLOW_SPEC.key,
        "overlay": asdict(OVERLAY),
        "overlay_key": OVERLAY.key,
        "exit": asdict(exit_spec),
        "exit_key": exit_spec.key,
        **summary,
    }
    row["combined_score"] = grid.combined_score(row)
    return row


def pct(value: float | None) -> str:
    return "--" if value is None else f"{value * 100:+.2f}%"


def build_report(context: dict, baseline: dict, ranked: list[dict]) -> str:
    lines = [
        "# 低位资金吸收退出敏感度回测",
        "",
        f"- 固定买点：`{FLOW_SPEC.key}`；固定筛选：`{OVERLAY.key}`。",
        f"- 训练 {len(context['train_days'])} 日，样本外 {len(context['test_days'])} 日。",
        "- 只扫描退出参数；资金流出分别测试仅提醒、3次跨5分钟确认。",
        "",
        "| 排名 | 止损 | 回撤启动 | 峰值回撤 | 固定止盈 | 流出 | 训练/测试N | 测试净收益 | 胜率 | P10 | ≤-2% |",
        "|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|",
    ]
    for index, row in enumerate(ranked[:20], 1):
        item = row["exit"]
        test = row["test"] or {}
        outflow = "仅提醒" if item["outflow_events"] == 0 else "3次/5m"
        take = "--" if item["take_profit"] is None else pct(item["take_profit"])
        lines.append(
            f"| {index} | {pct(item['stop_loss'])} | {pct(item['trail_activation'])} | "
            f"{pct(item['trail_pullback'])} | {take} | {outflow} | "
            f"{row['train']['n']}/{test.get('n', 0)} | {pct(test.get('net_mean'))} | "
            f"{test.get('win_ratio', 0) * 100:.1f}% | {pct(test.get('net_p10'))} | "
            f"{test.get('loss_2', 0) * 100:.1f}% |"
        )
    lines.extend(
        [
            "",
            "## 原敏感退出对照",
            "",
            f"- 样本外成本后均值 {pct((baseline.get('test') or {}).get('net_mean'))}，"
            f"胜率 {(baseline.get('test') or {}).get('win_ratio', 0) * 100:.1f}%。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=flow.DEFAULT_DB)
    parser.add_argument("--universe-limit", type=int, default=30)
    parser.add_argument("--json", default="")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db, uri=True)
    conn.execute("PRAGMA query_only=ON")
    context = grid.load_context(conn, args.universe_limit)
    choices = exit_choices()
    events = list(
        grid.iter_events(conn, context, (FLOW_SPEC,), exit_choices=choices)
    )
    rows = [result_row(events, context, item) for item in choices]
    ranked = sorted(rows, key=lambda row: row["combined_score"], reverse=True)
    valid = [row for row in ranked if np.isfinite(row["combined_score"])]
    baseline = next(row for row in rows if row["exit_key"] == SENSITIVE_EXIT.key)

    for index, row in enumerate(valid[:10], 1):
        item = row["exit"]
        test = row["test"]
        print(
            f"{index:2d}. stop={item['stop_loss']:.3f} activate={item['trail_activation']:.3f} "
            f"trail={item['trail_pullback']:.3f} take={item['take_profit']} "
            f"out={item['outflow_events']} test={pct(test['net_mean'])} "
            f"win={test['win_ratio'] * 100:.1f}% p10={pct(test['net_p10'])}"
        )

    payload = {
        "method": {
            "fixed_flow": asdict(FLOW_SPEC),
            "fixed_overlay": asdict(OVERLAY),
            "round_trip_cost": grid.ROUND_TRIP_COST,
            "exit_grid": len(choices),
        },
        "days": context["days"],
        "train_days": sorted(context["train_days"]),
        "test_days": sorted(context["test_days"]),
        "universe": context["universe"],
        "baseline": baseline,
        "final_top": valid[:100],
    }
    report = build_report(context, baseline, valid)
    if args.json:
        Path(args.json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"JSON -> {args.json}")
    if args.report:
        Path(args.report).write_text(report, encoding="utf-8")
        print(f"报告 -> {args.report}")


if __name__ == "__main__":
    main()
