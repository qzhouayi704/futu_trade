"""Artifact invariants, real-data capacity and reproducibility audit."""
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path

from .data import load
from .models import FillCosts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    market = load(args.input)
    report = json.loads((args.output/'report.json').read_text(encoding='utf-8'))
    assert report['sha256'] == market.sha256
    assert set(report['train_entry_dates']).isdisjoint(report['validation_entry_dates'])
    assert report['train_exit_through'] < min(report['validation_entry_dates'])
    costs = FillCosts()
    groups = defaultdict(list)
    with (args.output/'trades.csv').open(encoding='utf-8-sig',newline='') as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        signal,entry = int(row['signal']),int(row['entry'])
        price = float(row['entry_price'])
        path = market.paths[row['code']]
        assert signal < entry
        assert path.mean[entry]*path.volume[entry]*costs.participation >= costs.ticket
        if row['exit']:
            trigger,out = int(row['trigger']),int(row['exit'])
            assert entry <= trigger < out
            assert path.volume[out]*costs.participation >= costs.ticket/(price*(1+costs.fee))
            expected = float(row['exit_price'])/price*(1-costs.fee)/(1+costs.fee)-1
            assert abs(float(row['net'])-expected) < 1e-12
            if row['split'] == 'train':
                assert row['exit_time'][:10] <= report['train_exit_through']
        else:
            assert not row['net'] and not row['exit_price']
        groups[(row['strategy'],row['split'],row['code'])].append(row)
    for trades in groups.values():
        trades.sort(key=lambda row:int(row['entry']))
        for prior,current in zip(trades,trades[1:]):
            assert prior['exit'] and int(prior['exit']) < int(current['signal'])
    for r in report['results']:
        for split in ('train','validation'):
            s = r[split]
            assert s['filled'] == s['closed']+s['unresolved']
            assert s['signals'] == s['filled']+s['unfilled']+s['position_blocked']
    print(json.dumps({'status':'PASS','rows_checked':len(rows),'strategy_split_stock_groups':len(groups),
                      'hash':market.sha256,'positive_training_scores':sum(r['score'] > 0 for r in report['training_grid']),
                      'checks':['chronology','no_same_stock_overlap','minute_capacity','fees','unresolved_accounting',
                                'training_exit_isolation','input_hash']},ensure_ascii=False))


if __name__ == '__main__':
    main()
