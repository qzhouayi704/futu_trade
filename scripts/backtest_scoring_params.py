#!/usr/bin/env python3
"""端到端评分参数回测: tick信号 + TREND评分过滤 + 逐笔交易模拟
从ticker_data重建分钟数据 → 生成sniper信号 → 用kline指标评分过滤 → tick级别交易"""
import sqlite3
from collections import defaultdict

DB = '/opt/futu_trade_sys/simple_trade/data/trade.db'
# 已优化的sniper参数
MEGA_MULT = 5; ACCEL_THRESH = 1.5; COOLDOWN = 15; FLOOR_PCT = 0.02
SCAN_INTERVAL = 3; CONFLICT_WINDOW = 15

def load_kline_indicators():
    """从kline_data计算每只股票的TREND指标"""
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    rows = c.execute("""SELECT stock_code, substr(time_key,1,10) as td,
        open_price, close_price, high_price, low_price, volume, turnover
        FROM kline_data WHERE time_key >= '2026-05-20' ORDER BY stock_code, time_key""").fetchall()
    c.close()
    stock_bars = defaultdict(list)
    for r in rows:
        stock_bars[r['stock_code']].append({
            'date':r['td'],'open':float(r['open_price']),'close':float(r['close_price']),
            'high':float(r['high_price']),'low':float(r['low_price']),'vol':int(r['volume'])})
    # 为每只股票的每天计算指标
    indicators = {}  # {(stock_code, date): {...}}
    for code, bars in stock_bars.items():
        for i in range(5, len(bars)):
            b = bars[i]
            c5 = bars[i-5]['close']
            change_5d = (b['close']-c5)/c5*100 if c5>0 else 0
            amp = (b['high']-b['low'])/b['open']*100 if b['open']>0 else 0
            avg_vol = sum(bars[j]['vol'] for j in range(i-5,i))/5
            vol_ratio = b['vol']/avg_vol if avg_vol>0 else 1
            lb = max(0,i-19)
            h20=max(bars[j]['high'] for j in range(lb,i+1))
            l20=min(bars[j]['low'] for j in range(lb,i+1))
            kline_pos = (b['close']-l20)/(h20-l20) if h20!=l20 else 0.5
            prev = bars[i-1]
            prev_change = abs((prev['close']-prev['open'])/prev['open']*100) if prev['open']>0 else 0
            indicators[(code, b['date'])] = {
                'change_5d':change_5d,'amplitude':amp,'vol_ratio':vol_ratio,
                'kline_pos':kline_pos,'prev_change':prev_change}
    return indicators

