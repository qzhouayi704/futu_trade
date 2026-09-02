#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Causal structural-exit scan for the validated accumulation entry."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path
import sqlite3
import sys
from typing import Iterator

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import big_order_flow_eval as flow  # noqa: E402
import daily_position_flow_backtest as daily  # noqa: E402
import flow_count_breadth_backtest as breadth_bt  # noqa: E402
import low_position_accumulation_grid as grid  # noqa: E402


FLOW_SPEC = grid.FlowSpec(15, 3.0, 1.0, 0.65, 3, 10)
OVERLAY = grid.OverlaySpec(0.50, 0.40, "balanced", "11:30")


@dataclass(frozen=True, order=True)
class AdaptiveExitSpec:
    hard_stop: float
    trail_activation: float
    trail_pullback: float
    vwap_break_minutes: int
    support_grace: int
    profit_floor: float
    take_profit: float | None
    vwap_tolerance: float
    outflow_events: int = 3
    outflow_span: int = 5

    @property
    def key(self) -> str:
        take = "none" if self.take_profit is None else f"{self.take_profit:g}"
        return (
            f"hard{self.hard_stop:g}-activate{self.trail_activation:g}-"
            f"trail{self.trail_pullback:g}-vwap{self.vwap_break_minutes}-"
            f"grace{self.support_grace}-floor{self.profit_floor:g}-take{take}-"
            f"tol{self.vwap_tolerance:g}-out{self.outflow_events}x{self.outflow_span}"
        )


@dataclass(frozen=True)
class AdaptiveOutcome:
    net_return: float
    reason: str
    exit_index: int


@dataclass
class EventResult:
    event: grid.Event
    outcomes: dict[str, AdaptiveOutcome]


@dataclass
class ResultMetrics:
    metrics: grid.Metrics = field(default_factory=grid.Metrics)
    reasons: Counter = field(default_factory=Counter)
    returns: list[float] = field(default_factory=list)

    def add(self, result: EventResult, spec: AdaptiveExitSpec) -> None:
        outcome = result.outcomes[spec.key]
        self.metrics.add(result.event, outcome.net_return)
        self.reasons[outcome.reason] += 1
        self.returns.append(outcome.net_return)

    def summary(self) -> dict | None:
        summary = self.metrics.summary()
        if summary is None:
            return None
        values = np.asarray(self.returns, dtype=float)
        summary.update(
            {
                "net_p10": float(np.quantile(values, 0.10)),
                "net_min": float(values.min()),
                "loss_2": float((values <= -0.02).mean()),
                "exit_reasons": dict(self.reasons),
            }
        )
        return summary


def adaptive_choices() -> tuple[AdaptiveExitSpec, ...]:
    return tuple(
        AdaptiveExitSpec(
            hard_stop=hard_stop,
            trail_activation=activation,
            trail_pullback=pullback,
            vwap_break_minutes=vwap_minutes,
            support_grace=grace,
            profit_floor=floor,
            take_profit=take_profit,
            vwap_tolerance=tolerance,
        )
        for hard_stop in (0.025, 0.03)
        for activation in (0.025, 0.03)
        for pullback in (0.015, 0.02)
        for vwap_minutes in (3, 5)
        for grace in (10, 20)
        for floor in (0.0, 0.005)
        for take_profit in (None, 0.05)
        for tolerance in (0.0, 0.003)
    )


def confirmed_outflow(
    indices: list[int], cursor: int, event_count: int, min_span: int
) -> bool:
    recent = [item for item in indices if cursor - item <= 15]
    return bool(
        len(recent) >= event_count
        and recent[-1] - recent[-event_count] >= min_span
    )


