"""Compact inspection of immutable research output."""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('report',type=Path)
    args = parser.parse_args()
    data = json.loads(args.report.read_text(encoding='utf-8'))
    print('COVERAGE',data['coverage'])
    print('VERSIONS',data['versions'])
    print('TRAIN_GRID_POSITIVE',sum(row['score']>0 for row in data['entry_grid']),len(data['entry_grid']))
    print('EXIT_GRID_POSITIVE',sum(row['score']>0 for row in data['exit_grid']),len(data['exit_grid']))
    print('WINNER',data['selected_by_training'])
    for row in data['results']:
        train,val = row['train'],row['validation']
        print('RESULT',row['family'],row['variant'],'train_mean',round(train['mean_net_pct'],4),
              'train_score',round(row['train_score'],4),'n',val['closed'],'mean',round(val['mean_net_pct'],4),
              'median',round(val['median_net_pct'],4),'win',round(val['win_pct'],2),
              'PF',round(val['profit_factor'] or 0,3),'worst',round(val['worst_trade_pct'],3),
              'stop%',round(val['stop_pct'],2),'gross',val.get('mean_gross_after_slip_pct'),
              'delay',val['median_delay_minutes'],'unresolved',val['unresolved'],
              'gap_free_n',row['validation_gap_free']['closed'],
              'gap_free_mean',row['validation_gap_free']['mean_net_pct'],
              'stress_cost',row['stress']['higher_cost']['mean_net_pct'],
              'stress_range',row['stress']['adverse_range']['mean_net_pct'])
        if row['variant']=='tuned':
            print('PARAM',row['rule'],row['exit'])
            print('DAILY',val['daily_mean_pct'])
            print('PORTFOLIO',row['portfolio_proxy'])
            for item in row['focus']:
                if item['day'] in ('2026-09-17','2026-09-18','2026-09-22','2026-09-23'):
                    print('CASE',item['day'],item['code'],item['signal_time'],item['entry_time'],
                          round(item['entry_price'],4),item['exit_time'],item['exit_price'],
                          item['net'],item['reason'],item['gap_minutes'])
    for row in data['staged']:
        print('STAGED',row['family'],row['initial_weight'],
              'train',row['train']['mean_net_pct'],'validation',row['validation']['mean_net_pct'],
              'n',row['validation']['closed'],'added',row['validation']['added'])
    for family,rows in data['training_top5_neighbors'].items():
        print('NEIGHBORS',family,[(r['validation']['closed'],r['validation']['mean_net_pct']) for r in rows])


if __name__ == '__main__':
    main()
