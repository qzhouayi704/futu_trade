"""Causal completed-minute order events with overnight pending exits."""
from __future__ import annotations

import numpy as np
from scripts.analysis.minute_entry_study.models import INDEX, N
from scripts.analysis.minute_entry_study.replay import next_complete_minute
from .models import ExitRule, FillCosts, Market, ReplayResult, Signal, StockPath, SwingTrade


def after(point: int) -> int:
    day,index = divmod(point,N)
    return day*N+next_complete_minute(index)


def find_fill(path: StockPath, start: int, end: int, costs: FillCosts, quantity: float | None = None) -> int | None:
    sl = slice(start,end)
    valid = np.isfinite(path.mean[sl]) & (path.volume[sl] > 0)
    capacity = path.volume[sl]*costs.participation
    valid &= (capacity >= quantity if quantity is not None else capacity*path.mean[sl] >= costs.ticket)
    points = np.flatnonzero(valid)
    return start+int(points[0]) if len(points) else None


def replay(path: StockPath, signal: Signal, policy: ExitRule, costs: FillCosts, end_day: int) -> SwingTrade | None:
    boundary = min(len(path.mean),(end_day+1)*N)
    earliest = after(signal.index)
    entry = find_fill(path,earliest,min(earliest+5,(signal.day+1)*N,boundary),costs)
    if entry is None:
        return None
    buy = float(path.high[entry] if costs.adverse else path.mean[entry])*(1+costs.slippage)
    quantity = costs.ticket/(buy*(1+costs.fee))
    risk = float(np.clip(signal.atr*policy.atr_multiple,.02,.10))
    start = entry+1
    points = np.arange(start,boundary)
    valid = np.isfinite(path.mean[start:boundary])
    fixed_stop = buy*(1-risk)
    peak = np.maximum.accumulate(np.r_[buy,np.nan_to_num(path.high[start:boundary],nan=buy)])[:-1]
    trail = np.where((peak >= buy*(1+risk)) & policy.protection,
                     peak*(1-min(signal.atr*1.5,.15)),0)
    stop_level = np.maximum(fixed_stop,trail)
    stop_hit = valid & (path.low[start:boundary] <= stop_level)
    target_hit = valid & (path.high[start:boundary] >= buy*(1+risk*policy.reward))
    deadline = (signal.day+policy.sessions-1)*N+INDEX[949]
    # Time exit is a CLOCK event; it does not require a quote in that minute.
    time_hit = points >= deadline
    hits = np.flatnonzero(stop_hit | target_hit | time_hit)
    trigger = None
    out_index = None
    reason = 'RIGHT_CENSORED'
    if len(hits):
        local = int(hits[0])
        trigger = start+local
        if stop_hit[local]:
            reason = 'TRAIL' if trail[local] > fixed_stop else 'STOP'
        elif target_hit[local]:
            reason = 'TARGET'
        else:
            reason = 'TIME'
        out_index = find_fill(path,after(trigger),boundary,costs,quantity)
        if out_index is None:
            reason = 'PENDING_EXIT_NO_FILL'
    last = out_index if out_index is not None else boundary-1
    observed = np.isfinite(path.mean[entry:last+1])
    gaps = int((~observed).sum())
    missing_days = sum(not np.isfinite(path.mean[d*N:(d+1)*N]).any()
                       for d in range(entry//N+1,last//N+1))
    out = (float(path.low[out_index] if costs.adverse else path.mean[out_index])*(1-costs.slippage)
           if out_index is not None else None)
    net = out/buy*(1-costs.fee)/(1+costs.fee)-1 if out is not None else None
    highs,lows = path.high[entry:last+1],path.low[entry:last+1]
    mfe = float(np.nanmax(highs)/buy-1) if np.isfinite(highs).any() else None
    mae = float(np.nanmin(lows)/buy-1) if np.isfinite(lows).any() else None
    return SwingTrade(signal.code,signal.theme,signal.day,signal.index,entry,trigger,out_index,buy,out,net,reason,
                      gaps,missing_days,risk,last//N-entry//N,mfe,mae,buy/signal.anchor-1,signal.index-signal.gate)


def run(market: Market, signals: list[Signal], policy: ExitRule, costs: FillCosts,
        entry_days: list[int], end_day: int, slots: int | None = None) -> ReplayResult:
    allowed = set(entry_days)
    result = ReplayResult()
    busy: dict[str,int] = {}
    active: list[SwingTrade] = []
    cash = 100000.
    for signal in signals:
        if signal.day not in allowed:
            continue
        result.signals += 1
        # Exit minute is usable as completed evidence no earlier than its next boundary.
        freed = [t for t in active if t.exit is not None and t.exit+1 < after(signal.index)]
        cash += sum(costs.ticket*(1+t.net) for t in freed)
        active = [t for t in active if t not in freed]
        if busy.get(signal.code,-1) >= signal.index:
            result.blocked_by_position += 1
            continue
        if slots is not None and (len(active) >= slots or cash < costs.ticket):
            result.blocked_by_position += 1
            continue
        trade = replay(market.paths[signal.code],signal,policy,costs,end_day)
        if trade is None:
            result.unfilled += 1
            continue
        result.trades.append(trade)
        busy[signal.code] = trade.exit if trade.exit is not None else (end_day+1)*N
        active.append(trade)
        cash -= costs.ticket
    return result
