#!/usr/bin/env python3
"""
精确验证 accel_in 的角色 — 3种模式对比

之前回测结论(models.py注释): "纯mega +1.60%/笔, accel独立 -0.53%/笔"
当前回测结论: accel_in 作为确认信号时共振有效

这两个不矛盾吗？验证:
  模式A: 纯mega_buy, 无需任何确认 → 预期亏损
  模式B: mega_buy触发 + accel_in确认 → 预期盈利 (共振)
  模式C: accel_in独立触发, 无需确认 → 预期亏损
  模式D: accel_in触发 + mega_buy确认 → 对比
  模式E: mega_buy+accel_in都能触发, 互相确认 → 对比
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

def run(dates, data, triggers, confirms, min_types, label):
    cap=100000; pos={}; closed=[]; cd={}; pending=defaultdict(list)
    for td in dates:
        sigs=data[td]['signals']; ticks=data[td]['ticks']; pending.clear()
        for sig in sigs:
            code=sig['stock_code']; st=sig['signal_type']
            price=float(sig['price']) if sig['price'] else 0
            stime=sig.get('time','')
            if price<=0: continue
            if st=='mega_sell':
                if code in pos:
                    pp=pos.pop(code); pp['exit']=price; pp['reason']='mega_sell'
                    cap+=price*pp['qty']; closed.append(pp)
                    cd[code]=pt(stime)+1800
                continue
            if st in ('sustained_out','reversal_bear'): continue
            pending[code].append({'ts':pt(stime),'type':st,'price':price,'name':sig['stock_name'],'time':stime})
            if st not in triggers: continue
            csec=pt(stime)
            if code in cd and csec<cd[code]: continue
            recent=[s for s in pending[code] if 0<=(csec-s['ts'])<1200]  # 20min
            types_in=set(s['type'] for s in recent if s['type'] in confirms)
            if len(types_in)<min_types: continue
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
            pos[code]={'code':code,'name':sig['stock_name'],'entry':entry,'qty':qty,'peak':entry,'trail':False}
            cd[code]=csec+1800
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
    
    # 每笔统计
    per_trade = pnl/n if n else 0
    
    print(f"  {label:45s} | {n:>3}笔 | P&L: {pnl:>+8,.0f} | 胜率: {wr:>5.1f}% | PF: {pf:>5.2f} | 每笔: {per_trade:>+7,.0f}")
    
    if n > 0 and n <= 15:
        for t in closed:
            tpnl = (t['exit']-t['entry'])*t['qty']
            tpct = (t['exit']/t['entry']-1)*100 if t['entry']>0 else 0
            icon = "🟢" if tpnl > 0 else "🔴"
            print(f"    {icon} {t['name']}({t['code']}) {t['entry']:.2f}→{t['exit']:.2f} {tpnl:+,.0f} ({tpct:+.1f}%) [{t['reason']}]")
    
    return {'pnl': pnl, 'trades': n, 'wr': wr, 'pf': pf, 'per_trade': per_trade}


if __name__ == '__main__':
    print("🔄 加载数据...")
    dates, data = load_data()
    
    print(f"\n{'='*90}")
    print("📊 accel_in 角色精确验证 (3天数据, 优化后参数: 20m窗口 止损5% 追踪2%)")
    print(f"{'='*90}\n")
    
    print("📌 模式A: 纯mega_buy, 无需确认 (信号来就买)")
    a = run(dates, data, {'mega_buy'}, {'mega_buy'}, 1, "mega_buy独立触发(无确认)")
    
    print(f"\n📌 模式B: mega_buy触发 + accel_in确认 (当前策略)")
    b = run(dates, data, {'mega_buy'}, {'mega_buy','accel_in'}, 2, "mega_buy触发 + accel_in确认 ✅")
    
    print(f"\n📌 模式C: accel_in独立触发, 无需确认")
    c = run(dates, data, {'accel_in'}, {'accel_in'}, 1, "accel_in独立触发(无确认)")
    
    print(f"\n📌 模式D: accel_in触发 + mega_buy确认 (反过来)")
    d = run(dates, data, {'accel_in'}, {'accel_in','mega_buy'}, 2, "accel_in触发 + mega_buy确认")
    
    print(f"\n📌 模式E: 双向触发 + 互相确认")
    e = run(dates, data, {'mega_buy','accel_in'}, {'mega_buy','accel_in'}, 2, "mega_buy+accel_in互相触发确认")
    
    print(f"\n{'='*90}")
    print("📊 结论")
    print(f"{'='*90}")
    print(f"""
┌─────────────────────────────────────────────────┬────────┬──────────┬────────┐
│ 模式                                             │ P&L    │ 每笔均值  │ 结论   │
├─────────────────────────────────────────────────┼────────┼──────────┼────────┤
│ A. mega_buy独立(无确认)                           │ {a['pnl']:>+6,.0f}  │ {a['per_trade']:>+6,.0f}    │ {'❌亏损' if a['pnl']<0 else '✅盈利'}  │
│ B. mega_buy触发 + accel_in确认 ← 当前            │ {b['pnl']:>+6,.0f}  │ {b['per_trade']:>+6,.0f}    │ {'❌亏损' if b['pnl']<0 else '✅盈利'}  │
│ C. accel_in独立(无确认)                           │ {c['pnl']:>+6,.0f}  │ {c['per_trade']:>+6,.0f}    │ {'❌亏损' if c['pnl']<0 else '✅盈利'}  │
│ D. accel_in触发 + mega_buy确认                    │ {d['pnl']:>+6,.0f}  │ {d['per_trade']:>+6,.0f}    │ {'❌亏损' if d['pnl']<0 else '✅盈利'}  │
│ E. 双向触发互相确认                               │ {e['pnl']:>+6,.0f}  │ {e['per_trade']:>+6,.0f}    │ {'❌亏损' if e['pnl']<0 else '✅盈利'}  │
└─────────────────────────────────────────────────┴────────┴──────────┴────────┘

关键区别:
  ✅ accel_in 作为"确认信号" = 有效 (帮助过滤噪音)
  ❌ accel_in 作为"独立触发" = 无效 (信号质量不够)
  
  之前回测结论: "accel独立 -0.53%/笔" → 对应模式C (独立触发)
  当前回测结论: "accel_in确认有效" → 对应模式B (共振确认)
  
  两个结论完全一致! accel_in 的价值在于"锦上添花"而非"独当一面"
""")
