#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从数据库生成markdown报告"""
import sqlite3, os, sys
from datetime import datetime, timedelta

DB = os.path.join(os.path.dirname(__file__), '..', 'simple_trade', 'data', 'trade.db')
OUT = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'buy_signal_report.md')

def vwap(row):
    if not row: return None
    v, t = row[5], row[6]
    if v and v > 0 and t and t > 0: return t / v
    ps = [p for p in row[1:5] if p]
    return sum(ps)/len(ps) if ps else None

def fp(v):
    return '-' if v is None else f'{v:.3f}'

def fr(v):
    if v is None: return '-'
    return f'+{v:.2f}%' if v >= 0 else f'{v:.2f}%'

conn = sqlite3.connect(DB)
c = conn.cursor()

# 1. 去重买入信号
c.execute("""
    SELECT ts.id, s.code, s.name, ts.signal_price, ts.created_at, ts.strategy_id, ts.strategy_name
    FROM trade_signals ts JOIN stocks s ON ts.stock_id = s.id
    WHERE ts.signal_type = 'BUY' ORDER BY ts.created_at DESC
""")
rows = c.fetchall()
seen = set()
signals = []
for r in rows:
    key = (r[1], r[4][:10])
    if key not in seen:
        seen.add(key)
        signals.append({'code':r[1],'name':r[2],'price':r[3],'date':r[4][:10],
                        'strategy':r[6] or r[5] or '-'})

# 2. 分析
results = []
for sig in signals:
    c.execute("SELECT time_key,open_price,close_price,high_price,low_price,volume,turnover FROM kline_data WHERE stock_code=? AND DATE(time_key)=DATE(?) LIMIT 1", (sig['code'], sig['date']))
    d0 = c.fetchone()
    bv = vwap(d0) or sig['price']
    
    c.execute("SELECT time_key,open_price,close_price,high_price,low_price,volume,turnover FROM kline_data WHERE stock_code=? AND DATE(time_key)>DATE(?) ORDER BY time_key ASC LIMIT 15", (sig['code'], sig['date']))
    fk = c.fetchall()
    
    r = {'code':sig['code'],'name':sig['name'],'date':sig['date'],'strategy':sig['strategy'],'bv':bv}
    for label, idx in [('d1',0),('d3',2),('d5',4),('d10',9)]:
        if idx < len(fk):
            v = vwap(fk[idx])
            r[f'{label}_d'] = fk[idx][0][:10]
            r[f'{label}_v'] = v
            r[f'{label}_r'] = (v - bv)/bv*100 if v and bv else None
        else:
            r[f'{label}_d'] = '-'
            r[f'{label}_v'] = None
            r[f'{label}_r'] = None
    results.append(r)
conn.close()

# 3. 生成MD - 只输出有完整T+10数据的信号（有意义的）
# 分两组：完整数据 + 近期数据
full = [r for r in results if r.get('d10_r') is not None]
partial = [r for r in results if r.get('d10_r') is None and r.get('d1_r') is not None]
nodata = [r for r in results if r.get('d1_r') is None]

lines = []
lines.append('# 买入信号收益率分析报告\n')
lines.append(f'> 生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}  ')
lines.append(f'> 数据来源: 本地 trade.db，共 {len(signals)} 条去重买入信号\n')
lines.append('## 计算方法\n')
lines.append('- **买入价**: 信号日的盘中均价 (VWAP = 成交额 ÷ 成交量)')
lines.append('- **T+N 价格**: 信号日之后第 N 个交易日的盘中均价')
lines.append('- **收益率**: (T+N均价 - 买入均价) ÷ 买入均价 × 100%\n')

# 汇总统计
lines.append('## 汇总统计\n')
lines.append('| 指标 | T+1 | T+3 | T+5 | T+10 |')
lines.append('|------|-----|-----|-----|------|')
for label, desc in [('d1','T+1'),('d3','T+3'),('d5','T+5'),('d10','T+10')]:
    pass  # placeholder
