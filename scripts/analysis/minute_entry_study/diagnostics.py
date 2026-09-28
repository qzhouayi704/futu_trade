"""Post-selection diagnostics; never feeds parameter selection."""
from __future__ import annotations
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
import statistics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('directory',type=Path)
    args = parser.parse_args()
    destination = args.directory/'diagnostics.json'
    if destination.exists():
        raise FileExistsError(destination)
    with (args.directory/'trades.csv').open(encoding='utf-8-sig',newline='') as stream:
        rows = list(csv.DictReader(stream))
    index = {(r['strategy'],r['day'],r['code']):r for r in rows if r['split']=='validation' and r['net']}
    base = [r for r in rows if r['strategy']=='recorded_confirmed:fixed' and r['split']=='validation' and r['net']]
    paired = []
    for family in ('candidate_immediate','recorded_watching','breakout','low_reclaim','sustained_flow'):
        pairs = [(float(index[(family+':fixed',r['day'],r['code'])]['net']),float(r['net']))
                 for r in base if (family+':fixed',r['day'],r['code']) in index]
        paired.append({'family':family,'n':len(pairs),
                       'early_mean_pct':statistics.mean(p[0] for p in pairs)*100 if pairs else None,
                       'confirmation_mean_pct':statistics.mean(p[1] for p in pairs)*100 if pairs else None,
                       'difference_pp':statistics.mean(p[0]-p[1] for p in pairs)*100 if pairs else None})
    report = json.loads((args.directory/'report.json').read_text(encoding='utf-8'))
    # Excluding named examples checks whether their outsized moves drive aggregate conclusions.
    excluding_focus = []
    for item in report['results']:
        if item['variant'] != 'tuned':
            continue
        selected = [float(r['net']) for r in rows if r['split']=='validation' and r['net']
                    and r['strategy']==item['family']+':tuned' and r['code'] not in {'HK.00699','HK.00100'}]
        excluding_focus.append({'family':item['family'],'closed':len(selected),
                                'mean_net_pct':statistics.mean(selected)*100 if selected else None})
    result = {'paired':paired,'paired_warning':'Conditioned on future confirmation; timing attribution only, not deployable selection.',
              'excluding_focus':excluding_focus,
              'positive_training_entry_scores':sum(r['score']>0 for r in report['entry_grid']),
              'positive_training_exit_scores':sum(r['score']>0 for r in report['exit_grid'])}
    destination.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    main()
