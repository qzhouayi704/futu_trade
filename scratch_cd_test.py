#!/usr/bin/env python3
"""冷却时间 + 冲突窗口 参数扫描"""
import sqlite3
from datetime import date

DB_PATH = "/opt/futu_trade_sys/simple_trade/data/trade.db"
TODAY = date.today().isoformat()
FOCUS = ['HK.00981','HK.00100','HK.06651','HK.00992','HK.01879','HK.02631','HK.00068','HK.03033']

KEY_MOMENTS = [
    {'stock': 'HK.00981', 'type': 'red', 'before': '09:45'},
    {'stock': 'HK.00992', 'type': 'green', 'before': '10:00'},
    {'stock': 'HK.00100', 'type': 'red', 'before': '10:00'},
    {'stock': 'HK.06651', 'type': 'green', 'after': '13:30', 'before': '14:30'},
]

def load_minute_data(db, code):
    rows = db.execute("""
        SELECT substr(datetime(timestamp/1000, 'unixepoch', '+8 hours'), 12, 5) as minute,
               direction, SUM(turnover) as tv, AVG(price) as ap
        FROM ticker_data WHERE stock_code=? AND trade_date=?
        GROUP BY minute, direction ORDER BY minute
    """, (code, TODAY)).fetchall()
    minutes = {}
    for minute, d, tv, ap in rows:
        if not ('09:15' <= minute <= '16:10'): continue
        if minute not in minutes: minutes[minute] = {'b':0,'s':0,'p':0,'n':0}
        e = minutes[minute]
        v = float(tv or 0)
        if d == 'BUY': e['b'] += v
        elif d == 'SELL': e['s'] += v
        if ap and float(ap) > 0: e['p'] += float(ap); e['n'] += 1
    tl = []
    cb, cs = 0, 0
    for m in sorted(minutes):
        e = minutes[m]; cb += e['b']; cs += e['s']
        tl.append({'time': m, 'net': round((e['b']-e['s'])/10000,1), 'cum_net': round((cb-cs)/10000,1),
                    'price': round(e['p']/e['n'],3) if e['n']>0 else 0, 'tv': round((e['b']+e['s'])/10000,1)})
    tvs = [p['tv'] for p in tl if p['tv'] > 0]
    return tl, sum(tvs)/len(tvs) if tvs else 0, sum(p['tv'] for p in tl)

def run(tl, avg, dt, cd, cw):
    if len(tl)<10 or avg<=0: return []
    mm = max(5000, dt*0.005)
    ds = max(0.35*avg*20, 3000)
    sigs, cool, prev_d, recent = [], {}, 'neutral', []
    for i, p in enumerate(tl):
        scan = i%3==0 and i>0
        def ok(t, red):
            if t in cool and i-cool[t]<cd: return False
            for r in recent:
                if r[2]>=max(0,i-cw) and ((red and not r[1]) or (not red and r[1])): return False
            return True
        def em(t, red):
            cool[t]=i; s={'time':p['time'],'red':red,'type':t}; sigs.append(s); recent.append((p['time'],red,i))
        if p['net']<-max(mm,avg*15) and ok('ms',True): em('ms',True)
        if p['net']>max(mm,avg*15) and ok('mb',False): em('mb',False)
        if scan:
            cd2 = 'p' if p['cum_net']>0 else 'n' if p['cum_net']<0 else 'x'
            if prev_d=='n' and cd2=='p' and p['cum_net']>5000 and ok('rb',False): em('rb',False)
            if prev_d=='p' and cd2=='n' and p['cum_net']<-5000 and ok('rr',True): em('rr',True)
            if i>=6:
                r3=sum(tl[j]['net'] for j in range(i-2,i+1))
                p3=sum(tl[j]['net'] for j in range(i-5,i-2))
                if p3>0 and r3>p3*8 and r3>3000 and ok('ai',False): em('ai',False)
            if i>=20:
                wn=sum(tl[j]['net'] for j in range(i-19,i+1))
                if wn<-ds and ok('so',True): em('so',True)
            prev_d=cd2
    return sigs

db = sqlite3.connect(DB_PATH)
data = {}
for c in FOCUS:
    t, a, d = load_minute_data(db, c)
    if t: data[c] = (t, a, d)
db.close()

# 测试冷却时间: 10,15,20,25,30,45,60  x  冲突窗口: 0,10,15,20,30
print(f"{'冷却':>4} {'冲突':>4} | {'信号':>4} {'🔴':>3} {'🟢':>3} | {'捕获':>4} | {'特征'}")
print("-" * 75)

best_score, best_cd, best_cw = -1, 0, 0
for cd in [10, 15, 20, 25, 30, 45, 60]:
    for cw in [0, 10, 15, 20, 30]:
        all_sigs = []
        for c, (t, a, d) in data.items():
            for s in run(t, a, d, cd, cw):
                s['stock'] = c
                all_sigs.append(s)
        all_sigs.sort(key=lambda x: x['time'])
        total = len(all_sigs)
        reds = sum(1 for s in all_sigs if s['red'])
        greens = total - reds

        captured = 0
        for km in KEY_MOMENTS:
            for s in all_sigs:
                if s['stock'] != km['stock']: continue
                if (km['type']=='red') != s['red']: continue
                if 'before' in km and s['time'] > km['before']: continue
                if 'after' in km and s['time'] < km['after']: continue
                captured += 1; break

        # 矛盾信号计数：同股票30分钟内出现红绿
        contradictions = 0
        for i, s1 in enumerate(all_sigs):
            for s2 in all_sigs[i+1:]:
                if s2['time'] > s1['time'][:3] + str(int(s1['time'][3:])+30).zfill(2): break
                if s1['stock'] == s2['stock'] and s1['red'] != s2['red']:
                    contradictions += 1

        note = ""
        if total > 40: note += "太多 "
        if total < 10: note += "太少 "
        if captured < 4: note += f"漏{4-captured}个 "
        if contradictions > 0: note += f"矛盾{contradictions} "
        if 15 <= total <= 30 and captured == 4 and contradictions == 0: note += "⭐"

        score = captured*25 - max(0,total-20)*1 - contradictions*10
        if score > best_score: best_score, best_cd, best_cw = score, cd, cw

        print(f"{cd:>4} {cw:>4} | {total:>4} {reds:>3} {greens:>3} | {captured:>4}/4 | {note}")

print(f"\n最优组合: 冷却={best_cd}分钟, 冲突窗口={best_cw}分钟")
