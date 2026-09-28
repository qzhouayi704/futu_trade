"""Frozen legacy timing study, horizon-specific folds and train-only selection."""
import argparse
from collections import Counter
from dataclasses import asdict
import csv
import json
import logging
from pathlib import Path
import time
import numpy as np

from ..engine import run
from ..metrics import portfolio
from ..models import ExitRule, FillCosts
from ..run import record
from .analytics import describe, diagnostics, paired
from .data import load
from .models import Policy
from .signals import choose, exits, folds, policies, route_eligible, signal_for, signals, training_score


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--audit-only', action='store_true')
    args = parser.parse_args()
    if args.output and args.output.exists():
        raise FileExistsError(args.output)
    Path('logs').mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s',
                        handlers=[logging.StreamHandler(), logging.FileHandler('logs/legacy_swing_study.log', encoding='utf-8')])
    started = time.monotonic()
    study = load(args.input)
    market = study.market
    audit = {**study.counts, 'stages': study.stages,
             'episode_themes': dict(Counter(e.opportunity.theme for e in study.episodes)),
             'episode_dates': len({e.first.day for e in study.episodes}),
             'valid_background_episode_dates': len({e.first.day for e in study.episodes if e.opportunity.background.valid}),
             'route_episodes': {route: sum(route_eligible(e, route) for e in study.episodes) for route in ('all', 'low', 'flow')},
             'persist_lag_seconds_quantiles': np.quantile(study.time_lags, [0, .5, .95, 1]).tolist() if study.time_lags else []}
    logging.info('loaded %s', json.dumps(audit, ensure_ascii=False))
    if args.audit_only:
        return
    if args.output is None:
        raise ValueError('explicit output required')
    costs = FillCosts()
    grid = policies('low')+policies('flow')
    controls = policies('all')+grid
    by_key = {p.key: signals(study, p) for p in controls}
    training, selected, fixed, records = [], [], [], []
    for fold in folds():
        choices = []
        for p in grid:
            for ex in exits():
                days = fold.train_days(ex.sessions)
                result = run(market, by_key[p.key], ex, costs, days, fold.train_end)
                stats = describe(result, days)
                choices.append({'fold': fold.name, 'key': p.key+':'+ex.key, 'policy': asdict(p),
                                'exit': asdict(ex), 'stats': stats, 'score': training_score(stats)})
        training.extend(choices)
        # These decisions are frozen before this fold's returns are computed.
        picks = {route: choose(choices, None if route == 'joint' else route) for route in ('low', 'flow', 'joint')}
        for route, pick in picks.items():
            if pick is None:
                selected.append({'fold': fold.name, 'route': route, 'selection': None, 'reason': 'NO_ELIGIBLE_TRAINING_RULE'})
                continue
            p, ex = Policy(**pick['policy']), ExitRule(**pick['exit'])
            days = fold.test_days(ex.sessions)
            result = run(market, by_key[p.key], ex, costs, days, fold.test_end)
            selected.append({'fold': fold.name, 'route': route, 'selection': pick,
                             'positive_training_score': pick['score'] > 0,
                             'test': describe(result, days), 'diagnostics': diagnostics(result, days)})
            records.extend(record(t, 'selected:'+route+':'+pick['key'], fold.name, market.days) for t in result.trades)
        for p in controls:
            for h in (1, 3, 5):
                ex, days = ExitRule(h), fold.test_days(h)
                result = run(market, by_key[p.key], ex, costs, days, fold.test_end)
                fixed.append({'fold': fold.name, 'policy': asdict(p), 'sessions': h,
                              'entry_dates': [market.days[d] for d in days], 'test': describe(result, days)})
                records.extend(record(t, 'fixed:'+p.key+f':{h}d', fold.name, market.days) for t in result.trades)
        logging.info('completed %s: %d eligible training rules, %d positive', fold.name,
                     sum(r['score'] is not None for r in choices), sum(r['score'] is not None and r['score'] > 0 for r in choices))
    # Fixed-policy continuous OOS interval: positions do not reset at fold boundaries.
    continuous = []
    for p in controls:
        for h in (1, 3, 5):
            days, ex = list(range(20, 52-h+1)), ExitRule(h)
            result = run(market, by_key[p.key], ex, costs, days, 51)
            capital = run(market, by_key[p.key], ex, costs, days, 51, slots=5)
            stress = {name: describe(run(market, by_key[p.key], ex, c, days, 51), days)
                      for name, c in [('higher_cost', FillCosts(.0025, .001)), ('adverse_range', FillCosts(adverse=True))]}
            continuous.append({'policy': asdict(p), 'sessions': h, 'test': describe(result, days),
                               'diagnostics': diagnostics(result, days), 'stress': stress,
                               'portfolio': portfolio(market, capital.trades, costs, 20, 51),
                               'portfolio_execution': describe(capital, days)})
            records.extend(record(t, 'fixed:'+p.key+f':{h}d', 'continuous', market.days) for t in result.trades)
            records.extend(record(t, 'portfolio:'+p.key+f':{h}d', 'continuous', market.days) for t in capital.trades)
    paired_stats, paired_rows = paired(study)
    episode_rows = []
    for e in study.episodes:
        first_signal = signal_for(e, Policy('all', 'first'))
        episode_rows.append({'episode_id': e.first.event_id, 'code': e.first.code, 'day': e.first.day,
            'when': e.first.when.isoformat(), 'stage': e.first.stage, 'theme': e.opportunity.theme,
            'anchor': e.first.price, 'end_index': e.end_index, 'valid_daily': e.opportunity.background.valid,
            'recorded_confirmed': any(r.stage == 'CONFIRMED' for r in e.events),
            'all_first': first_signal.index if first_signal else None})
    report = {'schema': 1, 'input_sha256': market.sha256, 'days': market.days, 'audit': audit,
              'folds': [{**asdict(f), 'train_through': market.days[f.train_end],
                         'test_from': market.days[f.test_start], 'test_through': market.days[f.test_end]} for f in folds()],
              'costs': asdict(costs), 'training_combinations_per_fold': len(grid)*len(exits()),
              'signal_counts': {key: len(value) for key, value in by_key.items()},
              'training': training, 'selected': selected, 'fixed_by_fold': fixed,
              'continuous_fixed_oos': continuous, 'paired_episode_diagnostics': paired_stats,
              'limits': ['legacy capital_trend is not V2 or an unbiased whole-market scanner',
                         'FIRST requires contemporaneous theme; unmatched later confirmations excluded',
                         'daily historical revisions are not point-in-time; no corporate-action adjustments reconstructed',
                         'missing minutes not filled or certified as no-trade; observed-path outcomes are provisional',
                         'no photovoltaic legacy labels; volume proxies do not identify investors',
                         'fold selections are separate research accounts, not a stitched adaptive portfolio',
                         'continuous fixed policies retain positions across fold boundaries; no OOS winner selection',
                         'paired episodes can overlap and condition on future confirmation; descriptive only',
                         'completed-minute signals; orders wait up to five minutes without event-based cancellation',
                         'fees assumed; no board-lot rounding, queue or spread reconstruction'],
              'decision': 'RESEARCH_ONLY_NO_PRODUCTION_CHANGE', 'elapsed_seconds': time.monotonic()-started}
    args.output.mkdir(parents=True)
    (args.output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    write_csv(args.output/'trades.csv', records)
    write_csv(args.output/'episodes.csv', episode_rows)
    write_csv(args.output/'paired.csv', paired_rows)
    write_csv(args.output/'training-grid.csv', [{'fold': r['fold'], 'key': r['key'], 'score': r['score'],
        'closed': r['stats']['closed'], 'unresolved': r['stats']['unresolved'], 'mean_net_pct': r['stats']['mean_net_pct']} for r in training])
    logging.info('complete: %d trade records, %.1fs; %s', len(records), time.monotonic()-started, args.output)


if __name__ == '__main__':
    main()
