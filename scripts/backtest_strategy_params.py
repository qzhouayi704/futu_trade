#!/usr/bin/env python3
"""
Sniper策略参数端到端回测 — 从原始tick重新生成信号 → DecisionEngine模拟

扫描参数(来自 intraday_sniper.py):
  MEGA_MULTIPLIER: 巨量倍数 (当前=3)
  ACCEL_THRESHOLD: 加速倍数 (当前=3)
  SUSTAINED_RATIO: 持续流出比例 (当前=0.35)
  COOLDOWN_MINUTES: 冷却期 (当前=15)
  MEGA_FLOOR_PCT: 动态地板 (当前=0.02)
"""
import sqlite3
from collections import defaultdict

DB = '/opt/futu_trade_sys/simple_trade/data/trade.db'
MIN_DAILY_TURNOVER = 100
CONFLICT_WINDOW = 15
SCAN_INTERVAL = 3

# ===== 数据加载 =====
def load_all_data():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    days = [d['trade_date'] for d in conn.execute(
        "SELECT DISTINCT trade_date FROM ticker_data WHERE trade_date<'2026-06-06' ORDER BY trade_date").fetchall()]
    
    # 加载股票名
    names = {}
    for r in conn.execute("SELECT code, name FROM stocks").fetchall():
        names[r['code']] = r['name']
    
    all_data = {}
    for td in days:
        print(f"  加载 {td}...")
        rows = conn.execute("""
            SELECT stock_code, 
                   substr(datetime(timestamp/1000, 'unixepoch', '+8 hours'), 12, 5) as minute,
                   direction, SUM(turnover) as tv, AVG(price) as ap
            FROM ticker_data WHERE trade_date=?
            GROUP BY stock_code, minute, direction ORDER BY stock_code, minute
        """, (td,)).fetchall()
        
        # 按股票聚合分钟数据
        stock_minutes = defaultdict(lambda: defaultdict(lambda: {'buy':0,'sell':0,'price':0,'pn':0}))
        for r in rows:
            code = r['stock_code']; m = r['minute']; d = r['direction']
            tv = float(r['tv'] or 0); ap = float(r['ap'] or 0)
            if not ('09:15' <= m <= '16:10'): continue
            e = stock_minutes[code][m]
            if d == 'BUY': e['buy'] += tv
            elif d == 'SELL': e['sell'] += tv
            if ap > 0: e['price'] += ap; e['pn'] += 1
        
        # 构建timeline
        stock_timelines = {}
        for code, mins in stock_minutes.items():
            tl = []
            cb, cs = 0, 0
            for m in sorted(mins.keys()):
                e = mins[m]
                cb += e['buy']; cs += e['sell']
                net = e['buy'] - e['sell']
                price = round(e['price']/e['pn'],3) if e['pn']>0 else 0
                tl.append({
                    'time': m,
                    'net': round(net/10000, 1),
                    'cum_net': round((cb-cs)/10000, 1),
                    'price': price,
                    'turnover': round((e['buy']+e['sell'])/10000, 1),
                })
            tvs = [p['turnover'] for p in tl if p['turnover']>0]
            avg_tv = sum(tvs)/len(tvs) if tvs else 0
            day_total = sum(p['turnover'] for p in tl)
            if day_total >= MIN_DAILY_TURNOVER and len(tl) >= 10:
                stock_timelines[code] = {'tl': tl, 'avg_tv': avg_tv, 'day_total': day_total}
        
        # 加载tick用于交易模拟
        ticks_raw = conn.execute(
            "SELECT stock_code,price,timestamp FROM ticker_data WHERE trade_date=? ORDER BY timestamp",(td,)).fetchall()
        ticks = defaultdict(list)
        for t in ticks_raw:
            ticks[t['stock_code']].append({'price':float(t['price']),'ts':int(t['timestamp'])})
        
        all_data[td] = {'timelines': stock_timelines, 'ticks': dict(ticks)}
        print(f"    {len(stock_timelines)} 只股票有分钟数据")
    
    conn.close()
    return days, all_data, names

