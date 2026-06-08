import sqlite3
c = sqlite3.connect('simple_trade/data/trade.db')

# 全量盘后优选表现分析
print("="*80)
print("📊 盘后优选历史表现全量分析")
print("="*80)

rows = c.execute("""SELECT * FROM overnight_performance ORDER BY screen_date, stock_code""").fetchall()
cols = [d[0] for d in c.execute("PRAGMA table_info(overnight_performance)").fetchall()]
cols = [c[1] for c in c.execute("PRAGMA table_info(overnight_performance)").fetchall()]
records = [dict(zip(cols, r)) for r in rows]

print(f"\n总记录: {len(records)} 条")
print(f"\n{'日期':>12} {'股票':>12} {'分类':>8} {'评分':>5} {'判定':>8} {'次日涨跌':>8} {'最大涨':>7} {'最大跌':>7}")
print("-"*85)

wins = losses = 0; total_ret = 0; total_max_gain = 0; total_max_loss = 0
by_cat = {}; by_verdict = {}; by_score = {'high':[],'mid':[],'low':[]}

for r in records:
    cat = r.get('category','')
    score = r.get('total_score',0) or 0
    verdict = r.get('verdict','')
    nxt_chg = r.get('next_change_pct',0) or 0
    max_g = r.get('max_gain_pct',0) or 0
    max_l = r.get('max_loss_pct',0) or 0
    name = r.get('stock_name','')
    sd = r.get('screen_date','')
    
    flag = "✅" if nxt_chg > 0 else "❌"
    print(f"  {sd:>10} {name:>10} {cat:>6} {score:>5.0f} {verdict:>6} {flag}{nxt_chg:>+7.1f}% {max_g:>+6.1f}% {max_l:>+6.1f}%")
    
    if nxt_chg > 0: wins += 1
    else: losses += 1
    total_ret += nxt_chg; total_max_gain += max_g; total_max_loss += max_l
    
    by_cat.setdefault(cat, []).append(nxt_chg)
    by_verdict.setdefault(verdict, []).append(nxt_chg)
    if score >= 70: by_score['high'].append(nxt_chg)
    elif score >= 60: by_score['mid'].append(nxt_chg)
    else: by_score['low'].append(nxt_chg)

n = len(records)
print(f"\n{'='*85}")
print(f"📈 总体: {wins}胜{losses}负 | 胜率{wins/n*100:.1f}% | 平均收益{total_ret/n:+.2f}% | 平均最大涨{total_max_gain/n:.2f}% 跌{total_max_loss/n:.2f}%")

print(f"\n📊 按分类:")
for cat, rets in sorted(by_cat.items()):
    n2 = len(rets); w2 = sum(1 for r in rets if r>0)
    avg = sum(rets)/n2
    print(f"  {cat}: {n2}条 | 胜率{w2/n2*100:.0f}% | 平均{avg:+.2f}%")

print(f"\n📊 按判定:")
for v, rets in sorted(by_verdict.items()):
    n2 = len(rets); w2 = sum(1 for r in rets if r>0)
    avg = sum(rets)/n2
    print(f"  {v}: {n2}条 | 胜率{w2/n2*100:.0f}% | 平均{avg:+.2f}%")

print(f"\n📊 按评分:")
for label, rets in [('≥70分',by_score['high']),('60-69分',by_score['mid']),('<60分',by_score['low'])]:
    if rets:
        n2=len(rets); w2=sum(1 for r in rets if r>0); avg=sum(rets)/n2
        print(f"  {label}: {n2}条 | 胜率{w2/n2*100:.0f}% | 平均{avg:+.2f}%")

# 对比: 盘后优选 vs 策略信号
print(f"\n{'='*85}")
print("📊 对比: 盘后优选 vs 原始策略信号")
print("-"*85)
print(f"  盘后优选(filtered): {n}条 | 胜率{wins/n*100:.1f}% | 平均{total_ret/n:+.2f}%")
for r in c.execute("""
    SELECT strategy_id, COUNT(*) as total, 
    AVG(CASE WHEN day1_max_rise > ABS(day1_max_drop) THEN 1.0 ELSE 0.0 END)*100 as wr,
    AVG(day1_max_rise + day1_max_drop) as avg_ret
    FROM signal_performance WHERE signal_type='BUY' AND (day1_max_rise>0 OR day1_max_drop<0)
    GROUP BY strategy_id ORDER BY total DESC LIMIT 3
""").fetchall():
    print(f"  {r[0]}: {r[1]}条 | D1胜率{r[2]:.1f}% | 平均{r[3]:+.2f}%")

c.close()
