#!/usr/bin/env python3
"""StockScorer 三模式完整回测: TREND + BREAKOUT + MOMENTUM
用kline数据重建指标，对比3种评分模式的次日表现"""
import sqlite3
from collections import defaultdict

DB = '/opt/futu_trade_sys/simple_trade/data/trade.db'

def load_all():
    c = sqlite3.connect(DB)
    rows = c.execute("""SELECT stock_code, substr(time_key,1,10) as td,
        open_price, close_price, high_price, low_price, volume, turnover_rate
        FROM kline_data WHERE time_key>='2026-04-01' ORDER BY stock_code, time_key""").fetchall()
    stock_bars = defaultdict(list)
    for r in rows:
        stock_bars[r[0]].append({'date':r[1],'open':float(r[2]),'close':float(r[3]),
            'high':float(r[4]),'low':float(r[5]),'vol':int(r[6]),'tr':float(r[7] or 0)})
    cap_rows = c.execute("SELECT stock_code,date,net_inflow FROM capital_flow_daily WHERE date>='2026-04-01' ORDER BY stock_code,date").fetchall()
    cap = defaultdict(list)
    for r in cap_rows: cap[r[0]].append({'date':r[1],'net':float(r[2] or 0)})
    c.close()
    return stock_bars, cap

def get_cont_days(flows, date):
    d_idx = None
    for i,f in enumerate(flows):
        if f['date']<=date: d_idx=i
    if d_idx is None: return 0
    days=0
    for j in range(d_idx,-1,-1):
        if flows[j]['net']>0: days+=1
        else: break
    return days

def compute(bars, i):
    if i<5 or i+1>=len(bars): return None
    b=bars[i]; prev=bars[i-1]
    if b['open']<=0 or prev['open']<=0: return None
    c5=bars[i-5]['close']
    if c5<=0: return None
    change_5d=(b['close']-c5)/c5*100
    amp=(b['high']-b['low'])/b['open']*100
    avg_vol=sum(bars[j]['vol'] for j in range(i-5,i))/5
    vol_ratio=b['vol']/avg_vol if avg_vol>0 else 1
    lb=max(0,i-19)
    h20=max(bars[j]['high'] for j in range(lb,i+1))
    l20=min(bars[j]['low'] for j in range(lb,i+1))
    kline_pos=(b['close']-l20)/(h20-l20) if h20!=l20 else 0.5
    prev_change=abs((prev['close']-prev['open'])/prev['open']*100)
    today_change=(b['close']-b['open'])/b['open']*100
    # breakout detection
    h5=max(bars[j]['high'] for j in range(max(0,i-5),i))
    h10=max(bars[j]['high'] for j in range(max(0,i-10),i))
    h20_prev=max(bars[j]['high'] for j in range(lb,i))
    bl=''
    if b['high']>h20_prev: bl='20日高'
    elif b['high']>h10: bl='10日高'
    elif b['high']>h5: bl='5日高'
    bp=(b['close']-h20_prev)/h20_prev*100 if h20_prev>0 and bl else 0
    # recovery ratio for momentum
    recovery=(b['close']-b['low'])/(b['high']-b['low']) if b['high']!=b['low'] else 0.5
    nxt=bars[i+1]
    next_ret=(nxt['close']-b['close'])/b['close']*100
    next_mg=(nxt['high']-b['close'])/b['close']*100
    next_ml=(nxt['low']-b['close'])/b['close']*100
    return {
        'change_5d':change_5d,'amplitude':amp,'vol_ratio':vol_ratio,'kline_pos':kline_pos,
        'prev_change':prev_change,'today_change':today_change,'breakout_level':bl,'breakout_pct':bp,
        'recovery':recovery,'date':b['date'],'next_ret':next_ret,'next_mg':next_mg,'next_ml':next_ml,
        'turnover_rate':b['tr']
    }

def score_range(cfg, value):
    if value is None: return cfg['max_score']//2
    lo,hi=cfg['optimal_range']; mlo,mhi=cfg['marginal_range']
    if lo<=value<=hi: return cfg['max_score']
    if mlo<=value<=mhi: return cfg['max_score']//2
    return cfg.get('default',0)

