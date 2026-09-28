"""Completed-minute decisions and subsequent complete-minute execution proxies."""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
import math

import numpy as np

from .models import Exit, INDEX, N, Rule, Tape, Trade, WALL


@dataclass(frozen=True)
class Costs:
    fee: float = .0015
    slippage: float = .0005
    adverse: bool = False
    notional: float = 10000
    participation: float = .10


def next_complete_minute(index: int) -> int:
    """Minute t becomes known at t+1 minute+1s; t+2 is first full eligible bar."""
    return bisect_left(WALL, WALL[index] + 2)


def fill_index(tape: Tape, trigger: int, weight: float, costs: Costs, entry: bool) -> int | None:
    earliest = next_complete_minute(trigger)
    last = min(N, earliest + 5) if entry else N
    for index in range(earliest, last):
        if (np.isfinite(tape.mean[index]) and tape.volume[index] > 0
                and tape.mean[index]*tape.volume[index]*costs.participation >= costs.notional*weight):
            return index
    return None


def buy_price(tape: Tape, index: int, costs: Costs) -> float:
    return float(tape.high[index] if costs.adverse else tape.mean[index]) * (1 + costs.slippage)


def sell_price(tape: Tape, index: int, costs: Costs) -> float:
    return float(tape.low[index] if costs.adverse else tape.mean[index]) * (1 - costs.slippage)


def replay(tape: Tape, signal: int, rule: Rule, policy: Exit, costs: Costs) -> Trade | None:
    weight = rule.stage_weight
    entry = fill_index(tape, signal, weight, costs, True)
    if entry is None or entry >= INDEX[949]:
        return None
    initial_price = buy_price(tape, entry, costs)
    legs = [(weight, initial_price)]
    peak = initial_price
    gaps = 0
    add_trigger = next((event.index for event in tape.events if event.kind == 'BUY_CONFIRMED'
                        and event.eligible and event.index > entry), None)
    pending_add: int | None = None
    reason = 'MISSING_EXIT_DATA'
    exit_index = None
    for index in range(entry+1, N):
        if pending_add == index:
            legs.append((1-weight, buy_price(tape, index, costs)))
            pending_add = None
        if not np.isfinite(tape.mean[index]):
            gaps += 1
            continue
        # Only previously completed bars set the trailing threshold.
        trailing = peak*(1-policy.trail) if policy.trail and peak >= initial_price*(1+policy.target/2) else 0
        stop = max(initial_price*(1-policy.stop), trailing)
        if tape.low[index] <= stop:
            reason = 'TRAIL' if trailing > initial_price*(1-policy.stop) else 'STOP'
        elif tape.high[index] >= initial_price*(1+policy.target):
            reason = 'TARGET'
        elif index-entry >= policy.hold:
            reason = 'TIME'
        elif index >= INDEX[949]:
            reason = 'DAY_EXIT'
        else:
            peak = max(peak, float(tape.high[index]))
            if weight < 1 and len(legs) == 1 and index == add_trigger and tape.mean[index] >= initial_price:
                pending_add = fill_index(tape, index, 1-weight, costs, True)
            continue
        # A completed-bar stop is known at the following boundary + 1s. An add
        # whose execution minute has already started cannot be retroactively
        # cancelled using this newly completed bar's low.
        if pending_add is not None and pending_add < next_complete_minute(index):
            legs.append((1-weight,buy_price(tape,pending_add,costs)))
            pending_add = None
        total_weight = sum(w for w, _ in legs)
        exit_index = fill_index(tape, index, total_weight, costs, False)
        if exit_index is not None:
            gaps += exit_index-next_complete_minute(index)
        break
    total_weight = sum(w for w, _ in legs)
    out = sell_price(tape, exit_index, costs) if exit_index is not None else None
    gross = sum(w*(out/price-1) for w, price in legs) if out is not None else None
    net = (sum(w*((out/price)*(1-costs.fee)/(1+costs.fee)-1) for w, price in legs)
           if out is not None else None)
    return Trade(tape.day, tape.code, signal, entry, exit_index, initial_price, out, net, gross,
                 reason if exit_index is not None else 'MISSING_EXIT_DATA', gaps,
                 total_weight, len(legs)>1, initial_price/tape.anchor-1, signal-tape.gate)