def simulate_adaptive_exit(
    prices: np.ndarray,
    *,
    start: int,
    watch: int,
    vwap: np.ndarray,
    support_indices: list[int],
    outflow_indices: list[int],
    spec: AdaptiveExitSpec,
) -> AdaptiveOutcome:
    entry = float(prices[start])
    confirmation_low = float(np.nanmin(prices[watch : start + 1]))
    peak = entry
    profit_ready = False
    below_vwap_minutes = 0
    last_support = max((item for item in support_indices if item <= start), default=start)
    support_set = set(support_indices)
    exit_price = float(prices[-1])
    exit_index = len(prices) - 1
    reason = "EOD"

    for cursor in range(start + 1, len(prices)):
        price = float(prices[cursor])
        if not np.isfinite(price):
            continue
        if cursor in support_set:
            last_support = cursor
        fresh_support = cursor - last_support <= spec.support_grace
        peak = max(peak, price)
        profit_ready = profit_ready or peak >= entry * 1.015
        current_vwap = float(vwap[cursor]) if np.isfinite(vwap[cursor]) else None
        below_vwap = bool(
            current_vwap is not None
            and price < current_vwap * (1.0 - spec.vwap_tolerance)
        )
        below_vwap_minutes = below_vwap_minutes + 1 if below_vwap else 0
        structure_broken = price < confirmation_low * 0.997
        flow_broken = confirmed_outflow(
            outflow_indices, cursor, spec.outflow_events, spec.outflow_span
        )

        if price <= entry * (1.0 - spec.hard_stop):
            reason = "HARD_STOP"
        elif structure_broken and flow_broken:
            reason = "STRUCTURE_AND_OUTFLOW"
        elif (
            profit_ready
            and spec.take_profit is not None
            and price >= entry * (1.0 + spec.take_profit)
        ):
            reason = "TAKE_PROFIT"
        elif (
            profit_ready
            and not fresh_support
            and below_vwap_minutes >= spec.vwap_break_minutes
        ):
            reason = "VWAP_SUPPORT_LOST"
        elif (
            profit_ready
            and not fresh_support
            and peak >= entry * (1.0 + spec.trail_activation)
            and price <= peak * (1.0 - spec.trail_pullback)
        ):
            reason = "TRAIL_AFTER_SUPPORT_LOST"
        elif (
            profit_ready
            and not fresh_support
            and price <= entry * (1.0 + spec.profit_floor)
        ):
            reason = "PROFIT_FLOOR"
        else:
            continue
        exit_price = price
        exit_index = cursor
        break

    return AdaptiveOutcome(
        net_return=float(exit_price / entry - 1.0 - grid.ROUND_TRIP_COST),
        reason=reason,
        exit_index=exit_index,
    )


def iter_results(
    conn: sqlite3.Connection,
    context: dict,
    choices: tuple[AdaptiveExitSpec, ...],
) -> Iterator[EventResult]:
    histories = defaultdict(lambda: deque(maxlen=grid.CALIBRATION_DAYS))
    bars = context["bars"]
    for day in context["days"]:
        records = flow.load_day(conn, day)
        derived = {
            code: flow.derive(record, code, day, context["next_close"])
            for code, record in records.items()
        }
        breadth, _counts = breadth_bt.build_breadth(
            records, derived, day, context["previous_close"]
        )
        for code, record in records.items():
            if code not in context["allowed"]:
                continue
            base = derived.get(code)
            threshold = float(record.get("thr") or 0.0)
            if base is None or threshold <= 0:
                continue
            capital = grid.capital_windows(record, (FLOW_SPEC.window,))[FLOW_SPEC.window]
            scale = grid.window_bt.causal_scale(
                histories[(code, FLOW_SPEC.window)], threshold
            )
            active = (record["cb"] + record["cs"]) > 0
            if scale is not None:
                total = capital["buy"] + capital["sell"]
                ratio = np.divide(
                    capital["buy"],
                    total,
                    out=np.zeros(len(total), dtype=float),
                    where=total > 0,
                )
                mask = (
                    (capital["net"] >= FLOW_SPEC.threshold_mult * threshold)
                    & (capital["net"] >= FLOW_SPEC.scale_mult * scale)
                    & (ratio >= FLOW_SPEC.buy_ratio)
                    & (record["cb"] > 0)
                    & np.isfinite(base["p"])
                )
                confirmations = grid.sequence.pick_confirmations(mask)
                selected = grid.select_confirmation(
                    confirmations, FLOW_SPEC.event_count, FLOW_SPEC.min_span
                )
                if selected is not None:
                    target, watch = selected
                    feature = daily.daily_feature(
                        code, day, float(base["p"][target]), bars
                    )
                    if feature is not None:
                        event = grid.build_event(
                            FLOW_SPEC,
                            code,
                            day,
                            target,
                            watch,
                            base,
                            record,
                            capital,
                            threshold,
                            feature,
                            breadth,
                            (),
                        )
                        if grid.passes_overlay(event, OVERLAY):
                            vwap = grid.rolling_vwap(record, base["p"])
                            support_mask = (
                                (record["cb"] > 0)
                                & (capital["net"] > 0)
                                & (ratio >= 0.60)
                            )
                            support_indices = grid.sequence.pick_confirmations(support_mask)
                            outflow_mask = (
                                (record["cs"] > 0)
                                & (capital["net"] <= -threshold)
                            )
                            outflow_indices = grid.sequence.pick_confirmations(outflow_mask)
                            outcomes = {
                                item.key: simulate_adaptive_exit(
                                    base["p"],
                                    start=target,
                                    watch=watch,
                                    vwap=vwap,
                                    support_indices=support_indices,
                                    outflow_indices=outflow_indices,
                                    spec=item,
                                )
                                for item in choices
                            }
                            yield EventResult(event=event, outcomes=outcomes)
            sample = np.abs(capital["net"][active])
            sample = sample[np.isfinite(sample)]
            if len(sample):
                histories[(code, FLOW_SPEC.window)].append(sample)


