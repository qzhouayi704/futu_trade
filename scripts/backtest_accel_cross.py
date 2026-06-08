import sqlite3
from collections import defaultdict
DB = '/opt/futu_trade_sys/simple_trade/data/trade.db'
MIN_DAILY_TURNOVER = 100; CONFLICT_WINDOW = 15; SCAN_INTERVAL = 3

def load_all_data():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    days = [d['trade_date'] for d in conn.execute("SELECT DISTINCT trade_date FROM ticker_data WHERE trade_date>='2026-06-01' AND trade_date<='2026-06-05' ORDER BY trade_date").fetchall()]
    names = {r['code']:r['name'] for r in conn.execute("SELECT code, name FROM stocks").fetchall()}
    all_data = {}
    for td in days:
        rows = conn.execute("SELECT stock_code, substr(datetime(timestamp/1000, 'unixepoch', '+8 hours'), 12, 5) as minute, direction, SUM(turnover) as tv, AVG(price) as ap FROM ticker_data WHERE trade_date=? GROUP BY stock_code, minute, direction ORDER BY stock_code, minute", (td,)).fetchall()
        stock_minutes = defaultdict(lambda: defaultdict(lambda: {'buy':0,'sell':0,'price':0,'pn':0}))
        for r in rows:
            code=r['stock_code']; m=r['minute']; d=r['direction']; tv=float(r['tv'] or 0); ap=float(r['ap'] or 0)
            if not ('09:15'<=m<='16:10'): continue
            e=stock_minutes[code][m]
            if d=='BUY': e['buy']+=tv
            elif d=='SELL': e['sell']+=tv
            if ap>0: e['price']+=ap; e['pn']+=1
        stock_timelines = {}
        for code, mins in stock_minutes.items():
            tl=[]; cb=cs=0
            for m in sorted(mins.keys()):
                e=mins[m]; cb+=e['buy']; cs+=e['sell']; net=e['buy']-e['sell']
                price=round(e['price']/e['pn'],3) if e['pn']>0 else 0
                tl.append({'time':m,'net':round(net/10000,1),'cum_net':round((cb-cs)/10000,1),'price':price,'turnover':round((e['buy']+e['sell'])/10000,1)})
            tvs=[p['turnover'] for p in tl if p['turnover']>0]
            avg_tv=sum(tvs)/len(tvs) if tvs else 0; day_total=sum(p['turnover'] for p in tl)
            if day_total>=MIN_DAILY_TURNOVER and len(tl)>=10:
                stock_timelines[code]={'tl':tl,'avg_tv':avg_tv,'day_total':day_total}
        ticks_raw=conn.execute("SELECT stock_code,price,timestamp FROM ticker_data WHERE trade_date=? ORDER BY timestamp",(td,)).fetchall()
        ticks=defaultdict(list)
        for t in ticks_raw: ticks[t['stock_code']].append({'price':float(t['price']),'ts':int(t['timestamp'])})
        all_data[td]={'timelines':stock_timelines,'ticks':dict(ticks)}
    conn.close()
    return days, all_data, names

def generate_signals(timelines, names, params):
    mm=params['mega_mult']; at=params['accel_thresh']; cd=params['cooldown']; fp=params['floor_pct']
    signals=[]
    for code,data in timelines.items():
        tl=data['tl']; avg_tv=data['avg_tv']; day_total=data['day_total']; name=names.get(code,code)
        mega_floor=max(50,day_total*fp); accel_min=mega_floor*0.5
        abs_nets=[abs(p['net']) for p in tl if p['net']!=0]
        avg_abs_net=sum(abs_nets)/len(abs_nets) if abs_nets else avg_tv
        dynamic_mega=max(mega_floor,avg_abs_net*mm)
        state={'cd':{},'recent':[]}
        for i,pt in enumerate(tl):
            def can(st,red):
                if st in state['cd'] and i-state['cd'][st]<cd: return False
                cut=max(0,i-CONFLICT_WINDOW)
                for _,rr,ri in state['recent']:
                    if ri>=cut and (red!=rr): return False
                return True
            if pt['net']<-dynamic_mega and can('mega_sell',True):
                state['cd']['mega_sell']=i; state['recent'].append((pt['time'],True,i))
                signals.append({'time':pt['time'],'code':code,'name':name,'type':'mega_sell','red':True,'price':pt['price']})
            if pt['net']>dynamic_mega and can('mega_buy',False):
                state['cd']['mega_buy']=i; state['recent'].append((pt['time'],False,i))
                signals.append({'time':pt['time'],'code':code,'name':name,'type':'mega_buy','red':False,'price':pt['price']})
            if i%SCAN_INTERVAL==0 and i>0 and i>=6:
                r3=sum(tl[j]['net'] for j in range(i-2,i+1))
                p3=sum(tl[j]['net'] for j in range(i-5,i-2))
                if p3>0 and r3>p3*at and r3>accel_min and can('accel_in',False):
                    state['cd']['accel_in']=i; state['recent'].append((pt['time'],False,i))
                    signals.append({'time':pt['time'],'code':code,'name':name,'type':'accel_in','red':False,'price':pt['price']})
            state['recent']=[(t,r,ri) for t,r,ri in state['recent'] if ri>=max(0,i-30)]
    return sorted(signals, key=lambda s: s['time'])

