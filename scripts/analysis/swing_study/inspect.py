"""Compact artifact inspection without changing selection or rerunning a search."""
import argparse
import json
from pathlib import Path


def compact(stats: dict) -> dict:
    return {key:stats.get(key) for key in ('closed','unresolved','mean_net_pct','win_pct','profit_factor',
                                         'gap_free_closed','median_sessions','missing_whole_day_trades')}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--report',type=Path,required=True)
    args = parser.parse_args()
    d = json.loads(args.report.read_text(encoding='utf-8'))
    print('WINNER',json.dumps({k:d['selected_by_training'][k] for k in ('key','score','train')},ensure_ascii=False))
    for r in d['results']:
        print('SELECTED',json.dumps({'family':r['family'],'rule':r['rule'],'exit':r['exit'],
              'train':compact(r['train']),'validation':compact(r['validation']),
              'gap_free':compact(r['gap_free_conditional']),
              'no_whole_day_missing':compact(r['no_missing_whole_day_conditional']),
              'stress':{k:compact(v) for k,v in r['stress'].items()},'portfolio':r['portfolio'],
              'themes':{k:compact(v) for k,v in r['themes'].items()},
              'exclude_focus':compact(r['exclude_focus']),'remove_best':compact(r['remove_best_closed_trade'])},ensure_ascii=False))
    for r in d['horizon_comparison']:
        print('HORIZON',json.dumps({'family':r['rule']['family'],'days':r['exit']['sessions'],
                                   'train':compact(r['train']),'validation':compact(r['validation']),
                                   'ci95':r['validation'].get('day_cluster_ci95_pct'),
                                   'gap_free':compact(r['gap_free_conditional']),
                                   'no_whole_day_missing':compact(r['no_whole_day_missing_conditional']),
                                   'stress':{k:compact(v) for k,v in r['stress'].items()},
                                   'exclude_focus':compact(r['exclude_focus']),'portfolio':r['portfolio'],
                                   'themes':{k:compact(v) for k,v in r['themes'].items()}},ensure_ascii=False))
    for r in d.get('focus_cases',[]):
        if (r['signal_time'].startswith('2026-09-17') and r['code']=='HK.00699' or
            r['signal_time'].startswith('2026-09-18') and r['code']=='HK.00100'):
            print('FOCUS',json.dumps(r,ensure_ascii=False))
    for r in d['ten_day_exploratory']:
        print('TEN_DAY',json.dumps({'family':r['family'],'stats':compact(r['stats'])}))
    print('POSITIVE_TRAIN',sum(r['score'] > 0 for r in d['training_grid']))
    print('NEIGHBORS',json.dumps({f:[{'key':r['key'],'train_score':r['train_score'],'validation':compact(r['validation'])}
                                     for r in rows] for f,rows in d['neighbors'].items()},ensure_ascii=False))


if __name__ == '__main__':
    main()