stats = {}
for label in ['d1','d3','d5','d10']:
    rets = [r[f'{label}_r'] for r in results if r.get(f'{label}_r') is not None]
    if rets:
        stats[label] = {
            'n': len(rets),
            'avg': sum(rets)/len(rets),
            'win': len([x for x in rets if x>0])/len(rets)*100,
            'max': max(rets),
            'min': min(rets),
            'med': sorted(rets)[len(rets)//2]
        }
    else:
        stats[label] = {'n':0,'avg':0,'win':0,'max':0,'min':0,'med':0}

# rebuild stats table
lines_stats = []
lines_stats.append('## 汇总统计\n')
lines_stats.append('| 指标 | T+1 | T+3 | T+5 | T+10 |')
lines_stats.append('|------|-----|-----|-----|------|')
lines_stats.append(f"| 样本数 | {stats['d1']['n']} | {stats['d3']['n']} | {stats['d5']['n']} | {stats['d10']['n']} |")
lines_stats.append(f"| 平均收益 | {stats['d1']['avg']:+.2f}% | {stats['d3']['avg']:+.2f}% | {stats['d5']['avg']:+.2f}% | {stats['d10']['avg']:+.2f}% |")
lines_stats.append(f"| 胜率 | {stats['d1']['win']:.1f}% | {stats['d3']['win']:.1f}% | {stats['d5']['win']:.1f}% | {stats['d10']['win']:.1f}% |")
lines_stats.append(f"| 中位数 | {stats['d1']['med']:+.2f}% | {stats['d3']['med']:+.2f}% | {stats['d5']['med']:+.2f}% | {stats['d10']['med']:+.2f}% |")
lines_stats.append(f"| 最大盈利 | {stats['d1']['max']:+.2f}% | {stats['d3']['max']:+.2f}% | {stats['d5']['max']:+.2f}% | {stats['d10']['max']:+.2f}% |")
lines_stats.append(f"| 最大亏损 | {stats['d1']['min']:+.2f}% | {stats['d3']['min']:+.2f}% | {stats['d5']['min']:+.2f}% | {stats['d10']['min']:+.2f}% |")

# 按策略分组统计
lines_strat = []
lines_strat.append('\n## 按策略分组统计\n')
strat_groups = {}
for r in results:
    s = r['strategy']
    if s not in strat_groups: strat_groups[s] = []
    strat_groups[s].append(r)

for sname, sresults in sorted(strat_groups.items()):
    d1r = [r['d1_r'] for r in sresults if r.get('d1_r') is not None]
    d10r = [r['d10_r'] for r in sresults if r.get('d10_r') is not None]
    if not d1r: continue
    lines_strat.append(f'**{sname}** (共{len(sresults)}条信号)')
    lines_strat.append(f'- T+1: 样本={len(d1r)}, 平均={sum(d1r)/len(d1r):+.2f}%, 胜率={len([x for x in d1r if x>0])/len(d1r)*100:.0f}%')
    if d10r:
        lines_strat.append(f'- T+10: 样本={len(d10r)}, 平均={sum(d10r)/len(d10r):+.2f}%, 胜率={len([x for x in d10r if x>0])/len(d10r)*100:.0f}%')
    lines_strat.append('')

# 详细表格 - 有完整T+10数据的
lines_full = []
lines_full.append('\n## 详细数据 — 有完整 T+10 数据\n')
lines_full.append('| 股票代码 | 名称 | 信号日期 | 策略 | 买入均价 | T+1日期 | T+1均价 | T+1收益 | T+3日期 | T+3均价 | T+3收益 | T+5日期 | T+5均价 | T+5收益 | T+10日期 | T+10均价 | T+10收益 |')
lines_full.append('|----------|------|----------|------|----------|---------|---------|---------|---------|---------|---------|---------|---------|---------|----------|----------|----------|')
for r in full:
    lines_full.append(f"| {r['code']} | {r['name']} | {r['date']} | {r['strategy']} | {fp(r['bv'])} | {r['d1_d']} | {fp(r['d1_v'])} | {fr(r['d1_r'])} | {r['d3_d']} | {fp(r['d3_v'])} | {fr(r['d3_r'])} | {r['d5_d']} | {fp(r['d5_v'])} | {fr(r['d5_r'])} | {r['d10_d']} | {fp(r['d10_v'])} | {fr(r['d10_r'])} |")

# 近期（部分数据）
lines_partial = []
if partial:
    lines_partial.append(f'\n## 详细数据 — 近期信号（部分数据，共{len(partial)}条）\n')
    lines_partial.append('| 股票代码 | 名称 | 信号日期 | 策略 | 买入均价 | T+1日期 | T+1均价 | T+1收益 | T+3日期 | T+3均价 | T+3收益 | T+5日期 | T+5均价 | T+5收益 |')
    lines_partial.append('|----------|------|----------|------|----------|---------|---------|---------|---------|---------|---------|---------|---------|---------|')
    for r in partial:
        lines_partial.append(f"| {r['code']} | {r['name']} | {r['date']} | {r['strategy']} | {fp(r['bv'])} | {r['d1_d']} | {fp(r['d1_v'])} | {fr(r['d1_r'])} | {r.get('d3_d','-')} | {fp(r.get('d3_v'))} | {fr(r.get('d3_r'))} | {r.get('d5_d','-')} | {fp(r.get('d5_v'))} | {fr(r.get('d5_r'))} |")

# 无数据
lines_nodata = []
if nodata:
    lines_nodata.append(f'\n## 待观察信号（尚无后续K线数据，共{len(nodata)}条）\n')
    lines_nodata.append('| 股票代码 | 名称 | 信号日期 | 策略 | 信号价格 |')
    lines_nodata.append('|----------|------|----------|------|----------|')
    for r in nodata:
        lines_nodata.append(f"| {r['code']} | {r['name']} | {r['date']} | {r['strategy']} | {fp(r['bv'])} |")

# 合并输出
all_lines = []
all_lines.append('# 买入信号收益率分析报告\n')
all_lines.append(f'> 生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}  ')
all_lines.append(f'> 数据来源: 本地 trade.db, 共 {len(signals)} 条去重买入信号  ')
all_lines.append(f'> 有完整T+10数据: {len(full)}条, 部分数据: {len(partial)}条, 待观察: {len(nodata)}条\n')
all_lines.append('## 计算方法\n')
all_lines.append('- **买入价**: 信号日盘中均价 VWAP = 成交额 ÷ 成交量')
all_lines.append('- **T+N 价格**: 信号后第 N 个交易日的盘中均价')
all_lines.append('- **收益率**: (T+N均价 - 买入均价) ÷ 买入均价 × 100%\n')
all_lines.extend(lines_stats)
all_lines.extend(lines_strat)
all_lines.extend(lines_full)
all_lines.extend(lines_partial)
all_lines.extend(lines_nodata)

with open(OUT, 'w', encoding='utf-8') as f:
    f.write('\n'.join(all_lines))
print(f"Report written to {OUT}")
print(f"Full: {len(full)}, Partial: {len(partial)}, NoData: {len(nodata)}")