# ===== 信号生成(模拟IntradaySniper) =====
def generate_signals(timelines, names, params):
    mega_mult = params['mega_mult']
    accel_thresh = params['accel_thresh']
    sustained_ratio = params['sustained_ratio']
    cooldown = params['cooldown']
    floor_pct = params['floor_pct']
    
    signals = []
    
    for code, data in timelines.items():
        tl = data['tl']; avg_tv = data['avg_tv']; day_total = data['day_total']
        name = names.get(code, code)
        
        # 动态阈值
        mega_floor = max(50, day_total * floor_pct)
        accel_min = mega_floor * 0.5
        
        abs_nets = [abs(p['net']) for p in tl if p['net'] != 0]
        avg_abs_net = sum(abs_nets)/len(abs_nets) if abs_nets else avg_tv
        dynamic_mega = max(mega_floor, avg_abs_net * mega_mult)
        dynamic_sustained = max(sustained_ratio * avg_tv * 20, mega_floor * 0.6)
        
        state = {'prev_dir': 'neutral', 'cd': {}, 'recent': []}
        
        for i, pt in enumerate(tl):
            def can(st, red):
                if st in state['cd'] and i - state['cd'][st] < cooldown: return False
                cut = max(0, i - CONFLICT_WINDOW)
                for _, rr, ri in state['recent']:
                    if ri >= cut and (red != rr): return False
                return True
            
            # mega_sell
            if pt['net'] < -dynamic_mega and can('mega_sell', True):
                state['cd']['mega_sell'] = i
                state['recent'].append((pt['time'], True, i))
                signals.append({'time':pt['time'],'code':code,'name':name,'type':'mega_sell','red':True,'price':pt['price']})
            
            # mega_buy
            if pt['net'] > dynamic_mega and can('mega_buy', False):
                state['cd']['mega_buy'] = i
                state['recent'].append((pt['time'], False, i))
                signals.append({'time':pt['time'],'code':code,'name':name,'type':'mega_buy','red':False,'price':pt['price']})
            
            # 每3分钟
            if i % SCAN_INTERVAL == 0 and i > 0:
                cd = 'positive' if pt['cum_net']>0 else 'negative' if pt['cum_net']<0 else 'neutral'
                
                # accel_in
                if i >= 6:
                    r3 = sum(tl[j]['net'] for j in range(i-2,i+1))
                    p3 = sum(tl[j]['net'] for j in range(i-5,i-2))
                    if p3 > 0 and r3 > p3 * accel_thresh and r3 > accel_min:
                        if can('accel_in', False):
                            state['cd']['accel_in'] = i
                            state['recent'].append((pt['time'], False, i))
                            signals.append({'time':pt['time'],'code':code,'name':name,'type':'accel_in','red':False,'price':pt['price']})
                
                # sustained_out
                if i >= 20:
                    wn = sum(tl[j]['net'] for j in range(i-19, i+1))
                    if wn < -dynamic_sustained and can('sustained_out', True):
                        state['cd']['sustained_out'] = i
                        state['recent'].append((pt['time'], True, i))
                        signals.append({'time':pt['time'],'code':code,'name':name,'type':'sustained_out','red':True,'price':pt['price']})
                
                state['prev_dir'] = cd
            
            state['recent'] = [(t,r,ri) for t,r,ri in state['recent'] if ri >= max(0,i-30)]
    
    return sorted(signals, key=lambda s: s['time'])

# ===== 交易模拟 =====
def pt(t):
    try:
        p=t.split(':'); return int(p[0])*3600+int(p[1])*60
    except: return 0

