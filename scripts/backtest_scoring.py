#!/usr/bin/env python3
"""用评分系统回测所有历史买入记录，验证评分与盈亏的相关性"""
import json
from collections import defaultdict

IN_PATH = "scripts/buy_day_indicators.json"
OUT_PATH = "scripts/scoring_backtest.json"

with open(IN_PATH, 'r', encoding='utf-8') as f:
    data = json.load(f)

def score_trade(ind):
    """对单笔交易打分，返回(总分, 各项明细)"""
    details = {}
    total = 0
    
    # 1. 5日累计涨幅 ≥ 2% → 30分
    c5 = ind.get('change_5d')
    if c5 is not None:
        if c5 >= 10:
            s = 30
        elif c5 >= 5:
            s = 25
        elif c5 >= 2:
            s = 20
        elif c5 >= 0:
            s = 10
        else:
            s = 0
        details['5d_trend'] = {'value': c5, 'score': s, 'max': 30}
        total += s
    else:
        details['5d_trend'] = {'value': None, 'score': 0, 'max': 30, 'note': '无数据'}
    
    # 2. K线20日位置 0.3~0.8 → 20分
    kp = ind.get('kline_pos_20d')
    if kp is not None:
        if 0.3 <= kp <= 0.8:
            s = 20
        elif 0.2 <= kp < 0.3 or 0.8 < kp <= 0.9:
            s = 10
        else:
            s = 0
        details['kline_pos'] = {'value': round(kp, 3), 'score': s, 'max': 20}
        total += s
    else:
        details['kline_pos'] = {'value': None, 'score': 0, 'max': 20, 'note': '无数据'}
    
    # 3. 买入日振幅 8~35% → 15分
    amp = ind.get('day_amplitude')
    if amp is not None:
        if 8 <= amp <= 35:
            s = 15
        elif 5 <= amp < 8 or 35 < amp <= 45:
            s = 8
        else:
            s = 0
        details['amplitude'] = {'value': round(amp, 1), 'score': s, 'max': 15}
        total += s
    else:
        details['amplitude'] = {'value': None, 'score': 0, 'max': 15, 'note': '无数据'}
    
    # 4. 量比 ≥ 1.5 → 15分
    vr = ind.get('vol_ratio')
    if vr is not None:
        if vr >= 2.0:
            s = 15
        elif vr >= 1.5:
            s = 10
        elif vr >= 1.0:
            s = 5
        else:
            s = 0
        details['vol_ratio'] = {'value': round(vr, 2), 'score': s, 'max': 15}
        total += s
    else:
        details['vol_ratio'] = {'value': None, 'score': 0, 'max': 15, 'note': '无数据'}
    
    # 5. 前日涨幅 ≤ 10% → 10分
    pd = ind.get('prev_day_change')
    if pd is not None:
        if pd <= 5:
            s = 10
        elif pd <= 10:
            s = 5
        else:
            s = 0
        details['prev_change'] = {'value': round(pd, 2), 'score': s, 'max': 10}
        total += s
    else:
        details['prev_change'] = {'value': None, 'score': 0, 'max': 10, 'note': '无数据'}
    
    # 6. 资金流为正 → 10分
    fr = ind.get('flow_ratio')
    if fr is not None:
        if fr > 0.3:
            s = 10
        elif fr > 0:
            s = 5
        else:
            s = 0
        details['flow'] = {'value': round(fr, 3), 'score': s, 'max': 10}
        total += s
    else:
        details['flow'] = {'value': None, 'score': 0, 'max': 10, 'note': '无数据'}
    
    return total, details

# 对每笔交易打分
scored = []
for t in data['trades']:
    total, details = score_trade(t)
    scored.append({
        'code': t['code'],
        'name': t.get('name', t['code']),
        'date': t['date'],
        'result': t['result'],
        'actual_pct': t['actual_pct'],
        'potential_pct': t.get('potential_pct', 0),
        'hold_minutes': t['hold_minutes'],
        'score': total,
        'details': details,
    })

