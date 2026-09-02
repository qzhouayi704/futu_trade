#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Low-position repeated-capital-inflow parameter search.

The script is read-only and reuses the production archive reconstruction used by
the existing capital-flow analyses. Daily features and flow scales are causal:
the signal day is excluded from their calibration history.

Production usage:
    .venv/bin/python scripts/analysis/low_position_accumulation_grid.py \
        --db 'file:/data/futu_trade_data/trade.db?mode=ro' \
        --json /tmp/low_position_grid.json \
        --report /tmp/low_position_grid.md
"""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field, replace
import json
import math
from pathlib import Path
import sqlite3
import sys
from typing import Iterable, Iterator, Sequence

import numpy as np


def _analysis_dir() -> Path:
    source = Path(__file__)
    if source.name == "<stdin>":
        return Path.cwd() / "scripts" / "analysis"
    return source.resolve().parent


SCRIPT_DIR = _analysis_dir()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import big_order_flow_eval as flow  # noqa: E402
import capital_flow_sequence_backtest as sequence  # noqa: E402
import capital_window_backtest as window_bt  # noqa: E402
import daily_position_flow_backtest as daily  # noqa: E402
import flow_count_breadth_backtest as breadth_bt  # noqa: E402


WINDOWS = (10, 15, 30, 60)
THRESHOLD_MULTIPLES = (2.0, 3.0, 4.0)
SCALE_MULTIPLES = (1.0, 1.25, 1.5)
BUY_RATIOS = (0.60, 0.65, 0.75)
COUNT_SPANS = ((2, 5), (2, 10), (3, 10), (3, 15), (4, 15), (4, 30))
POSITION_MAXIMA = (0.20, 0.30, 0.35, 0.40, 0.50)
BREADTH_MINIMA = (None, 0.40, 0.45, 0.55)
LATEST_MINUTES = (None, "11:30", "14:30")
STOP_LOSSES = (0.0075, 0.01, 0.015)
TRAIL_PULLBACKS = (0.0075, 0.01)
TAKE_PROFITS = (None, 0.015, 0.025)
OUTFLOW_CONFIRMATIONS = ((0, 0), (2, 3), (3, 5))
ROUND_TRIP_COST = 0.0025
CALIBRATION_DAYS = 5
MIN_CALIBRATION_DAYS = 3
VALIDATION_DAYS = 10
TOP_FLOW_SPECS = 30
MIN_TRAIN_SAMPLES = 30
MIN_TRAIN_DAYS = 10
MIN_TEST_SAMPLES = 10
MIN_TEST_DAYS = 5


@dataclass(frozen=True, order=True)
class FlowSpec:
    window: int
    threshold_mult: float
    scale_mult: float
    buy_ratio: float
    event_count: int
    min_span: int

    @property
    def key(self) -> str:
        return (
            f"w{self.window}-t{self.threshold_mult:g}-s{self.scale_mult:g}-"
            f"r{self.buy_ratio:g}-n{self.event_count}-p{self.min_span}"
        )


@dataclass(frozen=True, order=True)
class OverlaySpec:
    position_max: float
    breadth_min: float | None
    acceptance: str
    latest_minute: str | None = None

    @property
    def key(self) -> str:
        breadth = "any" if self.breadth_min is None else f"{self.breadth_min:g}"
        latest = self.latest_minute or "any"
        return f"pos{self.position_max:g}-breadth{breadth}-{self.acceptance}-until{latest}"


@dataclass(frozen=True, order=True)
class ExitSpec:
    stop_loss: float
    trail_pullback: float
    take_profit: float | None = None
    outflow_events: int = 1
    outflow_span: int = 0
    trail_activation: float = 0.015

    @property
    def key(self) -> str:
        take = "none" if self.take_profit is None else f"{self.take_profit:g}"
        return (
            f"stop{self.stop_loss:g}-trail{self.trail_pullback:g}-take{take}-"
            f"out{self.outflow_events}x{self.outflow_span}-"
            f"activate{self.trail_activation:g}"
        )


@dataclass
class Event:
    flow_key: str
    code: str
    day: str
    minute: str
    index: int
    watch_index: int
    price: float
    pos20: float
    breadth: float | None
    return_from_watch: float
    confirm_vwap_distance: float | None
    confirm_drawdown: float
    watch_min_vwap_distance: float | None
    watch_max_drawdown: float
    mfe60: float
    mae60: float
    mfe_eod: float
    mae_eod: float
    eod: float
    time_to_1_5: int | None
    exits: dict[str, float]
    pos60: float = float("nan")
    extension_atr: float = float("nan")
    prev_ret: float = float("nan")
    day_change: float = float("nan")
    sector_breadth: float | None = None
    relative_strength: float | None = None
    activity_percentile: float | None = None
    flow_net: float = float("nan")
    flow_scale: float = float("nan")
    flow_buy_ratio: float = float("nan")


@dataclass
class Metrics:
    n: int = 0
    stocks: set[str] = field(default_factory=set)
    days: set[str] = field(default_factory=set)
    net_returns: list[float] = field(default_factory=list)
    eod_returns: list[float] = field(default_factory=list)
    mfe60: list[float] = field(default_factory=list)
    mfe_eod: list[float] = field(default_factory=list)
    mae60: list[float] = field(default_factory=list)
    times_1_5: list[int] = field(default_factory=list)
    by_day: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    def add(self, event: Event, net_return: float) -> None:
        self.n += 1
        self.stocks.add(event.code)
        self.days.add(event.day)
        self.net_returns.append(float(net_return))
        self.eod_returns.append(float(event.eod))
        self.mfe60.append(float(event.mfe60))
        self.mfe_eod.append(float(event.mfe_eod))
        self.mae60.append(float(event.mae60))
        if event.time_to_1_5 is not None:
            self.times_1_5.append(int(event.time_to_1_5))
        self.by_day[event.day].append(float(net_return))

    def summary(self) -> dict | None:
        if not self.n:
            return None
        net = np.asarray(self.net_returns, dtype=float)
        eod = np.asarray(self.eod_returns, dtype=float)
        mfe60 = np.asarray(self.mfe60, dtype=float)
        mfe_eod = np.asarray(self.mfe_eod, dtype=float)
        mae60 = np.asarray(self.mae60, dtype=float)
        day_means = np.asarray(
            [np.mean(values) for values in self.by_day.values()], dtype=float
        )
        result = {
            "n": self.n,
            "stocks": len(self.stocks),
            "days": len(self.days),
            "net_mean": float(net.mean()),
            "net_median": float(np.median(net)),
            "win_ratio": float((net > 0).mean()),
            "eod_mean": float(eod.mean()),
            "mfe60_median": float(np.median(mfe60)),
            "mae60_median": float(np.median(mae60)),
            "mae60_le_minus2": float((mae60 <= -0.02).mean()),
            "reached_1_5": float((mfe_eod >= 0.015).mean()),
            "reached_3": float((mfe_eod >= 0.03).mean()),
            "reached_5": float((mfe_eod >= 0.05).mean()),
            "positive_days": float((day_means > 0).mean()),
            "day_mean": float(day_means.mean()),
            "time_to_1_5_median": (
                float(np.median(self.times_1_5)) if self.times_1_5 else None
            ),
        }
        result["score"] = robust_score(result)
        return result


def robust_score(summary: dict) -> float:
    """Day-clustered utility in percentage-point units."""
    return float(
        summary["day_mean"] * 100.0
        + 0.25 * summary["reached_1_5"]
        + 0.10 * summary["reached_3"]
        + 0.20 * summary["positive_days"]
        + 0.10 * summary["win_ratio"]
        - 0.30 * summary["mae60_le_minus2"]
    )


def flow_specs() -> tuple[FlowSpec, ...]:
    return tuple(
        FlowSpec(window, threshold, scale, ratio, count, span)
        for window in WINDOWS
        for threshold in THRESHOLD_MULTIPLES
        for scale in SCALE_MULTIPLES
        for ratio in BUY_RATIOS
        for count, span in COUNT_SPANS
    )


def overlay_specs() -> tuple[OverlaySpec, ...]:
    return tuple(
        OverlaySpec(position, breadth, acceptance, latest)
        for position in POSITION_MAXIMA
        for breadth in BREADTH_MINIMA
        for acceptance in ("above-vwap", "strict", "balanced", "low-watch")
        for latest in LATEST_MINUTES
    )


def exit_specs() -> tuple[ExitSpec, ...]:
    return tuple(
        ExitSpec(stop, pullback, take_profit, outflow_events, outflow_span)
        for stop in STOP_LOSSES
        for pullback in TRAIL_PULLBACKS
        for take_profit in TAKE_PROFITS
        for outflow_events, outflow_span in OUTFLOW_CONFIRMATIONS
    )


def select_confirmation(
    indices: Sequence[int], event_count: int, min_span: int, max_age: int = 60
) -> tuple[int, int] | None:
    """Return the first causal endpoint with enough spaced flow episodes."""
    for position, endpoint in enumerate(indices):
        eligible = [index for index in indices[: position + 1] if endpoint - index <= max_age]
        if len(eligible) < event_count:
            continue
        selected = eligible[-event_count:]
        if selected[-1] - selected[0] >= min_span:
            return int(selected[-1]), int(selected[0])
    return None


def rolling_vwap(record: dict, prices: np.ndarray) -> np.ndarray:
    amount = np.asarray(record["tmb"] + record["tms"], dtype=float)
    valid = np.isfinite(prices) & (prices > 0) & (amount > 0)
    volume = np.zeros(len(prices), dtype=float)
    volume[valid] = amount[valid] / prices[valid]
    cumulative_amount = np.cumsum(amount)
    cumulative_volume = np.cumsum(volume)
    return np.divide(
        cumulative_amount,
        cumulative_volume,
        out=np.full(len(prices), np.nan),
        where=cumulative_volume > 0,
    )


def capital_windows(record: dict, windows: Iterable[int]) -> dict[int, dict]:
    result = {}
    for window in windows:
        buy = window_bt.rolling_sum(record["bb"], window)
        sell = window_bt.rolling_sum(record["bs"], window)
        result[window] = {"buy": buy, "sell": sell, "net": buy - sell}
    return result


def build_universe_intraday_context(
    records: dict[str, dict],
    derived: dict[str, dict],
    day: str,
    previous_close: dict[tuple, float],
    allowed: set[str],
) -> dict[str, dict[str, np.ndarray]]:
    """Build causal hot-universe breadth, relative strength and activity ranks."""
    codes = [
        code
        for code in sorted(allowed)
        if code in records
        and derived.get(code) is not None
        and (previous_close.get((code, day)) or 0.0) > 0
    ]
    if not codes:
        return {}

    returns = []
    cumulative_amounts = []
    valid_prices = []
    for code in codes:
        prices = np.asarray(derived[code]["p"], dtype=float)
        valid = np.isfinite(prices) & (prices > 0)
        previous = float(previous_close[(code, day)])
        returns.append(np.where(valid, prices / previous - 1.0, np.nan))
        amount = np.asarray(records[code]["tmb"] + records[code]["tms"], dtype=float)
        cumulative_amounts.append(np.cumsum(np.maximum(amount, 0.0)))
        valid_prices.append(valid)

    return_matrix = np.asarray(returns, dtype=float)
    amount_matrix = np.asarray(cumulative_amounts, dtype=float)
    valid_matrix = np.asarray(valid_prices, dtype=bool)
    breadth = np.full(flow.NG, np.nan)
    median_return = np.full(flow.NG, np.nan)
    for index in range(flow.NG):
        values = return_matrix[:, index]
        valid = np.isfinite(values)
        if int(valid.sum()) >= 3:
            breadth[index] = float((values[valid] > 0).mean())
            median_return[index] = float(np.median(values[valid]))

    output: dict[str, dict[str, np.ndarray]] = {}
    for row, code in enumerate(codes):
        activity = np.full(flow.NG, np.nan)
        for index in range(flow.NG):
            valid = valid_matrix[:, index] & (amount_matrix[:, index] > 0)
            if valid.sum() < 3 or not valid[row]:
                continue
            activity[index] = float(
                (amount_matrix[valid, index] <= amount_matrix[row, index]).mean()
            )
        output[code] = {
            "sector_breadth": breadth,
            "relative_strength": return_matrix[row] - median_return,
            "activity_percentile": activity,
            "day_change": return_matrix[row],
        }
    return output


def first_target(prices: np.ndarray, start: int, target_return: float) -> int | None:
    target = prices[start] * (1.0 + target_return)
    hits = np.where(prices[start + 1 :] >= target)[0]
    return int(hits[0] + start + 1) if len(hits) else None


def future_extreme(
    prices: np.ndarray, index: int, horizon: int | None, reducer
) -> float:
    end = len(prices) if horizon is None else min(len(prices), index + horizon + 1)
    values = prices[index + 1 : end]
    values = values[np.isfinite(values)]
    return float(reducer(values)) if len(values) else float(prices[index])


def simulate_exit(
    prices: np.ndarray,
    start: int,
    capital: dict,
    threshold: float,
    *,
    stop_loss: float,
    trail_pullback: float,
    take_profit: float | None = None,
    outflow_events: int = 1,
    outflow_span: int = 0,
    trail_activation: float = 0.015,
    sell_events: np.ndarray | None = None,
) -> float:
    entry = float(prices[start])
    peak = entry
    trailing_active = False
    exit_price = float(prices[-1])
    event_mask = capital["net"] <= -threshold
    if sell_events is not None:
        event_mask &= np.asarray(sell_events, dtype=float) > 0
    outflow_indices = set(sequence.pick_confirmations(event_mask))
    outflow_history: list[int] = []
    for index in range(start + 1, len(prices)):
        price = float(prices[index])
        if not np.isfinite(price):
            continue
        peak = max(peak, price)
        trailing_active = trailing_active or peak >= entry * (1.0 + trail_activation)
        buy = float(capital["buy"][index])
        sell = float(capital["sell"][index])
        total = buy + sell
        if index in outflow_indices:
            outflow_history.append(index)
        recent_outflows = [item for item in outflow_history if index - item <= 15]
        outflow = bool(
            outflow_events > 0
            and len(recent_outflows) >= outflow_events
            and recent_outflows[-1] - recent_outflows[-outflow_events] >= outflow_span
        )
        stopped = price <= entry * (1.0 - stop_loss)
        trailed = trailing_active and price <= peak * (1.0 - trail_pullback)
        took_profit = take_profit is not None and price >= entry * (1.0 + take_profit)
        if outflow or stopped or trailed or took_profit:
            exit_price = price
            break
    return float(exit_price / entry - 1.0 - ROUND_TRIP_COST)


def _finite_or_none(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


def build_event(
    spec: FlowSpec,
    code: str,
    day: str,
    target: int,
    watch: int,
    base: dict,
    record: dict,
    capital: dict,
    threshold: float,
    feature: daily.DailyFeature,
    breadth: np.ndarray,
    exit_choices: Sequence[ExitSpec],
    *,
    flow_scale: float = float("nan"),
    universe_context: dict[str, np.ndarray] | None = None,
) -> Event:
    prices = base["p"]
    price = float(prices[target])
    watch_price = float(prices[watch])
    vwap = rolling_vwap(record, prices)
    path = prices[watch : target + 1]
    path_vwap = vwap[watch : target + 1]
    running_peak = np.maximum.accumulate(path)
    drawdowns = path / running_peak - 1.0
    vwap_distances = np.divide(
        path,
        path_vwap,
        out=np.full(len(path), np.nan),
        where=np.isfinite(path_vwap) & (path_vwap > 0),
    ) - 1.0

    high60 = future_extreme(prices, target, 60, np.max)
    low60 = future_extreme(prices, target, 60, np.min)
    high_eod = future_extreme(prices, target, None, np.max)
    low_eod = future_extreme(prices, target, None, np.min)
    target_1_5 = first_target(prices, target, 0.015)
    intraday = universe_context or {}
    capital_total = float(capital["buy"][target] + capital["sell"][target])
    exits = {
        item.key: simulate_exit(
            prices,
            target,
            capital,
            threshold,
            stop_loss=item.stop_loss,
            trail_pullback=item.trail_pullback,
            take_profit=item.take_profit,
            outflow_events=item.outflow_events,
            outflow_span=item.outflow_span,
            trail_activation=item.trail_activation,
            sell_events=record["cs"],
        )
        for item in exit_choices
    }
    return Event(
        flow_key=spec.key,
        code=code,
        day=day,
        minute=flow.GRID[target],
        index=target,
        watch_index=watch,
        price=price,
        pos20=float(feature.pos20),
        breadth=_finite_or_none(breadth[target]),
        return_from_watch=price / watch_price - 1.0,
        confirm_vwap_distance=(
            price / vwap[target] - 1.0 if np.isfinite(vwap[target]) else None
        ),
        confirm_drawdown=float(drawdowns[-1]),
        watch_min_vwap_distance=(
            float(np.nanmin(vwap_distances))
            if np.isfinite(vwap_distances).any()
            else None
        ),
        watch_max_drawdown=float(np.nanmin(drawdowns)),
        mfe60=high60 / price - 1.0,
        mae60=low60 / price - 1.0,
        mfe_eod=high_eod / price - 1.0,
        mae_eod=low_eod / price - 1.0,
        eod=float(prices[-1] / price - 1.0),
        time_to_1_5=(target_1_5 - target if target_1_5 is not None else None),
        exits=exits,
        pos60=float(feature.pos60),
        extension_atr=float(feature.extension_atr),
        prev_ret=float(feature.prev_ret),
        day_change=(
            float(intraday["day_change"][target])
            if "day_change" in intraday
            and np.isfinite(intraday["day_change"][target])
            else float("nan")
        ),
        sector_breadth=(
            _finite_or_none(intraday["sector_breadth"][target])
            if "sector_breadth" in intraday
            else None
        ),
        relative_strength=(
            _finite_or_none(intraday["relative_strength"][target])
            if "relative_strength" in intraday
            else None
        ),
        activity_percentile=(
            _finite_or_none(intraday["activity_percentile"][target])
            if "activity_percentile" in intraday
            else None
        ),
        flow_net=float(capital["net"][target]),
        flow_scale=float(flow_scale),
        flow_buy_ratio=(
            float(capital["buy"][target] / capital_total)
            if capital_total > 0
            else float("nan")
        ),
    )


def acceptance_limits(mode: str) -> tuple[float, float]:
    if mode == "above-vwap":
        return 0.0, -0.01
    if mode == "strict":
        return -0.003, -0.01
    if mode == "balanced":
        return -0.005, -0.015
    if mode == "low-watch":
        return -0.01, -0.02
    raise ValueError(mode)


def passes_overlay(event: Event, overlay: OverlaySpec) -> bool:
    vwap_floor, _drawdown_floor = acceptance_limits(overlay.acceptance)
    return bool(
        event.pos20 <= overlay.position_max
        and (
            overlay.breadth_min is None
            or (event.breadth is not None and event.breadth >= overlay.breadth_min)
        )
        and event.confirm_vwap_distance is not None
        and event.confirm_vwap_distance >= vwap_floor
        and (
            overlay.latest_minute is None
            or event.index <= flow.IDX[overlay.latest_minute]
        )
    )


def current_overlay() -> OverlaySpec:
    return OverlaySpec(
        position_max=0.35,
        breadth_min=None,
        acceptance="strict",
        latest_minute=None,
    )


def current_exit() -> ExitSpec:
    return ExitSpec(
        stop_loss=0.01,
        trail_pullback=0.015,
        take_profit=None,
        outflow_events=1,
        outflow_span=0,
        trail_activation=0.015,
    )


def load_context(conn: sqlite3.Connection, universe_limit: int) -> dict:
    days, dropped = flow.full_days(conn)
    universe = daily.load_hot_ai_semiconductor_universe(
        conn, days[0], days[-1], max(1, universe_limit)
    )
    bars = daily.load_daily_bars(conn)
    next_close = daily.build_next_close(bars)
    previous_close = {
        (code, rows[index].day): rows[index - 1].close
        for code, rows in bars.items()
        for index in range(1, len(rows))
    }
    evaluation_days = days[MIN_CALIBRATION_DAYS:]
    split = max(1, len(evaluation_days) - VALIDATION_DAYS)
    return {
        "days": days,
        "dropped": dropped,
        "universe": universe,
        "allowed": {item["code"] for item in universe},
        "bars": bars,
        "next_close": next_close,
        "previous_close": previous_close,
        "train_days": set(evaluation_days[:split]),
        "test_days": set(evaluation_days[split:]),
        "evaluation_days": evaluation_days,
    }


def iter_events(
    conn: sqlite3.Connection,
    context: dict,
    specs: Sequence[FlowSpec],
    *,
    exit_choices: Sequence[ExitSpec],
) -> Iterator[Event]:
    grouped: dict[int, list[FlowSpec]] = defaultdict(list)
    for spec in specs:
        grouped[spec.window].append(spec)
    histories = defaultdict(lambda: deque(maxlen=CALIBRATION_DAYS))
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
        universe_context = build_universe_intraday_context(
            records,
            derived,
            day,
            context["previous_close"],
            context["allowed"],
        )
        for code, record in records.items():
            if code not in context["allowed"]:
                continue
            base = derived.get(code)
            threshold = float(record.get("thr") or 0.0)
            if base is None or threshold <= 0:
                continue
            windows = capital_windows(record, grouped)
            active = (record["cb"] + record["cs"]) > 0
            scales = {
                window: window_bt.causal_scale(histories[(code, window)], threshold)
                for window in grouped
            }
            event_cache: dict[tuple[int, int, int], Event] = {}
            for window, window_specs in grouped.items():
                scale = scales[window]
                if scale is None:
                    continue
                capital = windows[window]
                total = capital["buy"] + capital["sell"]
                ratio = np.divide(
                    capital["buy"],
                    total,
                    out=np.zeros(len(total), dtype=float),
                    where=total > 0,
                )
                mask_cache: dict[tuple[float, float, float], list[int]] = {}
                for spec in window_specs:
                    base_key = (spec.threshold_mult, spec.scale_mult, spec.buy_ratio)
                    confirmations = mask_cache.get(base_key)
                    if confirmations is None:
                        mask = (
                            (capital["net"] >= spec.threshold_mult * threshold)
                            & (capital["net"] >= spec.scale_mult * scale)
                            & (ratio >= spec.buy_ratio)
                            & (record["cb"] > 0)
                            & np.isfinite(base["p"])
                        )
                        confirmations = sequence.pick_confirmations(mask)
                        mask_cache[base_key] = confirmations
                    selected = select_confirmation(
                        confirmations, spec.event_count, spec.min_span
                    )
                    if selected is None:
                        continue
                    target, watch = selected
                    feature = daily.daily_feature(
                        code, day, float(base["p"][target]), bars
                    )
                    if feature is None:
                        continue
                    cache_key = (window, target, watch)
                    template = event_cache.get(cache_key)
                    if template is None:
                        template = build_event(
                            spec,
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
                            exit_choices,
                            flow_scale=scale,
                            universe_context=universe_context.get(code),
                        )
                        event_cache[cache_key] = template
                    yield replace(template, flow_key=spec.key)
            for window in grouped:
                sample = np.abs(windows[window]["net"][active])
                sample = sample[np.isfinite(sample)]
                if len(sample):
                    histories[(code, window)].append(sample)


def summarize_split(
    events: Iterable[Event],
    context: dict,
    overlay: OverlaySpec,
    exit_spec: ExitSpec,
) -> dict:
    train = Metrics()
    test = Metrics()
    for event in events:
        if not passes_overlay(event, overlay):
            continue
        target = train if event.day in context["train_days"] else test
        if event.day not in context["train_days"] and event.day not in context["test_days"]:
            continue
        target.add(event, event.exits[exit_spec.key])
    return {"train": train.summary(), "test": test.summary()}


def valid_train(summary: dict | None) -> bool:
    return bool(
        summary
        and summary["n"] >= MIN_TRAIN_SAMPLES
        and summary["days"] >= MIN_TRAIN_DAYS
    )


def valid_test(summary: dict | None) -> bool:
    return bool(
        summary
        and summary["n"] >= MIN_TEST_SAMPLES
        and summary["days"] >= MIN_TEST_DAYS
    )


def combined_score(result: dict) -> float:
    train = result.get("train")
    test = result.get("test")
    if not valid_train(train) or not valid_test(test):
        return -math.inf
    difference = abs(train["score"] - test["score"])
    return float(min(train["score"], test["score"]) - 0.25 * difference)


def rank_flow_specs(
    conn: sqlite3.Connection, context: dict, specs: Sequence[FlowSpec]
) -> list[dict]:
    metrics = {
        spec.key: {"train": Metrics(), "test": Metrics()} for spec in specs
    }
    overlay = current_overlay()
    exit_spec = current_exit()
    for event in iter_events(
        conn, context, specs, exit_choices=(current_exit(),)
    ):
        if not passes_overlay(event, overlay):
            continue
        split = (
            "train" if event.day in context["train_days"]
            else "test" if event.day in context["test_days"]
            else None
        )
        if split:
            metrics[event.flow_key][split].add(event, event.exits[exit_spec.key])

    by_key = {spec.key: spec for spec in specs}
    ranked = []
    for key, split_metrics in metrics.items():
        result = {
            "flow": asdict(by_key[key]),
            "flow_key": key,
            "overlay": asdict(overlay),
            "exit": asdict(exit_spec),
            "train": split_metrics["train"].summary(),
            "test": split_metrics["test"].summary(),
        }
        result["combined_score"] = combined_score(result)
        ranked.append(result)
    return sorted(ranked, key=lambda row: row["combined_score"], reverse=True)


def optimize_overlays_and_exits(
    conn: sqlite3.Connection,
    context: dict,
    selected_specs: Sequence[FlowSpec],
) -> tuple[list[dict], dict[str, list[Event]]]:
    events_by_flow: dict[str, list[Event]] = defaultdict(list)
    for event in iter_events(
        conn, context, selected_specs, exit_choices=exit_specs()
    ):
        events_by_flow[event.flow_key].append(event)

    ranked = []
    for spec in selected_specs:
        events = events_by_flow[spec.key]
        for overlay in overlay_specs():
            for exit_spec in exit_specs():
                result = summarize_split(events, context, overlay, exit_spec)
                row = {
                    "flow": asdict(spec),
                    "flow_key": spec.key,
                    "overlay": asdict(overlay),
                    "overlay_key": overlay.key,
                    "exit": asdict(exit_spec),
                    "exit_key": exit_spec.key,
                    **result,
                }
                row["combined_score"] = combined_score(row)
                ranked.append(row)
    return (
        sorted(ranked, key=lambda row: row["combined_score"], reverse=True),
        events_by_flow,
    )


def _pct(value: float | None, digits: int = 2) -> str:
    if value is None or not np.isfinite(value):
        return "--"
    return f"{value * 100:+.{digits}f}%"


def format_row(index: int, row: dict) -> str:
    test = row.get("test") or {}
    train = row.get("train") or {}
    flow_spec = row["flow"]
    overlay = row["overlay"]
    exit_spec = row["exit"]
    take_profit = (
        f"{exit_spec['take_profit'] * 100:.1f}%"
        if exit_spec["take_profit"] is not None
        else "--"
    )
    latest = overlay.get("latest_minute") or "全天"
    outflow = (
        "仅提醒"
        if exit_spec["outflow_events"] == 0
        else f"{exit_spec['outflow_events']}次/{exit_spec['outflow_span']}m"
    )
    activation = f"{exit_spec.get('trail_activation', 0.015) * 100:.1f}%启动"
    return (
        f"| {index} | {flow_spec['window']}m/{flow_spec['event_count']}次/"
        f"{flow_spec['min_span']}m | {flow_spec['threshold_mult']:g}×/"
        f"{flow_spec['scale_mult']:g}×/{flow_spec['buy_ratio'] * 100:.0f}% | "
        f"≤{overlay['position_max'] * 100:.0f}%/"
        f"{overlay['breadth_min'] if overlay['breadth_min'] is not None else '不限'}/"
        f"{overlay['acceptance']}/{latest} | {exit_spec['stop_loss'] * 100:.2f}%/"
        f"{exit_spec['trail_pullback'] * 100:.2f}%/"
        f"{take_profit}/{activation}/{outflow} | "
        f"{train.get('n', 0)}/{test.get('n', 0)} | "
        f"{_pct(test.get('net_mean'))} | {test.get('reached_1_5', 0) * 100:.1f}% | "
        f"{test.get('reached_3', 0) * 100:.1f}% | {_pct(test.get('mae60_median'))} | "
        f"{row['combined_score']:.3f} |"
    )


def build_report(context: dict, baseline: dict | None, ranked: Sequence[dict]) -> str:
    lines = [
        "# 低位多次资金吸收参数回测",
        "",
        "## 数据与方法",
        "",
        f"- 完整交易日：{len(context['days'])}（{context['days'][0]} 至 {context['days'][-1]}）。",
        f"- 因果评估日：{len(context['evaluation_days'])}；训练 {len(context['train_days'])} 日，样本外 {len(context['test_days'])} 日。",
        f"- 热门 AI/半导体股票池：{len(context['universe'])} 只。",
        "- 日线位置不使用信号日K线；资金力度只使用此前最多5个完整日。",
        "- 可执行收益包含0.25%往返成本，并模拟资金翻转、固定止损和1.5%盈利后峰值回撤退出。",
        "- 观察价建立在多次流入条件满足的当前时点；即时确认只检查当时价格相对VWAP的承接。",
        "- 分钟归档将独立流入近似为相隔至少5分钟的强流入片段；最近逐笔数据需另做精确回放复核。",
        "",
        "## 当前参数基线",
        "",
    ]
    if baseline and baseline.get("test"):
        test = baseline["test"]
        lines.extend([
            f"- 样本外 N={test['n']}，成本后均值 {_pct(test['net_mean'])}，胜率 {test['win_ratio'] * 100:.1f}%。",
            f"- 日内达到1.5%：{test['reached_1_5'] * 100:.1f}%；达到3%：{test['reached_3'] * 100:.1f}%。",
            f"- 60分钟 MFE 中位 {_pct(test['mfe60_median'])}，MAE 中位 {_pct(test['mae60_median'])}。",
        ])
    else:
        lines.append("- 当前参数样本不足，无法形成有效基线。")
    lines.extend([
        "",
        "## 稳健参数排名",
        "",
        "| 排名 | 窗口/次数/跨度 | 门槛/力度/买占 | 日线/宽度/承接/时段 | 止损/回撤/止盈/回撤启动/流出确认 | 训练/测试N | 测试净收益 | ≥1.5% | ≥3% | MAE60 | 稳健分 |",
        "|---:|---|---|---|---|---:|---:|---:|---:|---:|---:|",
    ])
    for index, row in enumerate(ranked[:15], 1):
        lines.append(format_row(index, row))
    lines.extend([
        "",
        "## 选择原则",
        "",
        "稳健分取训练与样本外较低者，并惩罚两段差异。它用于参数排序，不代表未来收益保证。",
        "最终上线参数还应通过最近完整逐笔数据的独立事件分组复核，并先以影子模式运行。",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=flow.DEFAULT_DB)
    parser.add_argument("--universe-limit", type=int, default=30)
    parser.add_argument("--top-flow-specs", type=int, default=TOP_FLOW_SPECS)
    parser.add_argument("--json", default="")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db, uri=True)
    conn.execute("PRAGMA query_only=ON")
    context = load_context(conn, args.universe_limit)
    specs = flow_specs()
    print(
        f"[1/2] 粗扫 {len(specs)} 组资金参数；完整日={len(context['days'])}，"
        f"训练={len(context['train_days'])}，样本外={len(context['test_days'])}"
    )
    flow_ranking = rank_flow_specs(conn, context, specs)
    valid_flow = [row for row in flow_ranking if np.isfinite(row["combined_score"])]
    selected_keys = {row["flow_key"] for row in valid_flow[: args.top_flow_specs]}
    selected_specs = [spec for spec in specs if spec.key in selected_keys]
    print(f"[2/2] 对前 {len(selected_specs)} 组扫描日线位置、市场宽度、承接和退出参数")
    final_ranking, events_by_flow = optimize_overlays_and_exits(
        conn, context, selected_specs
    )
    valid_final = [row for row in final_ranking if np.isfinite(row["combined_score"])]

    baseline = next(
        (
            row for row in flow_ranking
            if row["flow"] == asdict(FlowSpec(60, 3.0, 1.25, 0.65, 3, 10))
        ),
        None,
    )
    print("\n样本外稳健参数 Top 10")
    for index, row in enumerate(valid_final[:10], 1):
        print(format_row(index, row))

    output = {
        "method": {
            "round_trip_cost": ROUND_TRIP_COST,
            "calibration_days": CALIBRATION_DAYS,
            "validation_days": VALIDATION_DAYS,
            "score": "day_mean_pct + .25*hit1.5 + .10*hit3 + .20*positive_days + .10*win - .30*mae<=-2",
            "selection": "min(train,test)-0.25*abs(train-test)",
        },
        "days": context["days"],
        "dropped": context["dropped"],
        "train_days": sorted(context["train_days"]),
        "test_days": sorted(context["test_days"]),
        "universe": context["universe"],
        "grid_size": {
            "flow": len(specs),
            "selected_flow": len(selected_specs),
            "overlay": len(overlay_specs()),
            "exit": len(exit_specs()),
        },
        "baseline": baseline,
        "flow_top": valid_flow[:50],
        "final_top": valid_final[:100],
        "selected_event_counts": {
            key: len(events) for key, events in events_by_flow.items()
        },
    }
    report = build_report(context, baseline, valid_final)
    if args.json:
        Path(args.json).write_text(
            json.dumps(output, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"JSON -> {args.json}")
    if args.report:
        Path(args.report).write_text(report, encoding="utf-8")
        print(f"报告 -> {args.report}")


if __name__ == "__main__":
    main()