def score_tiered(cfg, value):
    if value is None: return cfg['max_score']//2
    for t,s in cfg['tiers']:
        if value>=t: return s
    return cfg.get('default',0)

def score_reverse(cfg, value):
    if value is None: return cfg['max_score']//2
    for t,s in cfg['reverse_tiers']:
        if value<=t: return s
    return cfg.get('default',0)

def score_trend(ind):
    vr=ind['vol_ratio']; tp=None  # no ticker_power from kline
    is_b=vr>=2.5  # B exemption (simplified, no ticker_power)
    if is_b:
        c5d_cfg={'max_score':25,'optimal_range':(2,20),'marginal_range':(-5,30),'default':0}
    else:
        c5d_cfg={'max_score':20,'optimal_range':(-2,15),'marginal_range':(-5,25),'default':0}
    total = score_range(c5d_cfg, ind['change_5d'])
    total += score_range({'max_score':20,'optimal_range':(5,20),'marginal_range':(3,50),'default':0}, ind['amplitude'])
    total += score_tiered({'max_score':25,'tiers':[(5,20),(3,25),(2,18),(1.5,12),(1,5)],'default':0}, vr)
    total += 8  # ticker_power default (no tick data)
    total += score_range({'max_score':5,'optimal_range':(0,1),'marginal_range':(0,1),'default':5}, ind['kline_pos'])
    total += score_reverse({'max_score':5,'reverse_tiers':[(3,5),(7,3),(12,1)],'default':0}, ind['prev_change'])
    return total

def score_breakout(ind, cont_days):
    bl=ind['breakout_level']; bp=ind['breakout_pct']
    if not bl: return 0, False
    total=0
    if bl=='20日高': total+=15
    elif bl=='10日高': total+=12
    elif bl=='5日高': total+=8
    if bp is not None:
        if 0<=bp<=3: total+=15
        elif bp<=5: total+=10
        elif bp<=8: total+=6
        else: total+=3
    else: total+=7
    total+=7  # net_inflow_ratio default (no data)
    total+=5  # big_order default
    for t,s in [(5,10),(3,8),(2,6),(1,3)]:
        if cont_days>=t: total+=s; break
    total+=score_tiered({'max_score':15,'tiers':[(3,15),(2,12),(1.5,8),(1,4)],'default':0}, ind['vol_ratio'])
    total+=4  # ticker_power default
    chg=ind['today_change']
    if 1<=chg<=5: total+=10
    elif 0<chg<1: total+=6
    elif 5<chg<=10: total+=7
    else: total+=3
    return total, True

def score_momentum(ind):
    pc=ind['prev_change']
    triggered = pc>=15
    if not triggered: return 0, False
    total=0
    for t,s in [(30,15),(20,12),(15,8)]:
        if pc>=t: total+=s; break
    total+=score_range({'max_score':20,'optimal_range':(-3,10),'marginal_range':(-8,20),'default':0}, ind['today_change'])
    total+=score_tiered({'max_score':20,'tiers':[(3,20),(2,16),(1.5,12),(1,6)],'default':0}, ind['vol_ratio'])
    total+=5  # ticker_power default
    total+=score_range({'max_score':15,'optimal_range':(5,25),'marginal_range':(3,40),'default':0}, ind['amplitude'])
    for t,s in [(0.8,15),(0.6,12),(0.4,8),(0.2,4)]:
        if ind['recovery']>=t: total+=s; break
    return total, triggered

def stats(group, label):
    n=len(group)
    if n==0: print(f"  {label}: 0条"); return
    wr=sum(1 for s in group if s['next_ret']>0)/n*100
    avg=sum(s['next_ret'] for s in group)/n
    mg=sum(s['next_mg'] for s in group)/n
    ml=sum(s['next_ml'] for s in group)/n
    print(f"  {label}: {n}条 | 胜率{wr:.1f}% | 平均{avg:+.2f}% | 盘中涨{mg:+.2f}%/跌{ml:+.2f}%")

