"""Train-only selection followed by frozen, date-isolated evaluation."""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict, replace
import csv
import json
from pathlib import Path
import time

from scripts.analysis.minute_entry_study.models import N, WALL
from .data import load
from .engine import replay, run
from .metrics import ci, filtered, portfolio, score, summary
from .models import EntryRule, ExitRule, FillCosts, ReplayResult, SwingTrade
from .signals import entry_grid, exit_grid, signals


def timestamp(point: int | None, days: list[str]) -> str | None:
    if point is None:
        return None
    day,minute = divmod(point,N)
    wall = WALL[minute]
    return f'{days[day]} {wall//60:02}:{wall%60:02}'


def record(trade: SwingTrade, label: str, split: str, days: list[str]) -> dict:
    result = asdict(trade)
    result.update(strategy=label,split=split,signal_time=timestamp(trade.signal,days),
                  entry_time=timestamp(trade.entry,days),trigger_time=timestamp(trade.trigger,days),
                  exit_time=timestamp(trade.exit,days))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--audit-only',action='store_true')
    args = parser.parse_args()
    if args.output is not None and args.output.exists():
        raise FileExistsError(args.output)
    began = time.monotonic()
    market = load(args.input)
    print(json.dumps({'stage':'loaded','audit':market.audit,'sectors':market.sectors,'days':market.days},ensure_ascii=False),flush=True)
    if args.audit_only:
        return
    if args.output is None or len(market.days) != 17:
        raise ValueError('explicit output and frozen 17-day calendar required')
    train,validation = list(range(5)),list(range(9,13))
    train_end,val_end = 8,16
    costs = FillCosts()
    rules,exits = entry_grid(),exit_grid()
    by_key = {rule.key:signals(market,rule) for rule in rules}
    rows = []
    for rule in rules:
        for policy in exits:
            result = run(market,by_key[rule.key],policy,costs,train,train_end)
            stats = summary(result,train)
            rows.append({'rule':asdict(rule),'exit':asdict(policy),'key':rule.key+':'+policy.key,
                         'train':stats,'score':score(stats)})
        print(json.dumps({'stage':'training','entry':rule.key,'completed':len(rows),'total':len(rules)*len(exits)}),flush=True)
    families = defaultdict(list)
    for row in rows:
        families[row['rule']['family']].append(row)
    chosen = [max(items,key=lambda r:(r['score'],r['train']['closed'],-r['exit']['sessions'],r['key']))
              for items in families.values()]
    winner = max(chosen,key=lambda r:(r['score'],r['train']['closed']))
    # All selections freeze here, before any validation returns are computed.
    results,records = [],[]
    for choice in chosen:
        rule,policy = EntryRule(**choice['rule']),ExitRule(**choice['exit'])
        candidates = by_key[rule.key]
        tested = run(market,candidates,policy,costs,validation,val_end)
        stats = summary(tested,validation)
        stats['day_cluster_ci95_pct'] = ci(tested.trades,validation)
        closed = [t for t in tested.trades if t.net is not None]
        without_best = sorted(closed,key=lambda t:t.net)[:-1]
        item = {'family':rule.family,'rule':asdict(rule),'exit':asdict(policy),'train':choice['train'],
                'train_score':choice['score'],'validation':stats,
                'gap_free_conditional':filtered([t for t in tested.trades if t.gap_minutes == 0],validation),
                'no_missing_whole_day_conditional':filtered([t for t in tested.trades if t.missing_whole_days == 0],validation),
                'exclude_focus':filtered([t for t in tested.trades if t.code not in {'HK.00699','HK.00100'}],validation),
                'remove_best_closed_trade':filtered(without_best,validation),
                'themes':{theme:filtered([t for t in tested.trades if t.theme == theme],validation)
                          for theme in ('AI','科技','医药','芯片','光伏')},'stress':{}}
        for name,stress in [('higher_cost',FillCosts(.0025,.001)),('adverse_range',FillCosts(adverse=True))]:
            item['stress'][name] = summary(run(market,candidates,policy,stress,validation,val_end),validation)
        capital = run(market,candidates,policy,costs,validation,val_end,slots=5)
        item['portfolio'] = portfolio(market,capital.trades,costs,min(validation),val_end)
        item['portfolio']['execution'] = summary(capital,validation)
        records.extend(record(t,rule.family+':selected','validation',market.days) for t in tested.trades)
        records.extend(record(t,rule.family+':portfolio','validation',market.days) for t in capital.trades)
        trained = run(market,candidates,policy,costs,train,train_end)
        records.extend(record(t,rule.family+':selected','train',market.days) for t in trained.trades)
        results.append(item)
        print(json.dumps({'stage':'validation','family':rule.family,'policy':asdict(policy),'stats':stats}),flush=True)
    horizon = []
    for rule in [EntryRule('confirmed'),EntryRule('immediate'),EntryRule('low'),EntryRule('flow')]:
        for sessions in (1,3,5):
            policy = ExitRule(sessions)
            tr = run(market,by_key[rule.key],policy,costs,train,train_end)
            val = run(market,by_key[rule.key],policy,costs,validation,val_end)
            val_stats = summary(val,validation)
            val_stats['day_cluster_ci95_pct'] = ci(val.trades,validation)
            capital = run(market,by_key[rule.key],policy,costs,validation,val_end,slots=5)
            horizon.append({'rule':asdict(rule),'exit':asdict(policy),'train':summary(tr,train),'validation':val_stats,
                            'gap_free_conditional':filtered([t for t in val.trades if t.gap_minutes == 0],validation),
                            'no_whole_day_missing_conditional':filtered([t for t in val.trades if t.missing_whole_days == 0],validation),
                            'exclude_focus':filtered([t for t in val.trades if t.code not in {'HK.00699','HK.00100'}],validation),
                            'stress':{name:summary(run(market,by_key[rule.key],policy,c,validation,val_end),validation)
                                      for name,c in [('higher_cost',FillCosts(.0025,.001)),
                                                     ('adverse_range',FillCosts(adverse=True))]},
                            'portfolio':portfolio(market,capital.trades,costs,min(validation),val_end),
                            'themes':{theme:filtered([t for t in val.trades if t.theme == theme],validation)
                                      for theme in ('AI','科技','医药','芯片','光伏')}})
            records.extend(record(t,rule.family+f':fixed{sessions}d','validation',market.days) for t in val.trades)
            records.extend(record(t,rule.family+f':fixed{sessions}d:portfolio','validation',market.days) for t in capital.trades)
    # Case diagnostics include ALL available focus signals, not just known winners.
    # Each is an independent entry-path experiment, NOT a portfolio or validation score.
    focus_cases = []
    for rule in [EntryRule('confirmed'),EntryRule('immediate'),EntryRule('low'),EntryRule('flow')]:
        for sessions in (1,3,5):
            policy = ExitRule(sessions)
            for signal in by_key[rule.key]:
                if signal.code not in {'HK.00699','HK.00100'} or signal.day+sessions > len(market.days):
                    continue
                trade = replay(market.paths[signal.code],signal,policy,costs,val_end)
                if trade is not None:
                    focus_cases.append(record(trade,rule.family+f':case{sessions}d','case_only',market.days))
    long_exploration = []
    for rule in [EntryRule('immediate'),EntryRule('low'),EntryRule('flow')]:
        entry_days = list(range(len(market.days)-10+1))
        result = run(market,by_key[rule.key],ExitRule(10),costs,entry_days,val_end)
        long_exploration.append({'family':rule.family,'note':'descriptive only; overlaps training and validation',
                                 'entry_dates':[market.days[d] for d in entry_days],'stats':summary(result,entry_days)})
        records.extend(record(t,rule.family+':10d','exploratory',market.days) for t in result.trades)
    neighbors = {}
    for family,items in families.items():
        neighbors[family] = []
        for choice in sorted(items,key=lambda r:r['score'],reverse=True)[:5]:
            rule,policy = EntryRule(**choice['rule']),ExitRule(**choice['exit'])
            result = run(market,by_key[rule.key],policy,costs,validation,val_end)
            neighbors[family].append({'key':choice['key'],'train_score':choice['score'],'validation':summary(result,validation)})
    report = {'schema':1,'sha256':market.sha256,'coverage':market.audit,'primary_sectors':market.sectors,
              'days':market.days,'train_entry_dates':[market.days[d] for d in train],
              'validation_entry_dates':[market.days[d] for d in validation],
              'train_exit_through':market.days[train_end],'validation_exit_through':market.days[val_end],
              'entry_rules':len(rules),'exit_rules':len(exits),'training_combinations':len(rows),
              'assumptions':{'costs':asdict(costs),'minute_decision':'completed minute plus 1 second; fill in next full minute',
                             'risk':'clip(prior14ATR/priorClose * multiple, 2%, 10%)',
                             'target':'entry * (1+risk*reward)','protection':'1.5 entry-date ATR trailing, activates at +1R',
                             'same_stock_overlap':False,'intraday_exit_clock':'15:49 trigger on final allowed session',
                             'daily_history':'prior dates only, latest historical stored version, not point-in-time revisions',
                             'universe':'event-time primary theme only; no future/current multi-label backfill',
                             'volume':'cumulative observed turnover / prior20 daily mean turnover * 330 / elapsed minutes',
                             'max_entry_minute_participation':.1,'lot_rounding':False,
                             'selection':'train-only joint 18x24 grid, 5 entry dates; last dates previously inspected, not blind'},
              'selected_by_training':winner,'results':results,'horizon_comparison':horizon,
              'ten_day_exploratory':long_exploration,'twenty_day':'UNAVAILABLE_NO_COMPLETE_ENTRY_WINDOW',
              'neighbors':neighbors,'training_grid':rows,'focus_cases':focus_cases,
              'decision':'RESEARCH_ONLY_INSUFFICIENT_INDEPENDENT_DATES',
              'elapsed_seconds':time.monotonic()-began}
    # Structural invariants: not a profitability test.
    for r in records:
        assert r['entry'] > r['signal']
        assert r['exit'] is None or r['exit'] > r['trigger'] >= r['entry']
        assert r['split'] != 'train' or r['exit'] is None or r['exit'] < (train_end+1)*N
    args.output.mkdir(parents=True)
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    with (args.output/'trades.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer = csv.DictWriter(stream,fieldnames=list(records[0]))
        writer.writeheader();writer.writerows(records)
    with (args.output/'training-grid.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        fields = ['key','score','closed','unresolved','mean_net_pct','win_pct']
        writer = csv.DictWriter(stream,fieldnames=fields)
        writer.writeheader()
        writer.writerows({f:row[f] if f in row else row['train'][f] for f in fields} for row in rows)
    print(json.dumps({'stage':'complete','winner':winner['key'],'train_score':winner['score'],
                      'decision':report['decision'],'elapsed':report['elapsed_seconds']}),flush=True)


if __name__ == '__main__':
    main()