def metrics(trades: list[Trade], signals: int, days: list[str]) -> dict:
    closed = [trade for trade in trades if trade.net is not None]
    returns = np.array([t.net for t in closed], dtype=float)
    positives = returns[returns > 0]
    negatives = returns[returns < 0]
    daily = {day: [t.net for t in closed if t.day == day] for day in days}
    return {
        'signals': signals, 'filled': len(trades), 'closed': len(closed),
        'unresolved': len(trades)-len(closed), 'unfilled': signals-len(trades),
        'active_days': sum(bool(values) for values in daily.values()),
        'mean_net_pct': float(returns.mean()*100) if len(returns) else None,
        'mean_gross_after_slip_pct': float(np.mean([t.gross for t in closed])*100) if closed else None,
        'median_net_pct': float(np.median(returns)*100) if len(returns) else None,
        'win_pct': float((returns > 0).mean()*100) if len(returns) else None,
        'profit_factor': float(positives.sum() / -negatives.sum()) if len(negatives) else None,
        'worst_trade_pct': float(returns.min()*100) if len(returns) else None,
        'p10_pct': float(np.quantile(returns, .1)*100) if len(returns) else None,
        'stop_pct': sum(t.reason in {'STOP','TRAIL'} for t in closed)/max(1,len(closed))*100,
        'gaps_over5': sum(t.gap_minutes > 5 for t in trades),
        'mean_entry_vs_anchor_pct': float(np.mean([t.entry_vs_anchor for t in trades])*100) if trades else None,
        'median_delay_minutes': float(np.median([t.signal_delay for t in trades])) if trades else None,
        'added': sum(t.added for t in trades),
        'daily_mean_pct': {day: float(np.mean(values)*100) if values else None for day, values in daily.items()},
        'daily_sum_pct': {day: float(sum(values)*100) for day, values in daily.items()},
    }


def train_score(stats: dict) -> float:
    """Frozen training-only penalized lower-confidence score in percentage points."""
    if stats['closed'] < 40 or stats['active_days'] < 5 or stats['unresolved'] > stats['filled'] * .1:
        return -1e9
    values = [value for value in stats['daily_mean_pct'].values() if value is not None]
    return float(np.mean(values) - np.std(values, ddof=1) / math.sqrt(len(values)))


def day_bootstrap(trades: list[Trade], days: list[str], seed: int = 20260924) -> list[float] | None:
    sums = np.array([sum(t.net for t in trades if t.day == day and t.net is not None) for day in days])
    counts = np.array([sum(t.day == day and t.net is not None for t in trades) for day in days])
    if counts.sum() == 0:
        return None
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, len(days), size=(2000, len(days)))
    totals = counts[picks].sum(axis=1)
    means = sums[picks].sum(axis=1)[totals > 0] / totals[totals > 0]
    return (np.quantile(means, [.025,.975])*100).tolist()


def portfolio(trades: list[Trade], tapes: list[Tape], days: list[str], slots: int = 5) -> dict:
    """Fixed 10% target tickets, no leverage; MTM only from observed means.

    Fractional quantities and costs embedded in closed tickets are explicit proxies.
    Any unresolved ticket or missing held-minute mark suppresses strict drawdown.
    """
    by_key = {(t.day,t.code): t for t in tapes}
    accepted, rejected = [], 0
    cumulative, peak, max_dd = 0., 0., 0.
    daily_returns = {}
    missing_marks = 0
    unresolved = False
    for day in days:
        if unresolved:
            # Cannot invent a sale or free yesterday's occupied slots.
            break
        day_trades = sorted((t for t in trades if t.day == day), key=lambda t: (t.entry,t.code))
        active: list[Trade] = []
        completed: list[Trade] = []
        chosen: list[Trade] = []
        for index in range(N):
            just_closed = [t for t in active if t.exit is not None and t.exit < index]
            completed.extend(just_closed)
            active = [t for t in active if t not in just_closed]
            for trade in day_trades:
                if trade.entry == index:
                    if len(active) < slots:
                        active.append(trade)
                        accepted.append(trade)
                        chosen.append(trade)
                    else:
                        rejected += 1
            realized = sum(t.net or 0 for t in completed)*.1
            floating = 0.
            fresh = True
            for trade in active:
                tape = by_key[(day,trade.code)]
                price = tape.mean[index]
                if not np.isfinite(price):
                    missing_marks += 1
                    fresh = False
                else:
                    floating += (price/trade.entry_price-1)*trade.weight*.1
            if fresh:
                marked = cumulative + realized + floating
                peak = max(peak, marked)
                max_dd = max(max_dd, peak-marked)
        result = sum(t.net or 0 for t in chosen)*.1
        if any(t.net is None for t in chosen):
            unresolved = True
        cumulative += result
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak-cumulative)
        daily_returns[day] = result*100
    return {'closed_only_return_pct': cumulative*100,
            'return_pct': None if unresolved else cumulative*100,
            'accepted': len(accepted), 'slot_rejected': rejected,
            'missing_held_marks': missing_marks, 'unresolved': unresolved,
            'observed_mark_drawdown_pct': max_dd*100,
            'strict_drawdown_pct': None if missing_marks or unresolved else max_dd*100,
            'daily_return_pct': daily_returns}
