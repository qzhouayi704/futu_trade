#!/usr/bin/env python3
"""盘后优选大规模回测 — 用kline+资金流数据重建评分，对比次日表现"""
import sqlite3
from collections import defaultdict

DB = '/opt/futu_trade_sys/simple_trade/data/trade.db'

def load_data():
    c = sqlite3.connect(DB)
    # kline (2026-04以后有500+只股票)
    rows = c.execute("""SELECT stock_code, substr(time_key,1,10) as td,
        open_price, close_price, high_price, low_price, volume, turnover_rate
        FROM kline_data WHERE time_key>='2026-04-01' ORDER BY stock_code, time_key""").fetchall()
    stock_bars = defaultdict(list)
    for r in rows:
        stock_bars[r[0]].append({
            'date':r[1],'open':float(r[2]),'close':float(r[3]),
            'high':float(r[4]),'low':float(r[5]),'vol':int(r[6]),
            'turnover_rate':float(r[7] or 0)})
    
    # 资金流(按日)
    cap_rows = c.execute("""SELECT stock_code, date, net_inflow FROM capital_flow_daily 
        WHERE date>='2026-04-01' ORDER BY stock_code, date""").fetchall()
    cap_daily = defaultdict(list)
    for r in cap_rows:
        cap_daily[r[0]].append({'date':r[1],'net':float(r[2] or 0)})
    
    c.close()
    return stock_bars, cap_daily

def compute_indicators(bars, i):
    if i < 5 or i+1 >= len(bars): return None
    b = bars[i]; prev = bars[i-1]
    c5 = bars[i-5]['close']
    if c5<=0 or b['open']<=0: return None
    change_5d = (b['close']-c5)/c5*100
    amp = (b['high']-b['low'])/b['open']*100
    avg_vol = sum(bars[j]['vol'] for j in range(i-5,i))/5
    vol_ratio = b['vol']/avg_vol if avg_vol>0 else 1
    lb = max(0,i-19)
    h20=max(bars[j]['high'] for j in range(lb,i+1))
    l20=min(bars[j]['low'] for j in range(lb,i+1))
    kline_pos = (b['close']-l20)/(h20-l20) if h20!=l20 else 0.5
    prev_change = (prev['close']-prev['open'])/prev['open']*100 if prev['open']>0 else 0
    today_change = (b['close']-b['open'])/b['open']*100
    nxt = bars[i+1]
    next_ret = (nxt['close']-b['close'])/b['close']*100
    next_max_gain = (nxt['high']-b['close'])/b['close']*100
    next_max_loss = (nxt['low']-b['close'])/b['close']*100
    # 趋势反转检测
    peak = max(bars[j]['close'] for j in range(lb,i+1))
    drop_from_peak = (peak-b['close'])/peak*100 if peak>0 else 0
    is_yang = b['close']>b['open']
    vol_up = b['vol']>avg_vol*1.2
    rebound = b['close']>prev['close']
    rev_score = sum([drop_from_peak>=10, is_yang, vol_up, rebound])*25
    return {
        'change_5d':change_5d,'amplitude':amp,'vol_ratio':vol_ratio,
        'kline_pos':kline_pos,'prev_change':abs(prev_change),
        'today_change':today_change,'turnover_rate':b.get('turnover_rate',0),
        'next_ret':next_ret,'next_max_gain':next_max_gain,'next_max_loss':next_max_loss,
        'date':b['date'],'close':b['close'],'rev_score':rev_score,
        'drop_from_peak':drop_from_peak}

def score_trend(ind):
    total = 0
    c5d = ind['change_5d']
    if -2<=c5d<=15: total+=20
    elif -5<=c5d<=25: total+=12
    amp = ind['amplitude']
    if 5<=amp<=20: total+=20
    elif 3<=amp<=50: total+=12
    vr = ind['vol_ratio']
    for t,s in [(5.0,20),(3.0,25),(2.0,18),(1.5,12),(1.0,5)]:
        if vr>=t: total+=s; break
    # ticker_power unavailable, use neutral 8
    total += 8
    if 0<=ind['kline_pos']<=1: total+=5
    pc = ind['prev_change']
    if pc>=12: total+=1
    elif pc>=7: total+=3
    elif pc>=3: total+=5
    return total

def classify_stock(ind, cont_days):
    """分类: 趋势追涨/趋势反转/资金吸筹/强势延续"""
    if ind['today_change']>=8: return '强势延续'
    if ind['rev_score']>=75: return '趋势反转'
    if cont_days>=2: return '资金吸筹'
    return '趋势追涨'

