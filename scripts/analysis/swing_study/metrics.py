"""Unresolved-aware statistics and conservative capital-account diagnostics."""
from dataclasses import asdict
import math
import numpy as np

from scripts.analysis.minute_entry_study.models import N
from .models import FillCosts, Market, ReplayResult, SwingTrade


def summary(result: ReplayResult, days: list[int]) -> dict:
    closed = [t for t in result.trades if t.net is not None]
    values = np.array([t.net for t in closed],dtype=float)
    groups = {day:[t.net for t in closed if t.day == day] for day in days}
    negative = values[values < 0]
    return {'signals':result.signals,'filled':len(result.trades),'closed':len(closed),
            'unresolved':len(result.trades)-len(closed),'unfilled':result.unfilled,
            'position_blocked':result.blocked_by_position,'active_days':sum(bool(v) for v in groups.values()),
            'mean_net_pct':float(values.mean()*100) if len(values) else None,
            'median_net_pct':float(np.median(values)*100) if len(values) else None,
            'win_pct':float((values > 0).mean()*100) if len(values) else None,
            'profit_factor':float(values[values > 0].sum()/-negative.sum()) if len(negative) else None,
            'worst_net_pct':float(values.min()*100) if len(values) else None,
            'median_sessions':float(np.median([t.overnight_count+1 for t in closed])) if closed else None,
            'gap_free_closed':sum(t.gap_minutes == 0 for t in closed),
            'missing_whole_day_trades':sum(t.missing_whole_days > 0 for t in result.trades),
            'median_missing_minutes':float(np.median([t.gap_minutes for t in result.trades])) if result.trades else None,
            'mean_mfe_pct':float(np.mean([t.mfe for t in closed])*100) if closed else None,
            'mean_mae_pct':float(np.mean([t.mae for t in closed])*100) if closed else None,
            'daily_mean_pct':{str(day):float(np.mean(v)*100) if v else None for day,v in groups.items()}}


def score(stats: dict) -> float:
    if stats['closed'] < 25 or stats['active_days'] < 4 or stats['unresolved'] > .1*stats['filled']:
        return -1e9
    daily = [v for v in stats['daily_mean_pct'].values() if v is not None]
    return min(float(np.mean(daily)-np.std(daily,ddof=1)/math.sqrt(len(daily))),
               float(np.mean(daily[:len(daily)//2])),float(np.mean(daily[len(daily)//2:])))


def filtered(trades: list[SwingTrade], days: list[int]) -> dict:
    return summary(ReplayResult(trades,len(trades)),days)


def ci(trades: list[SwingTrade], days: list[int]) -> list[float] | None:
    sums = np.array([sum(t.net for t in trades if t.day == day and t.net is not None) for day in days])
    counts = np.array([sum(t.day == day and t.net is not None for t in trades) for day in days])
    if not counts.sum():
        return None
    picks = np.random.default_rng(20260924).integers(0,len(days),size=(2000,len(days)))
    total = counts[picks].sum(axis=1)
    means = sums[picks].sum(axis=1)[total > 0]/total[total > 0]
    return (np.quantile(means,[.025,.975])*100).tolist()


def portfolio(market: Market, trades: list[SwingTrade], costs: FillCosts, start_day: int, end_day: int) -> dict:
    cash = 100000.
    active: list[SwingTrade] = []
    missing = 0
    peak,equity,maxdd = cash,cash,0.
    exposure = []
    realized = 0.
    by_entry: dict[int,list[SwingTrade]] = {}
    for trade in trades:
        by_entry.setdefault(trade.entry,[]).append(trade)
    for index in range(start_day*N,(end_day+1)*N):
        for trade in by_entry.get(index,[]):
            active.append(trade)
            cash -= costs.ticket
        exited = [t for t in active if t.exit == index]
        for trade in exited:
            cash += costs.ticket*(1+trade.net)
            realized += costs.ticket*trade.net
        active = [t for t in active if t not in exited]
        marks = [market.paths[t.code].mean[index] for t in active]
        exposure.append(len(active)*costs.ticket/100000)
        if any(not np.isfinite(p) for p in marks):
            missing += 1
            continue
        equity = cash+sum(costs.ticket/(t.entry_price*(1+costs.fee))*p*(1-costs.slippage)*(1-costs.fee)
                          for t,p in zip(active,marks))
        peak = max(peak,equity)
        maxdd = max(maxdd,(peak-equity)/peak)
    return {'closed_only_return_pct':realized/1000,'return_pct':None if active else (cash/100000-1)*100,
            'open_positions':len(active),'cash_hkd':cash,'missing_mark_minutes':missing,
            'observed_mark_drawdown_pct':maxdd*100,'strict_drawdown_pct':None if missing or active else maxdd*100,
            'mean_capital_occupation_pct':float(np.mean(exposure)*100),'trades':len(trades)}
