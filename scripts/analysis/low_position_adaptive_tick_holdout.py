#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Raw-tick holdout validation for structural accumulation exits."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
import sys

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1] if len(SCRIPT_DIR.parents) > 1 else None
for path in (SCRIPT_DIR, PROJECT_ROOT):
    if path is not None and str(path) not in sys.path:
        sys.path.insert(0, str(path))

import big_order_flow_eval as flow  # noqa: E402
import daily_position_flow_backtest as daily  # noqa: E402
import low_position_accumulation_grid as grid  # noqa: E402
import low_position_adaptive_exit as adaptive  # noqa: E402
import low_position_tick_holdout as tick_holdout  # noqa: E402
from simple_trade.v2.application.features.capital_windows import (  # noqa: E402
    CapitalWindowEngine,
)
from simple_trade.v2.domain.enums import DataQuality, TickDirection  # noqa: E402
from simple_trade.v2.domain.features import CapitalBaseline  # noqa: E402
from simple_trade.v2.domain.market import TickTrade  # noqa: E402


@dataclass
class RuntimeState:
    spec: adaptive.AdaptiveExitSpec
    peak: float
    profit_ready: bool = False
    below_vwap_minutes: int = 0
    minute_index: int | None = None
    minute_below_vwap: bool = False
    exit_price: float | None = None
    exit_reason: str = "EOD"


def selected_specs(payload: dict, limit: int) -> list[adaptive.AdaptiveExitSpec]:
    specs: list[adaptive.AdaptiveExitSpec] = []
    seen: set[str] = set()
    for row in payload.get("final_top", []):
        spec = adaptive.AdaptiveExitSpec(**row["exit"])
        if spec.key in seen:
            continue
        seen.add(spec.key)
        specs.append(spec)
        if len(specs) >= limit:
            break
    return specs


def exact_outflow_confirmed(
    moments: list[datetime], now: datetime, event_count: int, min_span: int
) -> bool:
    cutoff = now - timedelta(minutes=15)
    recent = [item for item in moments if item >= cutoff]
    return bool(
        len(recent) >= event_count
        and (recent[-1] - recent[-event_count]).total_seconds() >= min_span * 60
    )


def _commit_completed_minute(state: RuntimeState, index: int) -> None:
    if state.minute_index is None:
        state.minute_index = index
        return
    if index == state.minute_index:
        return
    state.below_vwap_minutes = (
        state.below_vwap_minutes + 1 if state.minute_below_vwap else 0
    )
    state.minute_index = index
    state.minute_below_vwap = False


