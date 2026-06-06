#!/usr/bin/env python3
"""
策略参数全面扫描 — 涵盖共振规则 + 信号强度 + 交易参数

扫描维度:
  A. 共振规则:
    - 窗口时间: 10/15/20/30 min
    - 确认信号类型: mega_buy+accel_in / mega_buy+accel_in+reversal_bull
    - reversal_bull 是否作为确认
  B. 信号强度:
    - accel_in 是否独立触发(strength 0 vs 50)
    - reversal_bull 是否触发(strength 0 vs 40)
  C. 真实默认参数对比:
    - Sniper通道: 激活10% 止损8% (engine.py L301-302)
    - 资金流通道: 激活5% 止损3% (engine.py L262-264)
    - DataClass默认: 激活5% 止损3% (models.py L137-139)
"""
import sqlite3
from collections import defaultdict

DB = '/opt/futu_trade_sys/simple_trade/data/trade.db'

def load_data():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    days = [d['trade_date'] for d in conn.execute(
        "SELECT DISTINCT trade_date FROM sniper_signals WHERE trade_date>='2026-06-01' ORDER BY trade_date").fetchall()]
    data = {}
    for td in days:
        sigs = [dict(s) for s in conn.execute("SELECT * FROM sniper_signals WHERE trade_date=? ORDER BY time",(td,)).fetchall()]
        ticks_raw = conn.execute("SELECT stock_code,price,timestamp FROM ticker_data WHERE trade_date=? ORDER BY timestamp",(td,)).fetchall()
        ticks = defaultdict(list)
        for t in ticks_raw: ticks[t['stock_code']].append({'price':float(t['price']),'ts':int(t['timestamp'])})
        data[td] = {'signals':sigs, 'ticks':dict(ticks)}
    conn.close()
    return days, data

def pt(t):
    try:
        p=t.split(':'); return int(p[0])*3600+int(p[1])*60+(int(p[2]) if len(p)>2 else 0)
    except: return 0

def run(dates, data, p):
    cap=100000; pos={}; closed=[]; cd={}; pending=defaultdict(list)
    window_sec=p['window']*60; cd_sec=p['cooldown']*60
    confirm_types=p['confirm_types']  # set of types that count as confirmation
    trigger_types=p['trigger_types']  # set of types that trigger resonance check
    
    for td in dates:
        sigs=data[td]['signals']; ticks=data[td]['ticks']; pending.clear()
        for sig in sigs:
            code=sig['stock_code']; st=sig['signal_type']
            price=float(sig['price']) if sig['price'] else 0
            stime=sig.get('time','')
            if price<=0: continue
            
            # mega_sell → auto sell
            if st=='mega_sell':
                if code in pos:
                    pp=pos.pop(code); pp['exit']=price; pp['reason']='mega_sell'
                    cap+=price*pp['qty']; closed.append(pp)
                    cd[code]=pt(stime)+cd_sec
                continue
            if st in ('sustained_out','reversal_bear'): continue
            
            # 缓存
            pending[code].append({'ts':pt(stime),'type':st,'price':price,'name':sig['stock_name'],'time':stime})
            
            # 触发检查
            if st not in trigger_types: continue
            
            csec=pt(stime)
            if code in cd and csec<cd[code]: continue
            
            # 共振
            recent=[s for s in pending[code] if 0<=(csec-s['ts'])<window_sec]
            types_in_window=set(s['type'] for s in recent if s['type'] in confirm_types)
            
            if len(types_in_window) < p['min_types']: continue
            
            if len(pos)>=p['maxp']: continue
            inv=cap*0.70; pc=inv*(1.0/p['maxp']); qty=int(pc/price)
            if qty<=0 or price*qty>cap*0.70: continue
            
            # 入场
            entry=price
            if code in ticks:
                for tk in ticks[code]:
                    tks=(tk['ts']/1000)%86400 if tk['ts']>1e10 else tk['ts']
                    if tks>csec: entry=tk['price']; break
            
            cost=entry*qty
            if cost>cap: continue
            cap-=cost
            pos[code]={'code':code,'name':sig['stock_name'],'entry':entry,'qty':qty,'peak':entry,'trail':False,'time':stime}
            cd[code]=csec+cd_sec
        
        # tick追踪
        tc=[]
        for code,pp in pos.items():
            if code not in ticks: continue
            for tk in ticks[code]:
                pr=tk['price']
                if pr>pp['peak']: pp['peak']=pr
                pnl_pct=(pr/pp['entry']-1)*100
                if pnl_pct<=p['sl']:
                    pp['exit']=pr; pp['reason']='stop_loss'; cap+=pr*pp['qty']; tc.append(code); closed.append(pp); break
                if not pp['trail'] and pnl_pct>=p['act']: pp['trail']=True
                if pp['trail']:
                    dd=(1-pr/pp['peak'])*100
                    if dd>=p['dd']:
                        pp['exit']=pr; pp['reason']='trailing'; cap+=pr*pp['qty']; tc.append(code); closed.append(pp); break
        for c in tc:
            if c in pos: del pos[c]
        
        # 收盘
        for code in list(pos.keys()):
            pp=pos[code]
            pp['exit']=ticks[code][-1]['price'] if code in ticks and ticks[code] else pp['entry']
            pp['reason']='eod'; cap+=pp['exit']*pp['qty']; closed.append(pp)
        pos.clear()
    
    n=len(closed)
    if n==0: return {'pnl':0,'trades':0,'wr':0,'pf':0}
    wins=sum(1 for t in closed if (t['exit']-t['entry'])*t['qty']>0)
    pnl=cap-100000
    gw=sum((t['exit']-t['entry'])*t['qty'] for t in closed if (t['exit']-t['entry'])*t['qty']>0)
    gl=abs(sum((t['exit']-t['entry'])*t['qty'] for t in closed if (t['exit']-t['entry'])*t['qty']<=0))
    pf=gw/gl if gl>0 else 999
    
    # 按退出
    be=defaultdict(lambda:{'c':0,'p':0})
    for t in closed:
        r=t.get('reason','?').split('(')[0]
        be[r]['c']+=1; be[r]['p']+=(t['exit']-t['entry'])*t['qty']
    
    return {'pnl':pnl,'trades':n,'wr':wins/n*100,'pf':pf,'by_exit':dict(be),'closed':closed}