if __name__=='__main__':
    print("加载数据...")
    stock_bars, cap_flows = load_all()
    print(f"  {len(stock_bars)}只股票")
    
    all_samples = []
    for code, bars in stock_bars.items():
        flows = cap_flows.get(code, [])
        for i in range(5, len(bars)-1):
            ind = compute(bars, i)
            if ind is None: continue
            if ind['turnover_rate']>0 and ind['turnover_rate']<0.3: continue
            cont = get_cont_days(flows, ind['date'])
            ts = score_trend(ind)
            bs, b_trig = score_breakout(ind, cont)
            ms, m_trig = score_momentum(ind)
            best_score = ts; best_mode = 'TREND'
            if b_trig and bs > best_score: best_score=bs; best_mode='BREAKOUT'
            if m_trig and ms > best_score: best_score=ms; best_mode='MOMENTUM'
            ind.update({'trend_score':ts,'breakout_score':bs,'breakout_trig':b_trig,
                'momentum_score':ms,'momentum_trig':m_trig,
                'best_score':best_score,'best_mode':best_mode,'cont':cont,'code':code})
            all_samples.append(ind)
    
    print(f"  {len(all_samples)}条样本\n")
    
    # === 1. 三种模式对比 ===
    print("="*80)
    print("📊 1. StockScorer三种模式 — 评分≥60时次日表现")
    print("="*80)
    trend_pass=[s for s in all_samples if s['trend_score']>=60]
    breakout_pass=[s for s in all_samples if s['breakout_trig'] and s['breakout_score']>=60]
    momentum_pass=[s for s in all_samples if s['momentum_trig'] and s['momentum_score']>=60]
    stats(trend_pass, "TREND≥60")
    stats(breakout_pass, "BREAKOUT≥60(突破)")
    stats(momentum_pass, "MOMENTUM≥60(动量接力)")
    
    # === 2. best策略 ===
    print(f"\n{'='*80}")
    print("📊 2. score_all_strategies: 最佳模式自动选择")
    print("="*80)
    best_pass=[s for s in all_samples if s['best_score']>=60]
    stats(best_pass, "Best≥60(自动选最佳模式)")
    stats(trend_pass, "对比: 仅TREND≥60")
    
    # === 3. 各模式评分段 ===
    print(f"\n{'='*80}")
    print("📊 3. TREND评分段 vs 次日表现")
    print("="*80)
    for lo,hi in [(0,30),(30,40),(40,50),(50,60),(60,70),(70,80),(80,100)]:
        g=[s for s in all_samples if lo<=s['trend_score']<hi]
        stats(g, f"  {lo:>3}-{hi:>3}")
    
    # === 4. BREAKOUT评分段 ===
    print(f"\n{'='*80}")
    print("📊 4. BREAKOUT评分段 vs 次日表现 (仅triggered)")
    print("="*80)
    triggered_b=[s for s in all_samples if s['breakout_trig']]
    print(f"  突破触发: {len(triggered_b)}条")
    for lo,hi in [(0,30),(30,40),(40,50),(50,60),(60,70),(70,80),(80,100)]:
        g=[s for s in triggered_b if lo<=s['breakout_score']<hi]
        stats(g, f"  {lo:>3}-{hi:>3}")
    
    # === 5. MOMENTUM评分段 ===
    print(f"\n{'='*80}")
    print("📊 5. MOMENTUM评分段 vs 次日表现 (前日≥15%)")
    print("="*80)
    triggered_m=[s for s in all_samples if s['momentum_trig']]
    print(f"  动量触发: {len(triggered_m)}条")
    for lo,hi in [(0,30),(30,40),(40,50),(50,60),(60,70),(70,80),(80,100)]:
        g=[s for s in triggered_m if lo<=s['momentum_score']<hi]
        stats(g, f"  {lo:>3}-{hi:>3}")
    
    # === 6. 盘后优选对比: 当前(仅TREND) vs 全模式 ===
    print(f"\n{'='*80}")
    print("📊 6. 盘后优选: 当前(仅TREND) vs 全模式(score_all_strategies)")
    print("="*80)
    stats(trend_pass, "当前: 仅TREND≥60")
    stats(best_pass, "建议: Best(TREND/BREAKOUT/MOMENTUM)≥60")
    # Only BREAKOUT or MOMENTUM that TREND missed
    extra=[s for s in best_pass if s['best_mode']!='TREND']
    stats(extra, "新增: BREAKOUT/MOMENTUM覆盖(TREND未通过)")