def pt(t):
    try: p=t.split(':'); return int(p[0])*3600+int(p[1])*60
    except: return 0

def simulate(signals, ticks):
    cap=100000; pos={}; closed=[]; cd={}; pending=defaultdict(list)
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
        inv=cap*0.70; qty=int(inv*0.50/price)
        if qty<=0: continue
        entry=price
        if code in ticks:
            for tk in ticks[code]:
                tks=(tk['ts']/1000)%86400 if tk['ts']>1e10 else tk['ts']
                if tks>csec: entry=tk['price']; break
        cost=entry*qty
        if cost>cap: continue
        cap-=cost; pos[code]={'code':code,'name':sig['name'],'entry':entry,'qty':qty,'peak':entry,'trail':False}
        cd[code]=csec+1800
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
    wins=sum(1 for t in closed if (t['exit']-t['entry'])*t['qty']>0) if n else 0
    wr=wins/n*100 if n else 0
    gw=sum((t['exit']-t['entry'])*t['qty'] for t in closed if (t['exit']-t['entry'])*t['qty']>0)
    gl=abs(sum((t['exit']-t['entry'])*t['qty'] for t in closed if (t['exit']-t['entry'])*t['qty']<=0))
    pf=gw/gl if gl>0 else 999
    return {'pnl':pnl,'trades':n,'wr':wr,'pf':pf,'closed':closed}

if __name__=='__main__':
    print("加载数据..."); days,all_data,names=load_all_data()
    print(f"日期: {days}\n")
    print("="*85)
    print("ACCEL_THRESHOLD × MEGA_MULTIPLIER 全交叉扫描 (含1.5x)")
    print("="*85)
    print(f"{'mega':>5} {'accel':>6} {'信号':>6} {'mega_buy':>9} {'accel_in':>9} {'交易':>5} {'P&L':>10} {'胜率':>7} {'PF':>6}")
    print("-"*75)
    
    results=[]
    for mm in [2, 3, 5, 8]:
        for at in [1.5, 2.0, 2.5, 3.0, 5.0]:
            total_closed=[]; total_sigs=[]; total_mb=0; total_ai=0
            for td in days:
                sigs=generate_signals(all_data[td]['timelines'],names,{'mega_mult':mm,'accel_thresh':at,'cooldown':15,'floor_pct':0.02})
                total_sigs.extend(sigs)
                total_mb+=sum(1 for s in sigs if s['type']=='mega_buy')
                total_ai+=sum(1 for s in sigs if s['type']=='accel_in')
                r=simulate(sigs,all_data[td]['ticks'])
                total_closed.extend(r['closed'])
            n=len(total_closed)
            pnl=sum((t['exit']-t['entry'])*t['qty'] for t in total_closed)
            wins=sum(1 for t in total_closed if (t['exit']-t['entry'])*t['qty']>0) if n else 0
            wr=wins/n*100 if n else 0
            gw=sum((t['exit']-t['entry'])*t['qty'] for t in total_closed if (t['exit']-t['entry'])*t['qty']>0)
            gl=abs(sum((t['exit']-t['entry'])*t['qty'] for t in total_closed if (t['exit']-t['entry'])*t['qty']<=0))
            pf=gw/gl if gl>0 else 999
            cur=" ← 当前" if mm==3 and at==3.0 else ""
            print(f"{mm:>4}x {at:>5.1f}x {len(total_sigs):>6} {total_mb:>9} {total_ai:>9} {n:>5} {pnl:>+10,.0f} {wr:>6.1f}% {pf:>5.2f}{cur}")
            results.append({'mm':mm,'at':at,'n':n,'pnl':pnl,'wr':wr,'pf':pf,'mb':total_mb,'ai':total_ai})
        print()
    
    results.sort(key=lambda x: x['pnl'], reverse=True)
    print("\nTOP 5:")
    for i,r in enumerate(results[:5]):
        print(f"  {i+1}. mega={r['mm']}x accel={r['at']}x → P&L:{r['pnl']:+,.0f} 胜率{r['wr']:.0f}% PF{r['pf']:.2f} ({r['n']}笔)")