if __name__=='__main__':
    print("🔄 加载数据...")
    dates,data=load_data()
    print(f"  日期: {dates}\n")

    # ============================================================
    # A. 共振规则参数差异
    # ============================================================
    print("="*85)
    print("📊 A. 共振规则: 确认信号类型 × 触发类型 × 窗口")
    print("="*85)
    print(f"{'模式':>20} {'窗口':>5} {'交易':>5} {'P&L':>10} {'胜率':>7} {'PF':>6}")
    print("-"*65)
    
    modes = [
        ("mega仅+accel确认", {'mega_buy'}, {'mega_buy','accel_in'}, 2),
        ("mega仅+accel+rev确认", {'mega_buy'}, {'mega_buy','accel_in','reversal_bull'}, 2),
        ("mega+accel都触发", {'mega_buy','accel_in'}, {'mega_buy','accel_in'}, 2),
        ("纯mega无需确认", {'mega_buy'}, {'mega_buy'}, 1),
        ("mega仅+accel确认(3种)", {'mega_buy'}, {'mega_buy','accel_in','reversal_bull'}, 3),
    ]
    
    for label,triggers,confirms,min_t in modes:
        for w in [10,15,20,30]:
            r=run(dates,data,{
                'window':w,'trigger_types':triggers,'confirm_types':confirms,'min_types':min_t,
                'maxp':2,'sl':-3,'act':5,'dd':3,'cooldown':30,
            })
            print(f"{label:>20} {w:>4}m {r['trades']:>5} {r['pnl']:>+10,.0f} {r['wr']:>6.1f}% {r['pf']:>5.2f}")
        print()

    # ============================================================
    # B. 真实代码的参数矛盾对比
    # ============================================================
    print("="*85)
    print("📊 B. 真实代码参数矛盾: Sniper通道(10%/8%) vs 资金流通道(5%/3%)")
    print("="*85)
    print(f"{'参数集':>25} {'交易':>5} {'P&L':>10} {'胜率':>7} {'PF':>6}")
    print("-"*60)
    
    param_sets = [
        ("DataClass默认(5%/3%/3%)", -3, 5, 3),
        ("Sniper通道(10%/8%/3%)", -8, 10, 3),
        ("资金流通道(5%/3%/3%)", -3, 5, 3),
        ("回测v2(5%/3%/3%)", -3, 5, 3),
        ("宽松(10%/5%/2%)", -5, 10, 2),
        ("极宽松(15%/8%/3%)", -8, 15, 3),
        ("紧凑(3%/2%/1.5%)", -2, 3, 1.5),
        ("最优候选(5%/5%/2%)", -5, 5, 2),
    ]
    
    for label,sl,act,dd in param_sets:
        r=run(dates,data,{
            'window':15,'trigger_types':{'mega_buy'},'confirm_types':{'mega_buy','accel_in'},'min_types':2,
            'maxp':2,'sl':sl,'act':act,'dd':dd,'cooldown':30,
        })
        print(f"{label:>25} {r['trades']:>5} {r['pnl']:>+10,.0f} {r['wr']:>6.1f}% {r['pf']:>5.2f}")

    # ============================================================
    # C. reversal_bull 价值评估
    # ============================================================
    print(f"\n{'='*85}")
    print("📊 C. reversal_bull 是否有价值?")
    print("="*85)
    
    for w in [15,20,30]:
        # 不含reversal_bull
        r1=run(dates,data,{
            'window':w,'trigger_types':{'mega_buy'},'confirm_types':{'mega_buy','accel_in'},'min_types':2,
            'maxp':2,'sl':-5,'act':5,'dd':2,'cooldown':30,
        })
        # 含reversal_bull
        r2=run(dates,data,{
            'window':w,'trigger_types':{'mega_buy'},'confirm_types':{'mega_buy','accel_in','reversal_bull'},'min_types':2,
            'maxp':2,'sl':-5,'act':5,'dd':2,'cooldown':30,
        })
        print(f"  窗口{w:>2}m: 无reversal_bull → {r1['trades']:>2}笔 {r1['pnl']:>+8,.0f} {r1['wr']:>5.1f}% PF{r1['pf']:>.2f}")
        print(f"  窗口{w:>2}m: 含reversal_bull → {r2['trades']:>2}笔 {r2['pnl']:>+8,.0f} {r2['wr']:>5.1f}% PF{r2['pf']:>.2f}")
        print()

    # ============================================================
    # D. 综合最优搜索
    # ============================================================
    print("="*85)
    print("📊 D. TOP 15 综合最优参数组合 (含策略参数)")
    print("="*85)
    
    results=[]
    for w in [10,15,20,30]:
        for triggers in [{'mega_buy'}, {'mega_buy','accel_in'}]:
            for confirms in [{'mega_buy','accel_in'}, {'mega_buy','accel_in','reversal_bull'}]:
                for mint in [1,2]:
                    for maxp in [2,3]:
                        for sl in [-2,-3,-5,-8]:
                            for act in [3,5,8,10]:
                                for dd in [1.5,2,3]:
                                    r=run(dates,data,{
                                        'window':w,'trigger_types':triggers,'confirm_types':confirms,
                                        'min_types':mint,'maxp':maxp,'sl':sl,'act':act,'dd':dd,'cooldown':30,
                                    })
                                    if r['trades']>=3:
                                        trig_s='+'.join(sorted(triggers))
                                        conf_s='+'.join(sorted(confirms))
                                        results.append({
                                            'w':w,'trig':trig_s,'conf':conf_s,'mint':mint,
                                            'maxp':maxp,'sl':sl,'act':act,'dd':dd,**r
                                        })
    
    results.sort(key=lambda x: x['pnl'], reverse=True)
    
    print(f"{'#':>3} {'窗口':>4} {'触发':>15} {'确认':>25} {'≥':>2} {'仓':>2} {'止损':>5} {'激活':>4} {'回撤':>4} {'笔':>3} {'P&L':>10} {'胜率':>6} {'PF':>5}")
    print("-"*110)
    for i,r in enumerate(results[:15]):
        print(f"{i+1:>3} {r['w']:>3}m {r['trig']:>15} {r['conf']:>25} {r['mint']:>2} {r['maxp']:>2} {r['sl']:>4}% {r['act']:>3}% {r['dd']:>3.0f}% "
              f"{r['trades']:>3} {r['pnl']:>+10,.0f} {r['wr']:>5.1f}% {r['pf']:>4.2f}")
    
    # 最差的也看看
    print(f"\n📉 BOTTOM 5 (最差参数组合)")
    print("-"*110)
    for i,r in enumerate(results[-5:]):
        print(f"  {r['w']:>3}m {r['trig']:>15} {r['conf']:>25} {r['mint']:>2} {r['maxp']:>2} {r['sl']:>4}% {r['act']:>3}% {r['dd']:>3.0f}% "
              f"{r['trades']:>3} {r['pnl']:>+10,.0f} {r['wr']:>5.1f}% {r['pf']:>4.02f}")
    
    print(f"\n共测试 {len(results)} 种有效参数组合")
    
    # 当前 vs 最优
    cur=run(dates,data,{
        'window':15,'trigger_types':{'mega_buy'},'confirm_types':{'mega_buy','accel_in'},
        'min_types':2,'maxp':2,'sl':-3,'act':5,'dd':3,'cooldown':30,
    })
    best=results[0]
    print(f"\n  当前: P&L {cur['pnl']:>+8,.0f} | {cur['trades']}笔 | 胜率{cur['wr']:.1f}% | PF{cur['pf']:.2f}")
    print(f"  最优: P&L {best['pnl']:>+8,.0f} | {best['trades']}笔 | 胜率{best['wr']:.1f}% | PF{best['pf']:.2f}")
    print(f"         窗口{best['w']}m 触发:{best['trig']} 确认:{best['conf']} ≥{best['mint']}种 "
          f"仓{best['maxp']} 止损{best['sl']}% 激活{best['act']}% 回撤{best['dd']}%")