def replay_stock(
    ticks: list[TickTrade],
    *,
    code: str,
    day: str,
    specs: list[adaptive.AdaptiveExitSpec],
    threshold: float,
    scale: float,
    bars: dict,
    breadth: np.ndarray,
) -> grid.Event | None:
    flow_spec = adaptive.FLOW_SPEC
    overlay = adaptive.OVERLAY
    engine = CapitalWindowEngine(
        windows=(flow_spec.window * 60,), large_order_threshold=threshold
    )
    engine.set_baselines(
        (
            CapitalBaseline(
                stock_code=code,
                large_order_threshold=threshold,
                flow_scale=scale,
                quality=DataQuality.GOOD,
            ),
        )
    )
    cumulative_turnover = 0.0
    cumulative_volume = 0
    trigger: dict | None = None
    states: dict[str, RuntimeState] = {}
    outflow_times: list[datetime] = []
    last_support_index = 0
    peak = low = peak60 = low60 = 0.0
    first_1_5: int | None = None
    last_price: float | None = None

    for row_index, tick in enumerate(ticks):
        last_price = tick.price
        cumulative_turnover += tick.turnover or tick.price * tick.volume
        cumulative_volume += tick.volume
        update = engine.on_tick(tick)

        if trigger is None:
            if not (
                update.accepted
                and update.is_large_order
                and update.is_independent_event
                and tick.direction is TickDirection.BUY
            ):
                continue
            aggregate = engine.snapshots(code, tick.exchange_time)[0]
            if not tick_holdout.qualifies_snapshot(
                aggregate, flow_spec, threshold, scale
            ):
                continue
            index = tick_holdout.trading_index(tick.exchange_time)
            feature = daily.daily_feature(code, day, tick.price, bars)
            if feature is None:
                continue
            breadth_value = (
                float(breadth[index]) if np.isfinite(breadth[index]) else None
            )
            vwap = cumulative_turnover / cumulative_volume if cumulative_volume else None
            vwap_distance = tick.price / vwap - 1.0 if vwap else None
            if not tick_holdout.passes_tick_overlay(
                position=float(feature.pos20),
                breadth=breadth_value,
                vwap_distance=vwap_distance,
                index=index,
                overlay=overlay,
            ):
                continue
            first_buy = aggregate.first_independent_buy_at or tick.exchange_time
            confirmation_low = min(
                item.price
                for item in ticks[: row_index + 1]
                if item.exchange_time >= first_buy
            )
            trigger = {
                "row_index": row_index,
                "index": index,
                "time": tick.exchange_time,
                "price": tick.price,
                "pos20": float(feature.pos20),
                "breadth": breadth_value,
                "vwap_distance": vwap_distance,
                "confirmation_low": confirmation_low,
            }
            states = {
                spec.key: RuntimeState(spec=spec, peak=tick.price, minute_index=index)
                for spec in specs
            }
            last_support_index = index
            peak = low = peak60 = low60 = tick.price
            continue

        aggregate = engine.snapshots(code, tick.exchange_time)[0]
        index = tick_holdout.trading_index(tick.exchange_time)
        elapsed = max(0, index - trigger["index"])
        peak = max(peak, tick.price)
        low = min(low, tick.price)
        if elapsed <= 60:
            peak60 = max(peak60, tick.price)
            low60 = min(low60, tick.price)
        if first_1_5 is None and tick.price >= trigger["price"] * 1.015:
            first_1_5 = elapsed

        if update.is_independent_event and tick.direction is TickDirection.BUY:
            if aggregate.main_net > 0 and (aggregate.buy_sell_ratio or 0.0) >= 0.60:
                last_support_index = index
        if update.is_independent_event and tick.direction is TickDirection.SELL:
            if aggregate.main_net <= -threshold:
                outflow_times.append(tick.exchange_time)

        vwap = cumulative_turnover / cumulative_volume if cumulative_volume else None
        for state in states.values():
            if state.exit_price is not None:
                continue
            spec = state.spec
            _commit_completed_minute(state, index)
            below_vwap = bool(
                vwap is not None
                and tick.price < vwap * (1.0 - spec.vwap_tolerance)
            )
            state.minute_below_vwap = below_vwap
            state.peak = max(state.peak, tick.price)
            state.profit_ready = (
                state.profit_ready or state.peak >= trigger["price"] * 1.015
            )
            fresh_support = index - last_support_index <= spec.support_grace
            structure_broken = tick.price < trigger["confirmation_low"] * 0.997
            flow_broken = exact_outflow_confirmed(
                outflow_times,
                tick.exchange_time,
                spec.outflow_events,
                spec.outflow_span,
            )
            reason = None
            if tick.price <= trigger["price"] * (1.0 - spec.hard_stop):
                reason = "HARD_STOP"
            elif structure_broken and flow_broken:
                reason = "STRUCTURE_AND_OUTFLOW"
            elif (
                state.profit_ready
                and spec.take_profit is not None
                and tick.price >= trigger["price"] * (1.0 + spec.take_profit)
            ):
                reason = "TAKE_PROFIT"
            elif (
                state.profit_ready
                and not fresh_support
                and state.below_vwap_minutes >= spec.vwap_break_minutes
            ):
                reason = "VWAP_SUPPORT_LOST"
            elif (
                state.profit_ready
                and not fresh_support
                and state.peak >= trigger["price"] * (1.0 + spec.trail_activation)
                and tick.price <= state.peak * (1.0 - spec.trail_pullback)
            ):
                reason = "TRAIL_AFTER_SUPPORT_LOST"
            elif (
                state.profit_ready
                and not fresh_support
                and tick.price <= trigger["price"] * (1.0 + spec.profit_floor)
            ):
                reason = "PROFIT_FLOOR"
            if reason is not None:
                state.exit_price = tick.price
                state.exit_reason = reason

    if trigger is None or last_price is None:
        return None
    exits = {}
    reasons = {}
    for key, state in states.items():
        exit_price = state.exit_price if state.exit_price is not None else last_price
        exits[key] = exit_price / trigger["price"] - 1.0 - grid.ROUND_TRIP_COST
        reasons[key] = state.exit_reason
    event = grid.Event(
        flow_key=flow_spec.key,
        code=code,
        day=day,
        minute=trigger["time"].strftime("%H:%M:%S"),
        index=trigger["index"],
        watch_index=trigger["index"],
        price=trigger["price"],
        pos20=trigger["pos20"],
        breadth=trigger["breadth"],
        return_from_watch=0.0,
        confirm_vwap_distance=trigger["vwap_distance"],
        confirm_drawdown=0.0,
        watch_min_vwap_distance=trigger["vwap_distance"],
        watch_max_drawdown=0.0,
        mfe60=peak60 / trigger["price"] - 1.0,
        mae60=low60 / trigger["price"] - 1.0,
        mfe_eod=peak / trigger["price"] - 1.0,
        mae_eod=low / trigger["price"] - 1.0,
        eod=last_price / trigger["price"] - 1.0,
        time_to_1_5=first_1_5,
        exits=exits,
    )
    event.adaptive_exit_reasons = reasons
    return event


