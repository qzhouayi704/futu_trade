"""Reproducible entry grid, chronological selection and held-out minute replay."""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict, replace
import csv
from itertools import product
import json
from pathlib import Path
import sys
import time

import numpy as np

from .models import Dataset, Exit, INDEX, Rule, Tape, Trade, WALL, load
from .replay import Costs, day_bootstrap, metrics, portfolio, replay, train_score
from .rules import choices, signal_index


def clock(index: int | None) -> str | None:
    if index is None:
        return None
    wall = WALL[index]
    return f'{wall//60:02}:{wall%60:02}'


def run_trades(tapes: list[Tape], signals: dict[tuple[str,str], int], rule: Rule,
               policy: Exit, costs: Costs) -> list[Trade]:
    result = []
    for tape in tapes:
        signal = signals.get((tape.day,tape.code))
        if signal is not None:
            trade = replay(tape, signal, rule, policy, costs)
            if trade is not None:
                result.append(trade)
    return result


def subset_metrics(trades: list[Trade], signals: dict[tuple[str,str],int], days: list[str]) -> dict:
    selected = [trade for trade in trades if trade.day in days]
    return metrics(selected, sum(day in days for day, _ in signals), days)


def score(stats: dict, train_days: list[str]) -> float:
    initial = train_score(stats)
    if initial == -1e9:
        return initial
    daily = stats['daily_mean_pct']
    cut = max(1, len(train_days)*2//3)
    a = [daily[d] for d in train_days[:cut] if daily[d] is not None]
    b = [daily[d] for d in train_days[cut:] if daily[d] is not None]
    if len(a) < 3 or len(b) < 2:
        return -1e9
    # Penalize a rule that succeeds only in one contiguous training block.
    return min(initial, float(np.mean(a)), float(np.mean(b)))


def serialize_trade(trade: Trade, strategy: str, split: str) -> dict:
    record = asdict(trade)
    record.update(strategy=strategy, split=split, signal_time=clock(trade.signal),
                  entry_time=clock(trade.entry), exit_time=clock(trade.exit))
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    began = time.monotonic()
    dataset = load(args.input)
    if len(dataset.days) < 12:
        raise ValueError('at least 12 observed dates required')
    train_days, validation_days = dataset.days[:-5], dataset.days[-5:]
    train_tapes = [t for t in dataset.tapes if t.day in train_days]
    validation_tapes = [t for t in dataset.tapes if t.day in validation_days]
    rule_grid = choices()
    base_exit, base_cost = Exit(), Costs()
    grid_rows = []
    signals_by_rule: dict[str, dict[tuple[str,str],int]] = {}
    family_rows: dict[str,list[dict]] = defaultdict(list)
    print(json.dumps({'stage':'loaded','stock_days':len(dataset.tapes),'coverage':dataset.coverage,
                      'train':train_days,'validation':validation_days,'rules':len(rule_grid)}), flush=True)
    for idx, rule in enumerate(rule_grid):
        signals = {}
        for tape in dataset.tapes:
            point = signal_index(tape, rule)
            if point is not None and point <= INDEX[870]:
                signals[(tape.day,tape.code)] = point
        signals_by_rule[rule.key] = signals
        trades = run_trades(train_tapes, signals, rule, base_exit, base_cost)
        stats = subset_metrics(trades, signals, train_days)
        row = {'rule':asdict(rule), 'key':rule.key, 'score':score(stats,train_days), 'train':stats}
        grid_rows.append(row)
        family_rows[rule.family].append(row)
        if idx % 40 == 0:
            print(json.dumps({'stage':'entry_grid','done':idx+1,'total':len(rule_grid)}), flush=True)
    selected = [max(rows, key=lambda row: (row['score'],row['train']['closed'],row['key']))
                for rows in family_rows.values()]
    exits = [Exit(stop,target,hold,trail) for stop,target,hold,trail in
             product((.01,.02,.03),(.02,.04,.06),(30,60,120),(0,.015))]
    results = []
    all_records = []
    exit_grid = []
    for selection in selected:
        rule = Rule(**selection['rule'])
        signals = signals_by_rule[rule.key]
        candidates = []
        for policy in exits:
            trades = run_trades(train_tapes, signals, rule, policy, base_cost)
            stats = subset_metrics(trades, signals, train_days)
            row = {'family':rule.family, 'exit':asdict(policy), 'score':score(stats,train_days), 'train':stats}
            candidates.append(row)
        best_exit = max(candidates, key=lambda row: (row['score'], -row['exit']['hold'], -row['exit']['stop']))
        exit_grid.extend(candidates)
        for label, policy in [('fixed',base_exit),('tuned',Exit(**best_exit['exit']))]:
            trades = run_trades(dataset.tapes, signals, rule, policy, base_cost)
            train = subset_metrics(trades, signals, train_days)
            validation = subset_metrics(trades, signals, validation_days)
            val_trades = [t for t in trades if t.day in validation_days]
            clean = [t for t in val_trades if t.gap_minutes == 0]
            validation['day_cluster_bootstrap_ci95_pct'] = day_bootstrap(val_trades, validation_days)
            item = {'family':rule.family,'variant':label,'rule':asdict(rule),'exit':asdict(policy),
                    'train_score':score(train,train_days),'train':train,'validation':validation,
                    'validation_gap_free':metrics(clean,len(clean),validation_days),
                    'portfolio_proxy':portfolio(val_trades,validation_tapes,validation_days),
                    'stress':{},'focus':[]}
            for name, cost in [('higher_cost',Costs(.0025,.001)),('adverse_range',Costs(adverse=True))]:
                stressed = run_trades(validation_tapes,signals,rule,policy,cost)
                item['stress'][name] = subset_metrics(stressed,signals,validation_days)
            for trade in trades:
                split = 'train' if trade.day in train_days else 'validation'
                record = serialize_trade(trade,f'{rule.family}:{label}',split)
                all_records.append(record)
                if trade.code in {'HK.00699','HK.00100'}:
                    item['focus'].append(record)
            results.append(item)
        print(json.dumps({'stage':'exit_grid','family':rule.family,'train_score':best_exit['score'],
                          'exit':best_exit['exit']}),flush=True)
    # Stage sizes are evaluated as hypotheses, never selected by held-out returns.
    staged = []
    for item in [r for r in results if r['variant']=='tuned' and r['family'] in {'breakout','low_reclaim','sustained_flow'}]:
        base_rule = Rule(**item['rule'])
        signals = signals_by_rule[base_rule.key]
        for weight in (.25,.5):
            rule = replace(base_rule,stage_weight=weight)
            policy = Exit(**item['exit'])
            trades = run_trades(dataset.tapes,signals,rule,policy,base_cost)
            staged.append({'family':rule.family,'initial_weight':weight,'rule':asdict(rule),'exit':asdict(policy),
                           'train':subset_metrics(trades,signals,train_days),
                           'validation':subset_metrics(trades,signals,validation_days)})
            all_records.extend(serialize_trade(t,f'{rule.family}:stage{weight}',
                               'train' if t.day in train_days else 'validation') for t in trades)
    tuned = [r for r in results if r['variant']=='tuned']
    winner = max(tuned,key=lambda item:item['train_score'])
    # Freeze the winner above before disclosing the validation ranks.
    validation_rank = sorted(tuned,key=lambda item:item['validation']['mean_net_pct'] or -1e9,reverse=True)
    top_neighbors = {}
    for family, rows in family_rows.items():
        selected_rows = sorted(rows,key=lambda row:row['score'],reverse=True)[:5]
        neighbors = []
        for row in selected_rows:
            rule = Rule(**row['rule'])
            sig = signals_by_rule[rule.key]
            trades = run_trades(validation_tapes,sig,rule,base_exit,base_cost)
            neighbors.append({'key':rule.key,'train_score':row['score'],
                              'validation':subset_metrics(trades,sig,validation_days)})
        top_neighbors[family] = neighbors
    report = {
        'schema':1,'input_sha256':dataset.sha256,'elapsed_seconds':time.monotonic()-began,
        'train_days':train_days,'validation_days':validation_days,'coverage':dataset.coverage,
        'versions':dataset.versions,'entry_rule_count':len(rule_grid),'exit_policy_count':len(exits),
        'assumptions':{'fee_per_side':base_cost.fee,'slippage_per_side':base_cost.slippage,
                       'notional_hkd':base_cost.notional,'max_minute_participation':base_cost.participation,
                       'decision_latency_seconds':1,'minute_price':'arithmetic mean, not close',
                       'volume_price_vwap':'proxy, not exact transaction VWAP',
                       'one_entry_per_stock_day':True,'no_same_bar_fill':True,
                       'split_note':'last five days excluded from parameter selection; previously inspected in diagnosis',
                       'universe_note':'recorded candidate universe, not all exchange-listed stocks',
                       'position_note':'prior 20 daily bars only; corporate actions not reconstructed'},
        'selected_by_training':{'family':winner['family'],'rule':winner['rule'],'exit':winner['exit']},
        'selection_decision':('RESEARCH_CANDIDATE_ONLY' if winner['train_score'] > 0 else 'NO_POSITIVE_TRAINING_EDGE'),
        'validation_rank_descriptive_only':[r['family'] for r in validation_rank],
        'entry_grid':grid_rows,'exit_grid':exit_grid,'results':results,'staged':staged,
        'training_top5_neighbors':top_neighbors,
    }
    args.output.mkdir(parents=True)
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    with (args.output/'trades.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer = csv.DictWriter(stream,fieldnames=list(all_records[0]))
        writer.writeheader()
        writer.writerows(all_records)
    with (args.output/'entry-grid.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        fields = ['key','score','closed','mean_net_pct','win_pct','profit_factor','unresolved']
        writer = csv.DictWriter(stream,fieldnames=fields)
        writer.writeheader()
        writer.writerows({field:(row[field] if field in row else row['train'][field]) for field in fields}
                         for row in grid_rows)
    print(json.dumps({'stage':'complete','winner':report['selected_by_training'],
                      'decision':report['selection_decision'],
                      'validation':[{'family':r['family'],'n':r['validation']['closed'],
                                     'mean':r['validation']['mean_net_pct'],
                                     'win':r['validation']['win_pct'],
                                     'unresolved':r['validation']['unresolved']} for r in tuned],
                      'elapsed':report['elapsed_seconds']},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
