#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate low-position accumulation parameters against recent raw ticks.

This is a read-only holdout check. It replays ``ticker_data`` through the V2
capital-window engine so split orders, independent events and sell offsets use
the same semantics as the live system.
"""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1] if len(SCRIPT_DIR.parents) > 1 else None
for path in (SCRIPT_DIR, PROJECT_ROOT):
    if path is None:
        continue
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import big_order_flow_eval as flow  # noqa: E402
import daily_position_flow_backtest as daily  # noqa: E402
import flow_count_breadth_backtest as breadth_bt  # noqa: E402
import low_position_accumulation_grid as grid  # noqa: E402
from simple_trade.v2.application.features.capital_windows import (  # noqa: E402
    CapitalWindowEngine,
)
from simple_trade.v2.domain.enums import DataQuality, TickDirection  # noqa: E402
from simple_trade.v2.domain.features import CapitalBaseline  # noqa: E402
from simple_trade.v2.domain.market import TickTrade  # noqa: E402


HK = timezone(timedelta(hours=8))


def selected_configs(
    payload: dict, limit: int, *, distinct_flow: bool = True
) -> list[dict]:
    """Keep the best rows or distinct flow families, then append the baseline."""
    result: list[dict] = []
    seen: set[str] = set()
    for row in payload.get("final_top", []):
        key = str(row["flow_key"])
        if distinct_flow and key in seen:
            continue
        seen.add(key)
        result.append({"name": f"rank_{len(result) + 1}", **row})
        if len(result) >= limit:
            break
    baseline = payload.get("baseline")
    if baseline:
        result.append({"name": "current_baseline", **baseline})
    return result


def raw_holdout_days(conn: sqlite3.Connection, context: dict, limit: int) -> list[str]:
    counts = dict(
        conn.execute(
            "SELECT trade_date, COUNT(*) FROM ticker_data GROUP BY trade_date"
        ).fetchall()
    )
    complete = [day for day in context["days"] if counts.get(day, 0) > 0]
    return complete[-limit:]


def build_references(
    conn: sqlite3.Connection,
    context: dict,
    windows: set[int],
) -> dict[tuple[str, str, int], tuple[float, float]]:
    """Build causal threshold/scale references before each signal day."""
    histories = defaultdict(lambda: deque(maxlen=grid.CALIBRATION_DAYS))
    references: dict[tuple[str, str, int], tuple[float, float]] = {}
    for day in context["days"]:
        records = flow.load_day(conn, day)
        for code, record in records.items():
            if code not in context["allowed"]:
                continue
            threshold = float(record.get("thr") or 0.0)
            if threshold <= 0:
                continue
            capital = grid.capital_windows(record, windows)
            active = (record["cb"] + record["cs"]) > 0
            for window in windows:
                scale = grid.window_bt.causal_scale(histories[(code, window)], threshold)
                if scale is not None:
                    references[(day, code, window)] = (threshold, float(scale))
                sample = np.abs(capital[window]["net"][active])
                sample = sample[np.isfinite(sample)]
                if len(sample):
                    histories[(code, window)].append(sample)
    return references


def load_day_inputs(conn: sqlite3.Connection, context: dict, day: str) -> dict:
    records = flow.load_day(conn, day)
    derived = {
        code: flow.derive(record, code, day, context["next_close"])
        for code, record in records.items()
    }
    breadth, _counts = breadth_bt.build_breadth(
        records, derived, day, context["previous_close"]
    )
    return {"records": records, "derived": derived, "breadth": breadth}


def load_ticks(
    conn: sqlite3.Connection,
    day: str,
    allowed: set[str],
) -> dict[str, list[TickTrade]]:
    if not allowed:
        return {}
    placeholders = ",".join("?" for _ in allowed)
    rows = conn.execute(
        "SELECT stock_code, price, volume, turnover, direction, timestamp "
        f"FROM ticker_data WHERE trade_date=? AND stock_code IN ({placeholders}) "
        "ORDER BY stock_code, timestamp, id",
        (day, *sorted(allowed)),
    ).fetchall()
    grouped: dict[str, list[TickTrade]] = defaultdict(list)
    for code, price, volume, turnover, direction, timestamp_ms in rows:
        try:
            side = TickDirection(str(direction).upper())
            price_value = float(price)
            volume_value = int(volume)
            turnover_value = float(turnover or price_value * volume_value)
            if price_value <= 0 or volume_value <= 0 or turnover_value < 0:
                continue
            grouped[str(code)].append(
                TickTrade(
                    stock_code=str(code),
                    exchange_time=datetime.fromtimestamp(float(timestamp_ms) / 1000.0, HK),
                    price=price_value,
                    volume=volume_value,
                    turnover=turnover_value,
                    direction=side,
                    # Production recovery deliberately ignores unstable Futu sequences.
                    sequence=None,
                    quality=DataQuality.GOOD,
                )
            )
        except (TypeError, ValueError):
            continue
    return grouped


def trading_index(moment: datetime) -> int:
    minute = flow.clip_minute(moment.strftime("%H:%M"))
    return flow.IDX[minute]


def qualifies_snapshot(aggregate, spec: grid.FlowSpec, threshold: float, scale: float) -> bool:
    first = aggregate.first_independent_buy_at
    last = aggregate.last_independent_buy_at
    span_seconds = (last - first).total_seconds() if first and last else 0.0
    return bool(
        aggregate.independent_buy_events >= spec.event_count
        and span_seconds >= spec.min_span * 60
        and aggregate.main_net >= spec.threshold_mult * threshold
        and aggregate.main_net >= spec.scale_mult * scale
        and aggregate.buy_sell_ratio is not None
        and aggregate.buy_sell_ratio >= spec.buy_ratio
    )


def passes_tick_overlay(
    *,
    position: float,
    breadth: float | None,
    vwap_distance: float | None,
    index: int,
    overlay: grid.OverlaySpec,
) -> bool:
    vwap_floor, _ = grid.acceptance_limits(overlay.acceptance)
    return bool(
        position <= overlay.position_max
        and (
            overlay.latest_minute is None
            or index <= flow.IDX[overlay.latest_minute]
        )
        and (
            overlay.breadth_min is None
            or (breadth is not None and breadth >= overlay.breadth_min)
        )
        and vwap_distance is not None
        and vwap_distance >= vwap_floor
    )


def replay_stock(
    ticks: list[TickTrade],
    *,
    code: str,
    day: str,
    config: dict,
    threshold: float,
    scale: float,
    bars: dict,
    breadth: np.ndarray,
) -> grid.Event | None:
    spec = grid.FlowSpec(**config["flow"])
    overlay = grid.OverlaySpec(**config["overlay"])
    exit_spec = grid.ExitSpec(**config["exit"])
    engine = CapitalWindowEngine(
        windows=(spec.window * 60,), large_order_threshold=threshold
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
    peak = low = 0.0
    peak60 = low60 = 0.0
    exit_price: float | None = None
    first_1_5: int | None = None
    last_price: float | None = None
    outflow_times: list[datetime] = []

    for row_index, tick in enumerate(ticks):
        last_price = tick.price
        cumulative_turnover += tick.turnover or tick.price * tick.volume
        cumulative_volume += tick.volume
        update = engine.on_tick(tick)
        aggregate = None

        if trigger is not None:
            aggregate = engine.snapshots(code, tick.exchange_time)[0]
            if update.is_independent_event and tick.direction is TickDirection.SELL:
                outflow_times.append(tick.exchange_time)
            cutoff = tick.exchange_time - timedelta(minutes=spec.window)
            outflow_times = [item for item in outflow_times if item >= cutoff]
            price = tick.price
            peak = max(peak, price)
            low = min(low, price)
            current_index = trading_index(tick.exchange_time)
            elapsed_minutes = max(0, current_index - trigger["index"])
            if elapsed_minutes <= 60:
                peak60 = max(peak60, price)
                low60 = min(low60, price)
            if first_1_5 is None and price >= trigger["price"] * 1.015:
                first_1_5 = elapsed_minutes
            if row_index > trigger["row_index"] and exit_price is None:
                confirmed_outflow = False
                if (
                    exit_spec.outflow_events > 0
                    and len(outflow_times) >= exit_spec.outflow_events
                ):
                    selected = outflow_times[-exit_spec.outflow_events :]
                    confirmed_outflow = bool(
                        (selected[-1] - selected[0]).total_seconds()
                        >= exit_spec.outflow_span * 60
                    )
                outflow = bool(
                    aggregate.main_net <= -threshold
                    and confirmed_outflow
                )
                stopped = price <= trigger["price"] * (1.0 - exit_spec.stop_loss)
                trailing = (
                    peak >= trigger["price"] * (1.0 + exit_spec.trail_activation)
                    and price <= peak * (1.0 - exit_spec.trail_pullback)
                )
                took_profit = (
                    exit_spec.take_profit is not None
                    and price >= trigger["price"] * (1.0 + exit_spec.take_profit)
                )
                if outflow or stopped or trailing or took_profit:
                    exit_price = price
            continue

        if not (
            update.accepted
            and update.is_large_order
            and update.is_independent_event
            and tick.direction is TickDirection.BUY
        ):
            continue
        aggregate = engine.snapshots(code, tick.exchange_time)[0]
        if not qualifies_snapshot(aggregate, spec, threshold, scale):
            continue
        index = trading_index(tick.exchange_time)
        feature = daily.daily_feature(code, day, tick.price, bars)
        if feature is None:
            continue
        breadth_value = float(breadth[index]) if np.isfinite(breadth[index]) else None
        vwap = cumulative_turnover / cumulative_volume if cumulative_volume > 0 else None
        vwap_distance = tick.price / vwap - 1.0 if vwap is not None else None
        if not passes_tick_overlay(
            position=float(feature.pos20),
            breadth=breadth_value,
            vwap_distance=vwap_distance,
            index=index,
            overlay=overlay,
        ):
            continue
        trigger = {
            "row_index": row_index,
            "index": index,
            "time": tick.exchange_time,
            "price": tick.price,
            "pos20": float(feature.pos20),
            "breadth": breadth_value,
            "vwap_distance": vwap_distance,
        }
        peak = low = peak60 = low60 = tick.price

    if trigger is None or last_price is None:
        return None
    realized_exit = exit_price if exit_price is not None else last_price
    entry = float(trigger["price"])
    return grid.Event(
        flow_key=spec.key,
        code=code,
        day=day,
        minute=trigger["time"].strftime("%H:%M:%S"),
        index=int(trigger["index"]),
        watch_index=int(trigger["index"]),
        price=entry,
        pos20=float(trigger["pos20"]),
        breadth=trigger["breadth"],
        return_from_watch=0.0,
        confirm_vwap_distance=float(trigger["vwap_distance"]),
        confirm_drawdown=0.0,
        watch_min_vwap_distance=float(trigger["vwap_distance"]),
        watch_max_drawdown=0.0,
        mfe60=peak60 / entry - 1.0,
        mae60=low60 / entry - 1.0,
        mfe_eod=peak / entry - 1.0,
        mae_eod=low / entry - 1.0,
        eod=last_price / entry - 1.0,
        time_to_1_5=first_1_5,
        exits={exit_spec.key: realized_exit / entry - 1.0 - grid.ROUND_TRIP_COST},
    )


def summarize(events: list[grid.Event], exit_spec: grid.ExitSpec) -> dict | None:
    metrics = grid.Metrics()
    for event in events:
        metrics.add(event, event.exits[exit_spec.key])
    return metrics.summary()


def pct(value: float | None) -> str:
    return "--" if value is None else f"{value * 100:+.2f}%"


def build_report(payload: dict) -> str:
    lines = [
        "# 低位多次资金吸收逐笔复核",
        "",
        f"- 完整逐笔交易日：{', '.join(payload['days'])}",
        "- 逐笔按生产引擎合并3秒内同向拆单；Futu不稳定sequence不参与去重。",
        "- 收益包含0.25%往返成本；卖点依次响应净流出、止损和盈利后回撤。",
        "",
        "| 参数 | 信号N/天数 | 净收益 | 胜率 | ≥1.5% | ≥3% | MFE60 | MAE60 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in payload["results"]:
        summary = result["summary"] or {}
        lines.append(
            f"| {result['name']} `{result['flow_key']}` | "
            f"{summary.get('n', 0)}/{summary.get('days', 0)} | "
            f"{pct(summary.get('net_mean'))} | {summary.get('win_ratio', 0) * 100:.1f}% | "
            f"{summary.get('reached_1_5', 0) * 100:.1f}% | "
            f"{summary.get('reached_3', 0) * 100:.1f}% | "
            f"{pct(summary.get('mfe60_median'))} | {pct(summary.get('mae60_median'))} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=flow.DEFAULT_DB)
    parser.add_argument("--grid-json", required=True)
    parser.add_argument("--universe-limit", type=int, default=30)
    parser.add_argument("--families", type=int, default=3)
    parser.add_argument(
        "--selection-mode", choices=("distinct-flow", "rows"), default="distinct-flow"
    )
    parser.add_argument("--days", type=int, default=5)
    parser.add_argument("--take-profit-override", type=float, default=None)
    parser.add_argument("--json", default="")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    grid_payload = json.loads(Path(args.grid_json).read_text(encoding="utf-8"))
    configs = selected_configs(
        grid_payload,
        args.families,
        distinct_flow=args.selection_mode == "distinct-flow",
    )
    if args.take_profit_override is not None:
        for config in configs:
            if config["name"] != "current_baseline":
                config["exit"] = {
                    **config["exit"],
                    "take_profit": args.take_profit_override,
                }
    conn = sqlite3.connect(args.db, uri=True)
    conn.execute("PRAGMA query_only=ON")
    context = grid.load_context(conn, args.universe_limit)
    days = raw_holdout_days(conn, context, args.days)
    windows = {int(item["flow"]["window"]) for item in configs}
    references = build_references(conn, context, windows)
    by_config: dict[str, list[grid.Event]] = {item["name"]: [] for item in configs}

    for day in days:
        inputs = load_day_inputs(conn, context, day)
        ticks_by_code = load_ticks(conn, day, context["allowed"])
        print(f"逐笔复核 {day}: {sum(map(len, ticks_by_code.values())):,} 条")
        for config in configs:
            spec = grid.FlowSpec(**config["flow"])
            for code, ticks in ticks_by_code.items():
                reference = references.get((day, code, spec.window))
                if reference is None:
                    continue
                event = replay_stock(
                    ticks,
                    code=code,
                    day=day,
                    config=config,
                    threshold=reference[0],
                    scale=reference[1],
                    bars=context["bars"],
                    breadth=inputs["breadth"],
                )
                if event is not None:
                    by_config[config["name"]].append(event)

    results = []
    for config in configs:
        exit_spec = grid.ExitSpec(**config["exit"])
        events = by_config[config["name"]]
        result = {
            "name": config["name"],
            "flow_key": config["flow_key"],
            "flow": config["flow"],
            "overlay": config["overlay"],
            "exit": config["exit"],
            "summary": summarize(events, exit_spec),
            "events": [
                {
                    "code": event.code,
                    "day": event.day,
                    "time": event.minute,
                    "price": event.price,
                    "pos20": event.pos20,
                    "breadth": event.breadth,
                    "vwap_distance": event.confirm_vwap_distance,
                    "mfe60": event.mfe60,
                    "mae60": event.mae60,
                    "mfe_eod": event.mfe_eod,
                    "eod": event.eod,
                    "net_return": event.exits[exit_spec.key],
                }
                for event in events
            ],
        }
        results.append(result)
        summary = result["summary"] or {}
        print(
            f"{config['name']}: N={summary.get('n', 0)}, "
            f"净收益={pct(summary.get('net_mean'))}, "
            f"达到1.5%={summary.get('reached_1_5', 0) * 100:.1f}%"
        )

    payload = {
        "method": {
            "engine": "CapitalWindowEngine",
            "round_trip_cost": grid.ROUND_TRIP_COST,
            "sequence": None,
            "read_only": True,
        },
        "days": days,
        "universe": grid_payload.get("universe", []),
        "results": results,
    }
    report = build_report(payload)
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
