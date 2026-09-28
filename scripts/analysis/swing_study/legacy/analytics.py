"""Delay diagnostics and missing-path-aware summaries; never eligibility filters."""
import numpy as np

from ..engine import replay
from ..metrics import filtered, summary
from ..models import ExitRule, FillCosts, ReplayResult
from .models import Policy, Study
from .signals import signal_for


def describe(result: ReplayResult, days: list[int]) -> dict:
    stats = summary(result, days)
    closed = [t for t in result.trades if t.net is not None]
    stats['codes'] = len({t.code for t in result.trades})
    stats['mean_entry_vs_first_pct'] = float(np.mean([t.entry_vs_anchor for t in result.trades])*100) if result.trades else None
    stats['median_signal_delay_minutes'] = float(np.median([t.signal_delay for t in result.trades])) if result.trades else None
    stats['mean_without_best_closed_pct'] = float(np.mean(sorted(t.net for t in closed)[:-1])*100) if len(closed) > 1 else None
    return stats


def diagnostics(result: ReplayResult, days: list[int]) -> dict:
    base, higher = FillCosts(), FillCosts(.0025, .001)
    multiplier = ((1-higher.slippage)/(1-base.slippage)*(1+base.slippage)/(1+higher.slippage)
                  * (1-higher.fee)/(1+higher.fee)*(1+base.fee)/(1-base.fee))
    fixed = [(1+t.net)*multiplier-1 for t in result.trades if t.net is not None]
    return {'fixed_path_higher_cost_mean_pct': float(np.mean(fixed)*100) if fixed else None,
            'gap_free_conditional': filtered([t for t in result.trades if t.gap_minutes == 0], days),
            'no_missing_whole_day_conditional': filtered([t for t in result.trades if not t.missing_whole_days], days),
            'exclude_focus': filtered([t for t in result.trades if t.code not in {'HK.00100', 'HK.00699'}], days),
            'themes': {theme: filtered([t for t in result.trades if t.theme == theme], days)
                       for theme in ('AI', '科技', '医药', '芯片', '光伏')}}


def paired(study: Study) -> tuple[dict, list[dict]]:
    rows = []
    market = study.market
    for route in ('all', 'low', 'flow'):
        for sessions in (1, 3, 5):
            for episode in study.episodes:
                early_signal = signal_for(episode, Policy(route, 'first'))
                if early_signal is None or early_signal.day+sessions > len(market.days):
                    continue
                late_signal = signal_for(episode, Policy(route, 'formal'))
                early = replay(market.paths[early_signal.code], early_signal, ExitRule(sessions), FillCosts(), 51)
                late = (replay(market.paths[late_signal.code], late_signal, ExitRule(sessions), FillCosts(), 51)
                        if late_signal else None)
                rows.append({'route': route, 'sessions': sessions, 'episode_id': episode.first.event_id,
                    'day': episode.first.day, 'code': episode.first.code, 'theme': episode.opportunity.theme,
                    'formal_available': late_signal is not None,
                    'formal_recorded': any(e.stage == 'CONFIRMED' for e in episode.events),
                    'delay_minutes': late_signal.index-early_signal.index if late_signal else None,
                    'early_filled': early is not None, 'formal_filled': late is not None,
                    'early_net_pct': early.net*100 if early and early.net is not None else None,
                    'formal_net_pct': late.net*100 if late and late.net is not None else None,
                    'formal_vs_early_fill_pct': (late.entry_price/early.entry_price-1)*100 if early and late else None,
                    'early_gap_minutes': early.gap_minutes if early else None,
                    'formal_gap_minutes': late.gap_minutes if late else None})
    output = {}
    for route in ('all', 'low', 'flow'):
        for sessions in (1, 3, 5):
            part = [r for r in rows if r['route'] == route and r['sessions'] == sessions]
            both = [r for r in part if r['early_net_pct'] is not None and r['formal_net_pct'] is not None]
            never = [r for r in part if not r['formal_recorded'] and r['early_net_pct'] is not None]
            fills = [r['formal_vs_early_fill_pct'] for r in part if r['formal_vs_early_fill_pct'] is not None]
            delays = [r['delay_minutes'] for r in part if r['delay_minutes'] is not None]
            output[f'{route}:{sessions}d'] = {
                'first_episodes': len(part), 'confirmed_episodes': sum(r['formal_available'] for r in part),
                'confirmed_outside_entry_window': sum(r['formal_recorded'] and not r['formal_available'] for r in part),
                'paired_closed': len(both),
                'paired_early_mean_pct': float(np.mean([r['early_net_pct'] for r in both])) if both else None,
                'paired_formal_mean_pct': float(np.mean([r['formal_net_pct'] for r in both])) if both else None,
                'paired_early_minus_formal_pct': float(np.mean([r['early_net_pct']-r['formal_net_pct'] for r in both])) if both else None,
                'median_confirmation_delay': float(np.median(delays)) if delays else None,
                'median_formal_fill_extension_pct': float(np.median(fills)) if fills else None,
                'unconfirmed_first_closed': len(never),
                'unconfirmed_first_mean_pct': float(np.mean([r['early_net_pct'] for r in never])) if never else None,
                'unconfirmed_first_win_pct': float(np.mean([r['early_net_pct'] > 0 for r in never])*100) if never else None,
                'unconfirmed_first_unresolved': sum(r['early_filled'] and r['early_net_pct'] is None and not r['formal_recorded'] for r in part)}
    return output, rows