def load_tick_data():
    """加载tick数据构建分钟时间线"""
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    days = [d['trade_date'] for d in c.execute(
        "SELECT DISTINCT trade_date FROM ticker_data WHERE trade_date>='2026-06-01' AND trade_date<='2026-06-05' ORDER BY trade_date").fetchall()]
    names = {r['code']:r['name'] for r in c.execute("SELECT code, name FROM stocks").fetchall()}
    all_data = {}
    for td in days:
        rows = c.execute("""SELECT stock_code, substr(datetime(timestamp/1000,'unixepoch','+8 hours'),12,5) as minute,
            direction, SUM(turnover) as tv, AVG(price) as ap
            FROM ticker_data WHERE trade_date=? GROUP BY stock_code, minute, direction ORDER BY stock_code, minute""", (td,)).fetchall()
        stock_minutes = defaultdict(lambda: defaultdict(lambda: {'buy':0,'sell':0,'price':0,'pn':0}))
        for r in rows:
            code=r['stock_code'];m=r['minute'];d=r['direction'];tv=float(r['tv'] or 0);ap=float(r['ap'] or 0)
            if not ('09:15'<=m<='16:10'): continue
            e=stock_minutes[code][m]
            if d=='BUY': e['buy']+=tv
            elif d=='SELL': e['sell']+=tv
            if ap>0: e['price']+=ap; e['pn']+=1
        # 计算ticker_power (逐笔买卖力量)
        ticker_powers = {}
        for code, mins in stock_minutes.items():
            total_buy = sum(e['buy'] for e in mins.values())
            total_sell = sum(e['sell'] for e in mins.values())
            bsr = total_buy/total_sell if total_sell>0 else 1.0
            ticker_powers[code] = bsr - 1.0  # power = BSR - 1
        
        stock_timelines = {}
        for code, mins in stock_minutes.items():
            tl=[]; cb=cs=0
            for m in sorted(mins.keys()):
                e=mins[m]; cb+=e['buy']; cs+=e['sell']; net=e['buy']-e['sell']
                price=round(e['price']/e['pn'],3) if e['pn']>0 else 0
                tl.append({'time':m,'net':round(net/10000,1),'cum_net':round((cb-cs)/10000,1),'price':price,'turnover':round((e['buy']+e['sell'])/10000,1)})
            tvs=[p['turnover'] for p in tl if p['turnover']>0]
            avg_tv=sum(tvs)/len(tvs) if tvs else 0; day_total=sum(p['turnover'] for p in tl)
            if day_total>=100 and len(tl)>=10:
                stock_timelines[code]={'tl':tl,'avg_tv':avg_tv,'day_total':day_total,'ticker_power':ticker_powers.get(code,0)}
        ticks_raw=c.execute("SELECT stock_code,price,timestamp FROM ticker_data WHERE trade_date=? ORDER BY timestamp",(td,)).fetchall()
        ticks=defaultdict(list)
        for t in ticks_raw: ticks[t['stock_code']].append({'price':float(t['price']),'ts':int(t['timestamp'])})
        all_data[td]={'timelines':stock_timelines,'ticks':dict(ticks)}
    c.close()
    return days, all_data, names

def generate_signals(timelines, names):
    """用已优化的sniper参数生成信号"""
    signals=[]
    for code,data in timelines.items():
        tl=data['tl']; avg_tv=data['avg_tv']; day_total=data['day_total']; name=names.get(code,code)
        mega_floor=max(50,day_total*FLOOR_PCT); accel_min=mega_floor*0.5
        abs_nets=[abs(p['net']) for p in tl if p['net']!=0]
        avg_abs_net=sum(abs_nets)/len(abs_nets) if abs_nets else avg_tv
        dynamic_mega=max(mega_floor,avg_abs_net*MEGA_MULT)
        state={'cd':{},'recent':[]}
        for i,pt in enumerate(tl):
            def can(st,red):
                if st in state['cd'] and i-state['cd'][st]<COOLDOWN: return False
                cut=max(0,i-CONFLICT_WINDOW)
                for _,rr,ri in state['recent']:
                    if ri>=cut and (red!=rr): return False
                return True
            if pt['net']<-dynamic_mega and can('mega_sell',True):
                state['cd']['mega_sell']=i; state['recent'].append((pt['time'],True,i))
                signals.append({'time':pt['time'],'code':code,'name':name,'type':'mega_sell','price':pt['price']})
            if pt['net']>dynamic_mega and can('mega_buy',False):
                state['cd']['mega_buy']=i; state['recent'].append((pt['time'],False,i))
                signals.append({'time':pt['time'],'code':code,'name':name,'type':'mega_buy','price':pt['price']})
            if i%SCAN_INTERVAL==0 and i>0 and i>=6:
                r3=sum(tl[j]['net'] for j in range(i-2,i+1))
                p3=sum(tl[j]['net'] for j in range(i-5,i-2))
                if p3>0 and r3>p3*ACCEL_THRESH and r3>accel_min and can('accel_in',False):
                    state['cd']['accel_in']=i; state['recent'].append((pt['time'],False,i))
                    signals.append({'time':pt['time'],'code':code,'name':name,'type':'accel_in','price':pt['price']})
            state['recent']=[(t,r,ri) for t,r,ri in state['recent'] if ri>=max(0,i-30)]
    return sorted(signals, key=lambda s: s['time'])

def score_range(cfg, value):
    if value is None: return cfg.get('default',0)
    opt=cfg['optimal_range']; mrg=cfg['marginal_range']
    if opt[0]<=value<=opt[1]: return cfg['max_score']
    if mrg[0]<=value<=mrg[1]: return int(cfg['max_score']*0.6)
    return 0

