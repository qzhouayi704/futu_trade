#!/usr/bin/env python3
"""用新的StockScorer全模式重新筛选6月5日盘后候选股，并验证6月6日实际表现"""
import sqlite3
from collections import defaultdict

DB = '/opt/futu_trade_sys/simple_trade/data/trade.db'
TARGET_DATE = '2026-06-05'
NEXT_DATE = '2026-06-06'
PASSING = 60

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
    vr=ind.get('vol_ratio',1); tp=ind.get('ticker_power')
    is_b=vr>=2.5 and (tp is not None and tp>=0.2)
    if is_b:
        c5d_cfg={'max_score':25,'optimal_range':(2,20),'marginal_range':(-5,30),'default':0}
    else:
        c5d_cfg={'max_score':20,'optimal_range':(-2,15),'marginal_range':(-5,25),'default':0}
    total = score_range(c5d_cfg, ind.get('change_5d'))
    total += score_range({'max_score':20,'optimal_range':(5,20),'marginal_range':(3,50),'default':0}, ind.get('amplitude'))
    total += score_tiered({'max_score':25,'tiers':[(5,20),(3,25),(2,18),(1.5,12),(1,5)],'default':0}, vr)
    if tp is not None:
        total += score_tiered({'max_score':25,'tiers':[(0.5,25),(0.2,18),(0.0,8)],'default':8}, tp)
    else:
        total += 8
    total += score_range({'max_score':5,'optimal_range':(0,1),'marginal_range':(0,1),'default':5}, ind.get('kline_pos'))
    total += score_reverse({'max_score':5,'reverse_tiers':[(3,5),(7,3),(12,1)],'default':0}, ind.get('prev_change'))
    return total

def score_breakout(ind, cont_days):
    bl=ind.get('breakout_level',''); bp=ind.get('breakout_pct',0)
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
    nir=ind.get('net_inflow_ratio')
    if nir is not None:
        for t,s in [(0.1,15),(0.05,12),(0.02,8),(0.0,4)]:
            if nir>=t: total+=s; break
    else: total+=7
    bor=ind.get('big_order_buy_ratio')
    if bor is not None:
        for t,s in [(0.6,10),(0.5,7),(0.4,4)]:
            if bor>=t: total+=s; break
    else: total+=5
    for t,s in [(5,10),(3,8),(2,6),(1,3)]:
        if cont_days>=t: total+=s; break
    total+=score_tiered({'max_score':15,'tiers':[(3,15),(2,12),(1.5,8),(1,4)],'default':0}, ind.get('vol_ratio'))
    tp=ind.get('ticker_power')
    if tp is not None:
        total+=score_tiered({'max_score':10,'tiers':[(0.5,10),(0.2,7),(0.0,4)],'default':4}, tp)
    else: total+=4
    chg=ind.get('today_change',0)
    if chg is not None:
        if 1<=chg<=5: total+=10
        elif 0<chg<1: total+=6
        elif 5<chg<=10: total+=7
        else: total+=3
    else: total+=5
    return total, True

def score_momentum(ind):
    pc=ind.get('prev_change',0)
    triggered = pc is not None and pc>=15
    if not triggered: return 0, False
    total=0
    for t,s in [(30,15),(20,12),(15,8)]:
        if pc>=t: total+=s; break
    total+=score_range({'max_score':20,'optimal_range':(-3,10),'marginal_range':(-8,20),'default':0}, ind.get('today_change'))
    total+=score_tiered({'max_score':20,'tiers':[(3,20),(2,16),(1.5,12),(1,6)],'default':0}, ind.get('vol_ratio'))
    tp=ind.get('ticker_power')
    if tp is not None:
        total+=score_tiered({'max_score':15,'tiers':[(0.5,15),(0.2,10),(0.0,5)],'default':5}, tp)
    else: total+=5
    total+=score_range({'max_score':15,'optimal_range':(5,25),'marginal_range':(3,40),'default':0}, ind.get('amplitude'))
    rec=ind.get('recovery',0.5)
    for t,s in [(0.8,15),(0.6,12),(0.4,8),(0.2,4)]:
        if rec>=t: total+=s; break
    return total, triggered