def simulate_trades(signals, ticks):
    cap=100000; pos={}; closed=[]; cd={}; pending=defaultdict(list)
    
    for sig in signals:
        code=sig['code']; st=sig['type']; price=sig['price']; stime=sig['time']
        if price<=0: continue
        
        if st=='mega_sell':
            if code in pos:
                pp=pos.pop(code); pp['exit']=price; pp['reason']='mega_sell'
                cap+=price*pp['qty']; closed.append(pp)
                cd[code]=pt(stime)+1800
            continue
        if st in ('sustained_out','reversal_bear'): continue
        
        pending[code].append({'ts':pt(stime),'type':st,'price':price,'name':sig['name'],'time':stime})
        if st != 'mega_buy': continue
        
        csec=pt(stime)
        if code in cd and csec<cd[code]: continue
        
        recent=[s for s in pending[code] if 0<=(csec-s['ts'])<1200]
        types=set(s['type'] for s in recent if s['type'] in ('mega_buy','accel_in'))
        if len(types)<2: continue
        if len(pos)>=2: continue
        
        inv=cap*0.70; pc=inv*0.50; qty=int(pc/price)
        if qty<=0: continue
        
        entry=price
        if code in ticks:
            for tk in ticks[code]:
                tks=(tk['ts']/1000)%86400 if tk['ts']>1e10 else tk['ts']
                if tks>csec: entry=tk['price']; break
        
        cost=entry*qty
        if cost>cap: continue
        cap-=cost
        pos[code]={'code':code,'name':sig['name'],'entry':entry,'qty':qty,'peak':entry,'trail':False}
        cd[code]=csec+1800
    
    # tick追踪
    tc=[]
    for code,pp in pos.items():
        if code not in ticks: continue
        for tk in ticks[code]:
            pr=tk['price']
            if pr>pp['peak']: pp['peak']=pr
            pnl_pct=(pr/pp['entry']-1)*100
            if pnl_pct<=-5:
                pp['exit']=pr; pp['reason']='sl'; cap+=pr*pp['qty']; tc.append(code); closed.append(pp); break
            if not pp['trail'] and pnl_pct>=5: pp['trail']=True
            if pp['trail']:
                dd=(1-pr/pp['peak'])*100
                if dd>=2:
                    pp['exit']=pr; pp['reason']='tp'; cap+=pr*pp['qty']; tc.append(code); closed.append(pp); break
    for c in tc:
        if c in pos: del pos[c]
    for code in list(pos.keys()):
        pp=pos[code]
        pp['exit']=ticks[code][-1]['price'] if code in ticks and ticks[code] else pp['entry']
        pp['reason']='eod'; cap+=pp['exit']*pp['qty']; closed.append(pp)
    pos.clear()
    
    n=len(closed)
    pnl=cap-100000
    wins=sum(1 for t in closed if (t['exit']-t['entry'])*t['qty']>0) if n else 0
    wr=wins/n*100 if n else 0
    gw=sum((t['exit']-t['entry'])*t['qty'] for t in closed if (t['exit']-t['entry'])*t['qty']>0)
    gl=abs(sum((t['exit']-t['entry'])*t['qty'] for t in closed if (t['exit']-t['entry'])*t['qty']<=0))
    pf=gw/gl if gl>0 else 999
    return {'pnl':pnl,'trades':n,'wr':wr,'pf':pf,'closed':closed}