def score_tiered(cfg, value):
    if value is None: return cfg.get('default',0)
    for thresh,score in cfg['tiers']:
        if value>=thresh: return score
    return 0

def score_stock(kline_ind, ticker_power, config):
    """评分一只股票"""
    if not kline_ind: return 0
    total = 0
    total += score_range(config['change_5d'], kline_ind['change_5d'])
    total += score_range(config['amplitude'], kline_ind['amplitude'])
    total += score_tiered(config['vol_ratio'], kline_ind['vol_ratio'])
    total += score_tiered(config['ticker_power'], ticker_power)
    total += score_range(config['kline_pos'], kline_ind['kline_pos'])
    pc = kline_ind['prev_change']
    if pc>=12: total+=1
    elif pc>=7: total+=3
    elif pc>=3: total+=5
    return total

def pt(t):
    try: p=t.split(':'); return int(p[0])*3600+int(p[1])*60
    except: return 0

def simulate(signals, ticks, timelines, kline_indicators, trade_date, config, passing_score):
    """带评分过滤的tick级交易模拟"""
    cap=100000; pos={}; closed=[]; cd={}; pending=defaultdict(list); filtered=0
    for sig in signals:
        code=sig['code']; st=sig['type']; price=sig['price']; stime=sig['time']
        if price<=0: continue
        if st=='mega_sell':
            if code in pos:
                pp=pos.pop(code); pp['exit']=price; pp['reason']='mega_sell'; cap+=price*pp['qty']; closed.append(pp)
                cd[code]=pt(stime)+1800
            continue
        pending[code].append({'ts':pt(stime),'type':st,'price':price,'name':sig['name']})
        if st!='mega_buy': continue
        csec=pt(stime)
        if code in cd and csec<cd[code]: continue
        recent=[s for s in pending[code] if 0<=(csec-s['ts'])<1200]
        types=set(s['type'] for s in recent if s['type'] in ('mega_buy','accel_in'))
        if len(types)<2 or len(pos)>=2: continue
        
        # ===== TREND评分过滤 =====
        tp = timelines[code]['ticker_power'] if code in timelines else 0
        ki = kline_indicators.get((code, trade_date))
        score = score_stock(ki, tp, config)
        if score < passing_score:
            filtered += 1
            continue
        # ===== 评分通过，执行交易 =====
        
        inv=cap*0.70; qty=int(inv*0.50/price)
        if qty<=0: continue
        # tick级入场: 找信号后第一个tick
        entry=price
        if code in ticks:
            for tk in ticks[code]:
                tks=(tk['ts']/1000)%86400 if tk['ts']>1e10 else tk['ts']
                if tks>csec: entry=tk['price']; break
        cost=entry*qty
        if cost>cap: continue
        cap-=cost; pos[code]={'code':code,'name':sig['name'],'entry':entry,'qty':qty,'peak':entry,'trail':False,'score':score}
        cd[code]=csec+1800
    
    # tick级止损止盈
    for code in list(pos.keys()):
        pp=pos[code]
        if code in ticks:
            for tk in ticks[code]:
                pr=tk['price']
                if pr>pp['peak']: pp['peak']=pr
                pnl_pct=(pr/pp['entry']-1)*100
                if pnl_pct<=-5: pp['exit']=pr; pp['reason']='sl'; cap+=pr*pp['qty']; closed.append(pp); del pos[code]; break
                if not pp['trail'] and pnl_pct>=5: pp['trail']=True
                if pp['trail'] and (1-pr/pp['peak'])*100>=2:
                    pp['exit']=pr; pp['reason']='tp'; cap+=pr*pp['qty']; closed.append(pp); del pos[code]; break
    for code in list(pos.keys()):
        pp=pos[code]; pp['exit']=ticks[code][-1]['price'] if code in ticks and ticks[code] else pp['entry']
        pp['reason']='eod'; cap+=pp['exit']*pp['qty']; closed.append(pp)
    
    n=len(closed); pnl=cap-100000
    wins=sum(1 for t in closed if (t['exit']-t['entry'])*t['qty']>0)
    wr=wins/n*100 if n else 0
    gw=sum((t['exit']-t['entry'])*t['qty'] for t in closed if (t['exit']-t['entry'])*t['qty']>0)
    gl=abs(sum((t['exit']-t['entry'])*t['qty'] for t in closed if (t['exit']-t['entry'])*t['qty']<=0))
    pf=gw/gl if gl>0 else 999
    return {'pnl':pnl,'trades':n,'wr':wr,'pf':pf,'filtered':filtered,'closed':closed}

