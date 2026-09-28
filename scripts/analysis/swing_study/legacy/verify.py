"""Independent artifact accounting and real-data causal/capacity checks."""
import argparse
from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path
import numpy as np

from scripts.analysis.minute_entry_study.models import N
from ..engine import after, run
from ..models import ExitRule, FillCosts
from .analytics import describe
from .data import load
from .models import Policy
from .signals import choose, folds, signals, training_score


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = json.loads((args.output/'report.json').read_text(encoding='utf-8'))
    assert hashlib.sha256(args.input.read_bytes()).hexdigest() == report['input_sha256']
    study = load(args.input)
    market, costs = study.market, FillCosts()
    assert market.days == report['days'] and len(market.days) == 52
    rows = read_rows(args.output/'trades.csv')
    groups: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    group_stats: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    boundaries = {f.name: f for f in folds()}
    for row in rows:
        signal, entry = int(row['signal']), int(row['entry'])
        p, buy = market.paths[row['code']], float(row['entry_price'])
        assert entry >= after(signal) and entry < after(signal)+5
        assert entry//N == int(row['day']) == signal//N
        assert p.mean[entry]*p.volume[entry]*costs.participation >= costs.ticket
        assert abs(buy-p.mean[entry]*(1+costs.slippage)) < 1e-9
        if row['split'] in boundaries:
            fold = boundaries[row['split']]
            assert signal//N >= fold.test_start
            boundary = (fold.test_end+1)*N
        else:
            assert row['split'] == 'continuous' and signal//N >= 20
            boundary = len(market.days)*N
        if row['exit']:
            trigger, out = int(row['trigger']), int(row['exit'])
            assert entry < trigger and out >= after(trigger) and out < boundary
            assert p.volume[out]*costs.participation >= costs.ticket/(buy*(1+costs.fee))
            expected = float(row['exit_price'])/buy*(1-costs.fee)/(1+costs.fee)-1
            assert abs(float(row['net'])-expected) < 1e-12
            last = out
        else:
            assert not row['net'] and not row['exit_price']
            last = boundary-1
        assert int(row['gap_minutes']) == int((~np.isfinite(p.mean[entry:last+1])).sum())
        groups[(row['strategy'], row['split'], row['code'])].append(row)
        group_stats[(row['strategy'], row['split'])].append(row)
    for trades in groups.values():
        trades.sort(key=lambda r: int(r['entry']))
        for prior, current in zip(trades, trades[1:]):
            assert prior['exit'] and int(prior['exit']) < int(current['signal'])
    for item in report['continuous_fixed_oos']:
        p = Policy(**item['policy'])
        key = 'fixed:'+p.key+f":{item['sessions']}d"
        part = group_stats.get((key, 'continuous'), [])
        closed = [float(r['net']) for r in part if r['net']]
        s = item['test']
        assert len(part) == s['filled'] == s['closed']+s['unresolved']
        assert len(closed) == s['closed']
        if closed:
            assert abs(np.mean(closed)*100-s['mean_net_pct']) < 1e-10
        assert s['signals'] == s['filled']+s['unfilled']+s['position_blocked']
    for selected in report['selected']:
        candidates = [r for r in report['training'] if r['fold'] == selected['fold']]
        route = None if selected['route'] == 'joint' else selected['route']
        expected = choose(candidates, route)
        assert expected == selected['selection']
        if expected:
            p, ex = Policy(**expected['policy']), ExitRule(**expected['exit'])
            fold = boundaries[selected['fold']]
            days = fold.train_days(ex.sessions)
            result = run(market, signals(study, p), ex, costs, days, fold.train_end)
            stats = describe(result, days)
            assert stats == expected['stats'] and training_score(stats) == expected['score']
            assert all(t.exit is None or t.exit < fold.test_start*N for t in result.trades)
    paired_rows = read_rows(args.output/'paired.csv')
    assert len({(r['route'], r['sessions'], r['episode_id']) for r in paired_rows}) == len(paired_rows)
    for key, item in report['paired_episode_diagnostics'].items():
        route, horizon = key.split(':')
        part = [r for r in paired_rows if r['route'] == route and int(r['sessions']) == int(horizon[:-1])]
        assert len(part) == item['first_episodes']
        assert sum(r['formal_available'] == 'True' for r in part) == item['confirmed_episodes']
        never = [float(r['early_net_pct']) for r in part if r['formal_recorded'] == 'False' and r['early_net_pct']]
        assert len(never) == item['unconfirmed_first_closed']
    output = {'status': 'PASS', 'input_sha256': market.sha256, 'trade_rows': len(rows),
              'paired_rows': len(paired_rows), 'episode_rows': len(read_rows(args.output/'episodes.csv')),
              'training_rows': len(report['training']),
              'checks': ['time_and_capacity', 'fees', 'no_overlap', 'missing_paths', 'unresolved_accounting',
                         'selected_training_recomputed', 'train_test_isolation', 'paired_denominators', 'input_hash']}
    print(json.dumps(output))


if __name__ == '__main__':
    main()