def summarize(
    results: list[EventResult], context: dict, spec: AdaptiveExitSpec
) -> dict:
    train = ResultMetrics()
    test = ResultMetrics()
    for result in results:
        if result.event.day in context["train_days"]:
            train.add(result, spec)
        elif result.event.day in context["test_days"]:
            test.add(result, spec)
    return {"train": train.summary(), "test": test.summary()}


def combined_score(row: dict) -> float:
    base = grid.combined_score(row)
    if not math.isfinite(base):
        return base
    tail_risk = max(row["train"]["loss_2"], row["test"]["loss_2"])
    return float(base - 0.50 * tail_risk)


def pct(value: float | None) -> str:
    return "--" if value is None else f"{value * 100:+.2f}%"


def build_report(context: dict, ranked: list[dict]) -> str:
    lines = [
        "# 低位资金吸收结构退出回测",
        "",
        f"- 固定买点：`{FLOW_SPEC.key}`；固定筛选：`{OVERLAY.key}`。",
        f"- 训练 {len(context['train_days'])} 日，样本外 {len(context['test_days'])} 日。",
        "- +1.5%仅进入利润管理；新流入仍新鲜时不触发VWAP、回撤或利润底线退出。",
        "",
        "| 排名 | 硬止损 | 启动/回撤 | VWAP确认 | 流入保护 | 利润底线 | 止盈 | 测试收益 | 胜率 | P10 | ≤-2% |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for index, row in enumerate(ranked[:20], 1):
        item = row["exit"]
        test = row["test"]
        take = "--" if item["take_profit"] is None else pct(item["take_profit"])
        lines.append(
            f"| {index} | {pct(item['hard_stop'])} | {pct(item['trail_activation'])}/"
            f"{pct(item['trail_pullback'])} | {item['vwap_break_minutes']}m/"
            f"{pct(item['vwap_tolerance'])} | {item['support_grace']}m | "
            f"{pct(item['profit_floor'])} | {take} | {pct(test['net_mean'])} | "
            f"{test['win_ratio'] * 100:.1f}% | {pct(test['net_p10'])} | "
            f"{test['loss_2'] * 100:.1f}% |"
        )
    return "\n".join(lines) + "\n"


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
    choices = adaptive_choices()
    print(f"固定买点，扫描 {len(choices)} 组结构退出参数")
    results = list(iter_results(conn, context, choices))
    rows = []
    for spec in choices:
        row = {
            "flow": asdict(FLOW_SPEC),
            "flow_key": FLOW_SPEC.key,
            "overlay": asdict(OVERLAY),
            "overlay_key": OVERLAY.key,
            "exit": asdict(spec),
            "exit_key": spec.key,
            **summarize(results, context, spec),
        }
        row["combined_score"] = combined_score(row)
        rows.append(row)
    ranked = sorted(rows, key=lambda item: item["combined_score"], reverse=True)
    valid = [row for row in ranked if math.isfinite(row["combined_score"])]
    for index, row in enumerate(valid[:10], 1):
        item = row["exit"]
        test = row["test"]
        print(
            f"{index:2d}. hard={item['hard_stop']:.3f} activate={item['trail_activation']:.3f} "
            f"trail={item['trail_pullback']:.3f} vwap={item['vwap_break_minutes']}m "
            f"grace={item['support_grace']}m floor={item['profit_floor']:.3f} "
            f"take={item['take_profit']} test={pct(test['net_mean'])} "
            f"win={test['win_ratio'] * 100:.1f}% p10={pct(test['net_p10'])}"
        )

    payload = {
        "method": {
            "fixed_flow": asdict(FLOW_SPEC),
            "fixed_overlay": asdict(OVERLAY),
            "round_trip_cost": grid.ROUND_TRIP_COST,
            "adaptive_grid": len(choices),
        },
        "days": context["days"],
        "train_days": sorted(context["train_days"]),
        "test_days": sorted(context["test_days"]),
        "universe": context["universe"],
        "final_top": valid[:100],
    }
    report = build_report(context, valid)
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