# 当前TREND_CONFIG
CURRENT_CONFIG = {
    'change_5d': {'max_score': 20, 'optimal_range': (-2.0, 15.0), 'marginal_range': (-5.0, 25.0), 'default': 0},
    'amplitude': {'max_score': 20, 'optimal_range': (5.0, 20.0), 'marginal_range': (3.0, 50.0), 'default': 0},
    'vol_ratio': {'max_score': 25, 'tiers': [(5.0, 20), (3.0, 25), (2.0, 18), (1.5, 12), (1.0, 5)], 'default': 0},
    'ticker_power': {'max_score': 25, 'tiers': [(0.5, 25), (0.2, 18), (0.0, 8)], 'default': 8},
    'kline_pos': {'max_score': 5, 'optimal_range': (0.0, 1.0), 'marginal_range': (0.0, 1.0), 'default': 5},
}

def make_variant(amp_opt=None, vr_tiers=None, c5d_opt=None, tp_tiers=None):
    cfg = dict(CURRENT_CONFIG)
    if amp_opt: cfg['amplitude'] = dict(cfg['amplitude']); cfg['amplitude']['optimal_range'] = amp_opt
    if vr_tiers: cfg['vol_ratio'] = dict(cfg['vol_ratio']); cfg['vol_ratio']['tiers'] = vr_tiers
    if c5d_opt: cfg['change_5d'] = dict(cfg['change_5d']); cfg['change_5d']['optimal_range'] = c5d_opt
    if tp_tiers: cfg['ticker_power'] = dict(cfg['ticker_power']); cfg['ticker_power']['tiers'] = tp_tiers
    return cfg