if __name__ == '__main__':
    print("加载数据...")
    stock_bars, cap_daily = load_data()
    print(f"  {len(stock_bars)} 只股票, {len(cap_daily)} 只有资金流")
    
    # 构建资金连续天数查找
    def get_cont_days(code, date):
        flows = cap_daily.get(code, [])
        d_idx = None
        for i,f in enumerate(flows):
            if f['date']<=date: d_idx=i
        if d_idx is None: return 0
        days = 0
        for j in range(d_idx, -1, -1):
            if flows[j]['net']>0: days+=1
            else: break
        return days
    
    # 收集所有样本
    all_samples = []
    for code, bars in stock_bars.items():
        for i in range(5, len(bars)-1):
            ind = compute_indicators(bars, i)
            if ind is None: continue
            cont = get_cont_days(code, ind['date'])
            trend_score = score_trend(ind)
            cat = classify_stock(ind, cont)
            # 盘后筛选模拟: 排除流动性不足
            if ind['turnover_rate']>0 and ind['turnover_rate']<0.3: continue
            # 排除缩量暴涨
            if ind['today_change']>10 and ind['turnover_rate']<1 and ind['vol_ratio']<0.8: continue
            all_samples.append({
                'code':code,'date':ind['date'],'trend_score':trend_score,
                'cat':cat,'cont_days':cont,'next_ret':ind['next_ret'],
                'next_max_gain':ind['next_max_gain'],'next_max_loss':ind['next_max_loss'],
                'today_change':ind['today_change'],'kline_pos':ind['kline_pos'],
                'vol_ratio':ind['vol_ratio'],'amplitude':ind['amplitude'],
                'rev_score':ind['rev_score'],'drop_from_peak':ind['drop_from_peak']})
    
    print(f"  {len(all_samples)} 条有效样本\n")
    
    # === 1. 当前盘后优选逻辑重建 ===
    print("="*80)
    print("📊 1. 当前盘后优选逻辑重建 (模拟)")
    print("="*80)
    
    # 模拟: trend_score>=60的是"趋势追涨"候选
    passed = [s for s in all_samples if s['trend_score']>=60]
    failed = [s for s in all_samples if s['trend_score']<60]
    
    def stats(group, label):
        n=len(group)
        if n==0: return
        wr=sum(1 for s in group if s['next_ret']>0)/n*100
        avg=sum(s['next_ret'] for s in group)/n
        avg_gain=sum(s['next_max_gain'] for s in group)/n
        avg_loss=sum(s['next_max_loss'] for s in group)/n
        print(f"  {label}: {n}条 | 胜率{wr:.1f}% | 平均{avg:+.2f}% | 盘中最大涨{avg_gain:+.2f}% 跌{avg_loss:+.2f}%")
    
    stats(passed, "评分≥60(通过)")
    stats(failed, "评分<60(未通过)")
    
    # === 2. 按分类拆解 ===
    print(f"\n{'='*80}")
    print("📊 2. 按分类拆解")
    print("="*80)
    cats = defaultdict(list)
    for s in all_samples: cats[s['cat']].append(s)
    for cat in ['趋势追涨','趋势反转','资金吸筹','强势延续']:
        if cat in cats: stats(cats[cat], cat)
    
    # === 3. 按分类+评分拆解 ===
    print(f"\n{'='*80}")
    print("📊 3. 分类+评分交叉")
    print("="*80)
    for cat in ['趋势追涨','趋势反转','资金吸筹','强势延续']:
        g = cats.get(cat,[])
        if not g: continue
        hi = [s for s in g if s['trend_score']>=60]
        lo = [s for s in g if s['trend_score']<60]
        print(f"\n  [{cat}]")
        stats(hi, f"  评分≥60")
        stats(lo, f"  评分<60")
    
    # === 4. 资金连续天数 vs 表现 ===
    print(f"\n{'='*80}")
    print("📊 4. 资金连续流入天数 vs 次日表现")
    print("="*80)
    for d in [0,1,2,3,5]:
        if d==5:
            g = [s for s in all_samples if s['cont_days']>=5]
            stats(g, f"≥{d}天")
        else:
            g = [s for s in all_samples if s['cont_days']==d]
            stats(g, f"  {d}天")
    
    # === 5. K线位置 vs 表现 ===
    print(f"\n{'='*80}")
    print("📊 5. K线位置 vs 次日表现")
    print("="*80)
    for lo,hi,label in [(0,0.2,'底部0-20%'),(0.2,0.4,'低位20-40%'),(0.4,0.6,'中位40-60%'),(0.6,0.8,'高位60-80%'),(0.8,1.01,'顶部80-100%')]:
        g = [s for s in all_samples if lo<=s['kline_pos']<hi]
        stats(g, label)
    
    # === 6. 前日涨幅 vs 表现 ===
    print(f"\n{'='*80}")
    print("📊 6. 当日涨幅分段 vs 次日表现")
    print("="*80)
    for lo,hi,label in [(-20,-5,'大跌<-5%'),(-5,-1,'小跌-5~-1%'),(-1,1,'平盘-1~+1%'),(1,5,'小涨+1~+5%'),(5,10,'中涨+5~+10%'),(10,50,'大涨>+10%')]:
        g = [s for s in all_samples if lo<=s['today_change']<hi]
        stats(g, label)
    
    # === 7. 距高点跌幅(趋势反转) ===
    print(f"\n{'='*80}")
    print("📊 7. 距20日高点跌幅 vs 次日表现 (趋势反转潜力)")
    print("="*80)
    for lo,hi,label in [(0,5,'近高点0-5%'),(5,10,'回调5-10%'),(10,20,'调整10-20%'),(20,50,'深跌>20%')]:
        g = [s for s in all_samples if lo<=s['drop_from_peak']<hi]
        stats(g, label)