if __name__=='__main__':
    c = sqlite3.connect(DB)
    # 加载所有股票的kline
    rows = c.execute("""SELECT stock_code, substr(time_key,1,10) as td,
        open_price, close_price, high_price, low_price, volume, turnover_rate
        FROM kline_data WHERE time_key>='2026-05-01' AND time_key<='2026-06-07'
        ORDER BY stock_code, time_key""").fetchall()
    stock_bars = defaultdict(list)
    for r in rows:
        stock_bars[r[0]].append({'date':r[1],'open':float(r[2]),'close':float(r[3]),
            'high':float(r[4]),'low':float(r[5]),'vol':int(r[6]),'tr':float(r[7] or 0)})

    # 股票名称
    names = {}
    try:
        for r in c.execute("SELECT stock_code, stock_name FROM stock_pool WHERE stock_name!=''").fetchall():
            names[r[0]] = r[1]
    except:
        pass

    # 资金流
    cap_rows = c.execute("SELECT stock_code,date,net_inflow FROM capital_flow_daily WHERE date>='2026-05-01' ORDER BY stock_code,date").fetchall()
    cap = defaultdict(list)
    for r in cap_rows: cap[r[0]].append({'date':r[1],'net':float(r[2] or 0)})

    # ticker数据（如有）
    ticker = {}
    try:
        trows = c.execute("""SELECT stock_code, buy_sell_ratio FROM ticker_stats 
            WHERE substr(time_key,1,10)=? ORDER BY stock_code""", (TARGET_DATE,)).fetchall()
        for r in trows:
            if r[1] and float(r[1])>0:
                ticker[r[0]] = float(r[1]) - 1.0
    except: pass

    c.close()

    candidates = []
    for code, bars in stock_bars.items():
        # 找到TARGET_DATE的索引
        idx = None
        for i, b in enumerate(bars):
            if b['date'] == TARGET_DATE:
                idx = i; break
        if idx is None or idx < 5: continue
        if bars[idx]['tr'] > 0 and bars[idx]['tr'] < 0.3: continue

        b = bars[idx]
        prev = bars[idx-1]
        if b['open'] <= 0 or prev['open'] <= 0: continue

        c5 = bars[idx-5]['close'] if idx >= 5 else bars[0]['close']
        if c5 <= 0: continue

        ind = {
            'change_5d': (b['close']-c5)/c5*100,
            'amplitude': (b['high']-b['low'])/b['open']*100,
            'vol_ratio': b['vol']/(sum(bars[j]['vol'] for j in range(max(0,idx-5),idx))/5) if sum(bars[j]['vol'] for j in range(max(0,idx-5),idx))>0 else 1,
            'kline_pos': 0.5,
            'prev_change': abs((prev['close']-prev['open'])/prev['open']*100),
            'today_change': (b['close']-b['open'])/b['open']*100,
            'ticker_power': ticker.get(code),
        }
        # kline position
        lb = max(0, idx-19)
        highs = [bars[j]['high'] for j in range(lb,idx+1)]
        lows = [bars[j]['low'] for j in range(lb,idx+1)]
        if highs and lows:
            mh,ml = max(highs), min(lows)
            if mh>ml: ind['kline_pos'] = (b['close']-ml)/(mh-ml)

        # breakout
        if idx >= 6:
            h5 = max(bars[j]['high'] for j in range(max(0,idx-5),idx))
            h10 = max(bars[j]['high'] for j in range(max(0,idx-10),idx))
            h20 = max(bars[j]['high'] for j in range(lb,idx))
            if b['high'] > h20: ind['breakout_level']='20日高'; ind['breakout_pct']=(b['close']-h20)/h20*100
            elif b['high'] > h10: ind['breakout_level']='10日高'; ind['breakout_pct']=(b['close']-h10)/h10*100
            elif b['high'] > h5: ind['breakout_level']='5日高'; ind['breakout_pct']=(b['close']-h5)/h5*100

        # recovery
        if b['high']!=b['low']: ind['recovery']=(b['close']-b['low'])/(b['high']-b['low'])

        # capital continuity
        flows = cap.get(code, [])
        cont = 0
        d_idx = None
        for fi,f in enumerate(flows):
            if f['date']<=TARGET_DATE: d_idx=fi
        if d_idx is not None:
            for j in range(d_idx,-1,-1):
                if flows[j]['net']>0: cont+=1
                else: break
        ind['capital_continuity'] = cont
        if flows and d_idx is not None and d_idx>=0:
            last_flow = flows[d_idx]
            # simplified net_inflow_ratio
            ind['net_inflow_ratio'] = 0.05 if last_flow['net']>0 else -0.05

        # Score all 3 modes
        ts = score_trend(ind)
        bs, b_trig = score_breakout(ind, cont)
        ms, m_trig = score_momentum(ind)

        best_score = ts; best_mode = 'TREND'
        if b_trig and bs > best_score: best_score=bs; best_mode='BREAKOUT'
        if m_trig and ms > best_score: best_score=ms; best_mode='MOMENTUM'

        if best_score < PASSING: continue

        # Next day performance
        nxt_idx = None
        for ni in range(idx+1, len(bars)):
            if bars[ni]['date'] >= NEXT_DATE:
                nxt_idx = ni; break
        nxt_ret = nxt_mg = nxt_ml = None
        if nxt_idx:
            nxt = bars[nxt_idx]
            nxt_ret = (nxt['close']-b['close'])/b['close']*100
            nxt_mg = (nxt['high']-b['close'])/b['close']*100
            nxt_ml = (nxt['low']-b['close'])/b['close']*100

        mode_cat = {'TREND':'趋势追涨','BREAKOUT':'蓄势突破','MOMENTUM':'动量接力'}
        candidates.append({
            'code': code, 'name': names.get(code, code),
            'best_score': best_score, 'best_mode': best_mode,
            'category': mode_cat.get(best_mode,''),
            'trend': ts, 'breakout': bs if b_trig else '-',
            'momentum': ms if m_trig else '-',
            'change_5d': ind['change_5d'], 'vol_ratio': ind['vol_ratio'],
            'amplitude': ind['amplitude'], 'ticker_power': ind.get('ticker_power'),
            'breakout_level': ind.get('breakout_level',''),
            'next_ret': nxt_ret, 'next_mg': nxt_mg, 'next_ml': nxt_ml,
        })

    # Sort by best_score desc
    candidates.sort(key=lambda x: x['best_score'], reverse=True)

    print(f"{'='*100}")
    print(f"📊 6月5日盘后优选 — StockScorer全模式筛选 (评分≥{PASSING})")
    print(f"{'='*100}")
    print(f"{'排名':>4} {'股票':>10} {'分类':>6} {'最佳分':>6} {'模式':>10} "
          f"{'TREND':>6} {'BREAK':>6} {'MOMT':>6} {'5D%':>6} {'量比':>5} {'振幅':>5} "
          f"{'6/6收益':>8} {'盘中涨':>7} {'盘中跌':>7} {'结果':>4}")
    print("-"*100)

    wins = losses = 0
    for i, c in enumerate(candidates[:50], 1):
        tp_str = f"{c['ticker_power']:+.2f}" if c['ticker_power'] is not None else "N/A"
        nr = f"{c['next_ret']:+.1f}%" if c['next_ret'] is not None else "N/A"
        mg = f"{c['next_mg']:+.1f}%" if c['next_mg'] is not None else "N/A"
        ml = f"{c['next_ml']:+.1f}%" if c['next_ml'] is not None else "N/A"
        result = ""
        if c['next_ret'] is not None:
            if c['next_ret'] > 0: result = "✅"; wins += 1
            else: result = "❌"; losses += 1
        bs_str = str(c['breakout']) if c['breakout'] != '-' else '-'
        ms_str = str(c['momentum']) if c['momentum'] != '-' else '-'
        print(f"{i:>4} {c['name']:>10} {c['category']:>6} {c['best_score']:>6} {c['best_mode']:>10} "
              f"{c['trend']:>6} {bs_str:>6} {ms_str:>6} {c['change_5d']:>+5.1f}% {c['vol_ratio']:>5.1f} {c['amplitude']:>5.1f} "
              f"{nr:>8} {mg:>7} {ml:>7} {result:>4}")

    total = wins + losses
    print(f"\n{'='*100}")
    print(f"📈 Top50统计: {wins}胜{losses}负 | 胜率{wins/total*100:.1f}% | " if total>0 else "")
    if total > 0:
        avg_ret = sum(c['next_ret'] for c in candidates[:50] if c['next_ret'] is not None) / total
        print(f"   平均收益: {avg_ret:+.2f}%")

    # 按模式统计
    print(f"\n📊 按模式分组:")
    for mode in ['TREND','BREAKOUT','MOMENTUM']:
        group = [c for c in candidates if c['best_mode']==mode and c['next_ret'] is not None]
        if not group: continue
        w = sum(1 for c in group if c['next_ret']>0)
        avg = sum(c['next_ret'] for c in group)/len(group)
        print(f"  {mode:>10}: {len(group)}只 | 胜率{w/len(group)*100:.1f}% | 平均{avg:+.2f}%")