if __name__ == '__main__':
    print("加载kline指标...")
    kline_ind = load_kline_indicators()
    print(f"  {len(kline_ind)} 条指标")
    print("\n加载tick数据...")
    days, all_data, names = load_tick_data()
    print(f"  {len(days)} 天: {days}")
    
    def run_sweep(config, ps, label=""):
        total_closed=[]; total_filtered=0
        for td in days:
            sigs = generate_signals(all_data[td]['timelines'], names)
            r = simulate(sigs, all_data[td]['ticks'], all_data[td]['timelines'], kline_ind, td, config, ps)
            total_closed.extend(r['closed']); total_filtered+=r['filtered']
        n=len(total_closed)
        pnl=sum((t['exit']-t['entry'])*t['qty'] for t in total_closed)
        wins=sum(1 for t in total_closed if (t['exit']-t['entry'])*t['qty']>0)
        wr=wins/n*100 if n else 0
        gw=sum((t['exit']-t['entry'])*t['qty'] for t in total_closed if (t['exit']-t['entry'])*t['qty']>0)
        gl=abs(sum((t['exit']-t['entry'])*t['qty'] for t in total_closed if (t['exit']-t['entry'])*t['qty']<=0))
        pf=gw/gl if gl>0 else 999
        return {'pnl':pnl,'n':n,'wr':wr,'pf':pf,'filtered':total_filtered,'label':label}
    
    # ===== 基准: 无评分过滤 =====
    print("\n" + "="*80)
    print("📊 基准对比: 有/无评分过滤")
    print("="*80)
    r0 = run_sweep(CURRENT_CONFIG, 0, "无过滤")
    r60 = run_sweep(CURRENT_CONFIG, 60, "当前(PS=60)")
    print(f"{'配置':>15} {'交易':>5} {'P&L':>10} {'胜率':>7} {'PF':>6} {'过滤':>5}")
    print("-"*55)
    for r in [r0, r60]:
        print(f"  {r['label']:>12} {r['n']:>5} {r['pnl']:>+10,.0f} {r['wr']:>6.1f}% {r['pf']:>5.2f} {r['filtered']:>5}")
    
    # ===== 扫描1: PASSING_SCORE =====
    print("\n" + "="*80)
    print("📊 扫描1: PASSING_SCORE (评分及格线)")
    print("="*80)
    print(f"{'及格线':>7} {'交易':>5} {'P&L':>10} {'胜率':>7} {'PF':>6} {'过滤数':>6}")
    print("-"*50)
    for ps in [0, 30, 40, 50, 55, 60, 65, 70]:
        r = run_sweep(CURRENT_CONFIG, ps)
        cur = " ← 当前" if ps==60 else (" ← 无过滤" if ps==0 else "")
        print(f"  {ps:>5} {r['n']:>5} {r['pnl']:>+10,.0f} {r['wr']:>6.1f}% {r['pf']:>5.2f} {r['filtered']:>6}{cur}")
    
    # ===== 扫描2: 振幅区间 =====
    print("\n" + "="*80)
    print("📊 扫描2: AMPLITUDE 振幅区间 (PS=60)")
    print("="*80)
    print(f"{'区间':>12} {'交易':>5} {'P&L':>10} {'胜率':>7} {'PF':>6}")
    print("-"*45)
    for lo,hi in [(3,15),(5,20),(8,25),(10,30),(5,30)]:
        r = run_sweep(make_variant(amp_opt=(lo,hi)), 60)
        cur = " ← 当前" if (lo,hi)==(5,20) else ""
        print(f"  ({lo:>2},{hi:>2})% {r['n']:>5} {r['pnl']:>+10,.0f} {r['wr']:>6.1f}% {r['pf']:>5.2f}{cur}")
    
    # ===== 扫描3: 量比 =====
    print("\n" + "="*80)
    print("📊 扫描3: VOL_RATIO 量比阈值 (PS=60)")
    print("="*80)
    print(f"{'配置':>12} {'交易':>5} {'P&L':>10} {'胜率':>7} {'PF':>6}")
    print("-"*45)
    vr_opts = [
        ("宽松", [(3.0,20),(2.0,25),(1.5,18),(1.0,12),(0.5,5)]),
        ("当前", [(5.0,20),(3.0,25),(2.0,18),(1.5,12),(1.0,5)]),
        ("严格", [(8.0,20),(5.0,25),(3.0,18),(2.0,12),(1.5,5)]),
    ]
    for name, tiers in vr_opts:
        r = run_sweep(make_variant(vr_tiers=tiers), 60)
        cur = " ← 当前" if name=="当前" else ""
        print(f"  {name:>8} {r['n']:>5} {r['pnl']:>+10,.0f} {r['wr']:>6.1f}% {r['pf']:>5.2f}{cur}")
    
    # ===== 扫描4: ticker_power阈值 =====
    print("\n" + "="*80)
    print("📊 扫描4: TICKER_POWER 逐笔力量阈值 (PS=60)")
    print("="*80)
    print(f"{'配置':>12} {'交易':>5} {'P&L':>10} {'胜率':>7} {'PF':>6}")
    print("-"*45)
    tp_opts = [
        ("宽松", [(0.3,25),(0.1,18),(0.0,8)]),
        ("当前", [(0.5,25),(0.2,18),(0.0,8)]),
        ("严格", [(0.8,25),(0.5,18),(0.2,8)]),
    ]
    for name, tiers in tp_opts:
        r = run_sweep(make_variant(tp_tiers=tiers), 60)
        cur = " ← 当前" if name=="当前" else ""
        print(f"  {name:>8} {r['n']:>5} {r['pnl']:>+10,.0f} {r['wr']:>6.1f}% {r['pf']:>5.2f}{cur}")
    
    print("\n✅ 回测完成 — 所有交易均基于逐笔tick数据，信号后第一个tick入场，tick级别5%止损/2%追踪止盈")