if __name__ == '__main__':
    print("🔄 加载原始tick数据...")
    days, all_data, names = load_all_data()
    
    # 当前参数基准
    current = {'mega_mult':3, 'accel_thresh':3, 'sustained_ratio':0.35, 'cooldown':15, 'floor_pct':0.02}
    
    # ===== 扫描1: MEGA_MULTIPLIER =====
    print(f"\n{'='*80}")
    print("📊 扫描1: MEGA_MULTIPLIER (巨量倍数)")
    print(f"{'='*80}")
    print(f"{'倍数':>6} {'信号数':>8} {'mega_buy':>10} {'accel_in':>10} {'交易':>6} {'P&L':>10} {'胜率':>7} {'PF':>6}")
    print("-"*70)
    
    for mult in [1.5, 2, 3, 5, 8, 12]:
        p = {**current, 'mega_mult': mult}
        all_sigs = []; all_trades_r = {'pnl':0,'trades':0}
        total_closed = []
        for td in days:
            sigs = generate_signals(all_data[td]['timelines'], names, p)
            all_sigs.extend(sigs)
            r = simulate_trades(sigs, all_data[td]['ticks'])
            total_closed.extend(r['closed'])
        
        n = len(total_closed)
        pnl = sum((t['exit']-t['entry'])*t['qty'] for t in total_closed)
        wins = sum(1 for t in total_closed if (t['exit']-t['entry'])*t['qty']>0)
        wr = wins/n*100 if n else 0
        gw = sum((t['exit']-t['entry'])*t['qty'] for t in total_closed if (t['exit']-t['entry'])*t['qty']>0)
        gl = abs(sum((t['exit']-t['entry'])*t['qty'] for t in total_closed if (t['exit']-t['entry'])*t['qty']<=0))
        pf = gw/gl if gl>0 else 999
        mb = sum(1 for s in all_sigs if s['type']=='mega_buy')
        ai = sum(1 for s in all_sigs if s['type']=='accel_in')
        cur = " ← 当前" if mult==3 else ""
        print(f"{mult:>5.1f}x {len(all_sigs):>8} {mb:>10} {ai:>10} {n:>6} {pnl:>+10,.0f} {wr:>6.1f}% {pf:>5.2f}{cur}")

    # ===== 扫描2: ACCEL_THRESHOLD =====
    print(f"\n{'='*80}")
    print("📊 扫描2: ACCEL_THRESHOLD (加速倍数)")
    print(f"{'='*80}")
    print(f"{'倍数':>6} {'accel_in数':>10} {'交易':>6} {'P&L':>10} {'胜率':>7} {'PF':>6}")
    print("-"*55)
    
    for thresh in [1.5, 2, 3, 5, 8]:
        p = {**current, 'accel_thresh': thresh}
        total_closed = []; total_ai = 0
        for td in days:
            sigs = generate_signals(all_data[td]['timelines'], names, p)
            total_ai += sum(1 for s in sigs if s['type']=='accel_in')
            r = simulate_trades(sigs, all_data[td]['ticks'])
            total_closed.extend(r['closed'])
        n=len(total_closed)
        pnl=sum((t['exit']-t['entry'])*t['qty'] for t in total_closed)
        wins=sum(1 for t in total_closed if (t['exit']-t['entry'])*t['qty']>0)
        wr=wins/n*100 if n else 0
        gw=sum((t['exit']-t['entry'])*t['qty'] for t in total_closed if (t['exit']-t['entry'])*t['qty']>0)
        gl=abs(sum((t['exit']-t['entry'])*t['qty'] for t in total_closed if (t['exit']-t['entry'])*t['qty']<=0))
        pf=gw/gl if gl>0 else 999
        cur=" ← 当前" if thresh==3 else ""
        print(f"{thresh:>5.1f}x {total_ai:>10} {n:>6} {pnl:>+10,.0f} {wr:>6.1f}% {pf:>5.2f}{cur}")

    # ===== 扫描3: COOLDOWN_MINUTES =====
    print(f"\n{'='*80}")
    print("📊 扫描3: COOLDOWN_MINUTES (信号冷却期)")
    print(f"{'='*80}")
    print(f"{'冷却':>8} {'信号数':>8} {'交易':>6} {'P&L':>10} {'胜率':>7} {'PF':>6}")
    print("-"*55)
    
    for cd_min in [5, 10, 15, 20, 30]:
        p = {**current, 'cooldown': cd_min}
        total_closed = []; total_sigs = 0
        for td in days:
            sigs = generate_signals(all_data[td]['timelines'], names, p)
            total_sigs += len(sigs)
            r = simulate_trades(sigs, all_data[td]['ticks'])
            total_closed.extend(r['closed'])
        n=len(total_closed)
        pnl=sum((t['exit']-t['entry'])*t['qty'] for t in total_closed)
        wins=sum(1 for t in total_closed if (t['exit']-t['entry'])*t['qty']>0)
        wr=wins/n*100 if n else 0
        gw=sum((t['exit']-t['entry'])*t['qty'] for t in total_closed if (t['exit']-t['entry'])*t['qty']>0)
        gl=abs(sum((t['exit']-t['entry'])*t['qty'] for t in total_closed if (t['exit']-t['entry'])*t['qty']<=0))
        pf=gw/gl if gl>0 else 999
        cur=" ← 当前" if cd_min==15 else ""
        print(f"{cd_min:>6}min {total_sigs:>8} {n:>6} {pnl:>+10,.0f} {wr:>6.1f}% {pf:>5.02f}{cur}")

    # ===== 扫描4: MEGA_FLOOR_PCT =====
    print(f"\n{'='*80}")
    print("📊 扫描4: MEGA_FLOOR_PCT (动态地板%)")
    print(f"{'='*80}")
    print(f"{'地板%':>8} {'信号数':>8} {'交易':>6} {'P&L':>10} {'胜率':>7} {'PF':>6}")
    print("-"*55)
    
    for fp in [0.01, 0.015, 0.02, 0.03, 0.05]:
        p = {**current, 'floor_pct': fp}
        total_closed = []; total_sigs = 0
        for td in days:
            sigs = generate_signals(all_data[td]['timelines'], names, p)
            total_sigs += len(sigs)
            r = simulate_trades(sigs, all_data[td]['ticks'])
            total_closed.extend(r['closed'])
        n=len(total_closed)
        pnl=sum((t['exit']-t['entry'])*t['qty'] for t in total_closed)
        wins=sum(1 for t in total_closed if (t['exit']-t['entry'])*t['qty']>0)
        wr=wins/n*100 if n else 0
        gw=sum((t['exit']-t['entry'])*t['qty'] for t in total_closed if (t['exit']-t['entry'])*t['qty']>0)
        gl=abs(sum((t['exit']-t['entry'])*t['qty'] for t in total_closed if (t['exit']-t['entry'])*t['qty']<=0))
        pf=gw/gl if gl>0 else 999
        cur=" ← 当前" if fp==0.02 else ""
        print(f"{fp*100:>6.1f}% {total_sigs:>8} {n:>6} {pnl:>+10,.0f} {wr:>6.1f}% {pf:>5.02f}{cur}")

    # ===== 综合TOP搜索 =====
    print(f"\n{'='*80}")
    print("📊 TOP 10 最优策略参数组合")
    print(f"{'='*80}")
    
    results = []
    for mm in [2, 3, 5]:
        for at in [2, 3, 5]:
            for cd_m in [10, 15, 20]:
                for fp in [0.01, 0.02, 0.03]:
                    p = {'mega_mult':mm, 'accel_thresh':at, 'sustained_ratio':0.35, 'cooldown':cd_m, 'floor_pct':fp}
                    total_closed = []; total_sigs = 0
                    for td in days:
                        sigs = generate_signals(all_data[td]['timelines'], names, p)
                        total_sigs += len(sigs)
                        r = simulate_trades(sigs, all_data[td]['ticks'])
                        total_closed.extend(r['closed'])
                    n=len(total_closed)
                    if n<3: continue
                    pnl=sum((t['exit']-t['entry'])*t['qty'] for t in total_closed)
                    wins=sum(1 for t in total_closed if (t['exit']-t['entry'])*t['qty']>0)
                    wr=wins/n*100 if n else 0
                    gw=sum((t['exit']-t['entry'])*t['qty'] for t in total_closed if (t['exit']-t['entry'])*t['qty']>0)
                    gl=abs(sum((t['exit']-t['entry'])*t['qty'] for t in total_closed if (t['exit']-t['entry'])*t['qty']<=0))
                    pf=gw/gl if gl>0 else 999
                    results.append({'mm':mm,'at':at,'cd':cd_m,'fp':fp,'sigs':total_sigs,'n':n,'pnl':pnl,'wr':wr,'pf':pf})
    
    results.sort(key=lambda x: x['pnl'], reverse=True)
    print(f"{'#':>3} {'mega':>5} {'accel':>6} {'冷却':>5} {'地板':>5} {'信号':>6} {'交易':>5} {'P&L':>10} {'胜率':>7} {'PF':>6}")
    print("-"*75)
    for i, r in enumerate(results[:10]):
        print(f"{i+1:>3} {r['mm']:>4.0f}x {r['at']:>5.0f}x {r['cd']:>4}m {r['fp']*100:>4.1f}% {r['sigs']:>6} {r['n']:>5} {r['pnl']:>+10,.0f} {r['wr']:>6.1f}% {r['pf']:>5.02f}")
    
    # 当前 vs 最优
    cur_r = next((r for r in results if r['mm']==3 and r['at']==3 and r['cd']==15 and r['fp']==0.02), None)
    best = results[0] if results else None
    print(f"\n  当前: mega=3x accel=3x 冷却15m 地板2% → P&L: {cur_r['pnl']:+,.0f} 胜率{cur_r['wr']:.1f}% PF{cur_r['pf']:.2f}" if cur_r else "  当前参数未在搜索范围")
    if best:
        print(f"  最优: mega={best['mm']}x accel={best['at']}x 冷却{best['cd']}m 地板{best['fp']*100:.1f}% → P&L: {best['pnl']:+,.0f} 胜率{best['wr']:.1f}% PF{best['pf']:.2f}")
    
    print(f"\n共测试 {len(results)} 种有效参数组合")