# 按分数段分组统计
buckets = {'0-29': [], '30-49': [], '50-59': [], '60-79': [], '80-100': []}
for s in scored:
    sc = s['score']
    if sc >= 80: buckets['80-100'].append(s)
    elif sc >= 60: buckets['60-79'].append(s)
    elif sc >= 50: buckets['50-59'].append(s)
    elif sc >= 30: buckets['30-49'].append(s)
    else: buckets['0-29'].append(s)

bucket_stats = {}
for bk, trades in buckets.items():
    if trades:
        wins = [t for t in trades if t['result'] == 'WIN']
        losses = [t for t in trades if t['result'] == 'LOSS']
        avg_pnl = sum(t['actual_pct'] for t in trades) / len(trades)
        avg_potential = sum(t['potential_pct'] for t in trades) / len(trades)
        bucket_stats[bk] = {
            'count': len(trades),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': round(len(wins) / len(trades) * 100, 1),
            'avg_actual_pct': round(avg_pnl, 2),
            'avg_potential_pct': round(avg_potential, 2),
        }

# 总体统计
win_scores = [s['score'] for s in scored if s['result'] == 'WIN']
loss_scores = [s['score'] for s in scored if s['result'] == 'LOSS']

# 如果用60分及格线过滤
above_60 = [s for s in scored if s['score'] >= 60]
below_60 = [s for s in scored if s['score'] < 60]

result = {
    'overall': {
        'total': len(scored),
        'win_avg_score': round(sum(win_scores)/len(win_scores), 1) if win_scores else 0,
        'loss_avg_score': round(sum(loss_scores)/len(loss_scores), 1) if loss_scores else 0,
        'win_median_score': sorted(win_scores)[len(win_scores)//2] if win_scores else 0,
        'loss_median_score': sorted(loss_scores)[len(loss_scores)//2] if loss_scores else 0,
    },
    'threshold_60': {
        'above_count': len(above_60),
        'above_wins': sum(1 for s in above_60 if s['result'] == 'WIN'),
        'above_win_rate': round(sum(1 for s in above_60 if s['result'] == 'WIN') / len(above_60) * 100, 1) if above_60 else 0,
        'above_avg_pnl': round(sum(s['actual_pct'] for s in above_60) / len(above_60), 2) if above_60 else 0,
        'below_count': len(below_60),
        'below_wins': sum(1 for s in below_60 if s['result'] == 'WIN'),
        'below_win_rate': round(sum(1 for s in below_60 if s['result'] == 'WIN') / len(below_60) * 100, 1) if below_60 else 0,
        'below_avg_pnl': round(sum(s['actual_pct'] for s in below_60) / len(below_60), 2) if below_60 else 0,
    },
    'by_score_bucket': bucket_stats,
    'scored_trades': scored,
}

with open(OUT_PATH, 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"Done. {len(scored)} trades scored.")
print(f"\n=== Overall ===")
print(f"  WIN avg score:  {result['overall']['win_avg_score']}")
print(f"  LOSS avg score: {result['overall']['loss_avg_score']}")
print(f"\n=== 60-point threshold ===")
t60 = result['threshold_60']
print(f"  >=60: {t60['above_count']} trades, win_rate={t60['above_win_rate']}%, avg_pnl={t60['above_avg_pnl']}%")
print(f"  <60:  {t60['below_count']} trades, win_rate={t60['below_win_rate']}%, avg_pnl={t60['below_avg_pnl']}%")
print(f"\n=== By bucket ===")
for bk in ['0-29','30-49','50-59','60-79','80-100']:
    if bk in bucket_stats:
        b = bucket_stats[bk]
        print(f"  {bk:8s}: {b['count']:3d} trades, win_rate={b['win_rate']:5.1f}%, avg_pnl={b['avg_actual_pct']:+.2f}%")