def summarize(events: list[grid.Event], spec: adaptive.AdaptiveExitSpec) -> dict | None:
    metrics = adaptive.ResultMetrics()
    for event in events:
        result = adaptive.EventResult(
            event=event,
            outcomes={
                spec.key: adaptive.AdaptiveOutcome(
                    net_return=event.exits[spec.key],
                    reason=event.adaptive_exit_reasons[spec.key],
                    exit_index=0,
                )
            },
        )
        metrics.add(result, spec)
    return metrics.summary()


def pct(value: float | None) -> str:
    return "--" if value is None else f"{value * 100:+.2f}%"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=flow.DEFAULT_DB)
    parser.add_argument("--adaptive-json", required=True)
    parser.add_argument("--universe-limit", type=int, default=30)
    parser.add_argument("--configs", type=int, default=5)
    parser.add_argument("--days", type=int, default=5)
    parser.add_argument("--json", default="")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    payload = json.loads(Path(args.adaptive_json).read_text(encoding="utf-8"))
    specs = selected_specs(payload, args.configs)
    conn = sqlite3.connect(args.db, uri=True)
    conn.execute("PRAGMA query_only=ON")
    context = grid.load_context(conn, args.universe_limit)
    days = tick_holdout.raw_holdout_days(conn, context, args.days)
    references = tick_holdout.build_references(
        conn, context, {adaptive.FLOW_SPEC.window}
    )
    events: list[grid.Event] = []
    for day in days:
        inputs = tick_holdout.load_day_inputs(conn, context, day)
        ticks_by_code = tick_holdout.load_ticks(conn, day, context["allowed"])
        print(f"结构退出逐笔复核 {day}: {sum(map(len, ticks_by_code.values())):,} 条")
        for code, ticks in ticks_by_code.items():
            reference = references.get((day, code, adaptive.FLOW_SPEC.window))
            if reference is None:
                continue
            event = replay_stock(
                ticks,
                code=code,
                day=day,
                specs=specs,
                threshold=reference[0],
                scale=reference[1],
                bars=context["bars"],
                breadth=inputs["breadth"],
            )
            if event is not None:
                events.append(event)

    results = []
    for index, spec in enumerate(specs, 1):
        summary = summarize(events, spec)
        results.append(
            {
                "name": f"rank_{index}",
                "exit": spec.__dict__,
                "exit_key": spec.key,
                "summary": summary,
                "events": [
                    {
                        "code": event.code,
                        "day": event.day,
                        "time": event.minute,
                        "mfe_eod": event.mfe_eod,
                        "mae_eod": event.mae_eod,
                        "eod": event.eod,
                        "net_return": event.exits[spec.key],
                        "exit_reason": event.adaptive_exit_reasons[spec.key],
                    }
                    for event in events
                ],
            }
        )
        print(
            f"rank_{index}: N={(summary or {}).get('n', 0)}, "
            f"净收益={pct((summary or {}).get('net_mean'))}, "
            f"胜率={(summary or {}).get('win_ratio', 0) * 100:.1f}%, "
            f"P10={pct((summary or {}).get('net_p10'))}"
        )

    output = {
        "method": {
            "engine": "CapitalWindowEngine + adaptive structural exit",
            "round_trip_cost": grid.ROUND_TRIP_COST,
            "read_only": True,
        },
        "days": days,
        "results": results,
    }
    report_lines = [
        "# 结构退出逐笔复核",
        "",
        f"- 完整逐笔交易日：{', '.join(days)}",
        "",
        "| 参数 | N | 净收益 | 胜率 | P10 | ≤-2% |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        summary = result["summary"] or {}
        report_lines.append(
            f"| {result['name']} | {summary.get('n', 0)} | "
            f"{pct(summary.get('net_mean'))} | {summary.get('win_ratio', 0) * 100:.1f}% | "
            f"{pct(summary.get('net_p10'))} | {summary.get('loss_2', 0) * 100:.1f}% |"
        )
    report = "\n".join(report_lines) + "\n"
    if args.json:
        Path(args.json).write_text(
            json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"JSON -> {args.json}")
    if args.report:
        Path(args.report).write_text(report, encoding="utf-8")
        print(f"报告 -> {args.report}")


if __name__ == "__main__":
    main()
