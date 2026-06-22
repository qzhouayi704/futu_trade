#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单日信号质量评估 (read-only)。

对某交易日系统实际发出的 sniper_signals + entry_timing_signals，算每条信号
触发后的前向走势(+30min / 至今或收盘)，并按"从信号时刻到同窗口的全市场中位"
去 beta 得市场相对收益；按信号方向(买盘看涨/卖盘警示看跌)给方向感知命中率。

口径诚实：单日=噪音级；盘中跑则"EOD=至今"、近30min信号无 +30min。仅 SELECT。
用法：python signal_quality_today.py [db] [YYYY-MM-DD]
"""
import sqlite3, sys, bisect, statistics as st
from collections import defaultdict

DB = sys.argv[1] if len(sys.argv) > 1 else "/opt/futu_trade_sys/simple_trade/data/trade.db"
con = sqlite3.connect(DB); cur = con.cursor()
D = sys.argv[2] if len(sys.argv) > 2 else cur.execute("SELECT MAX(trade_date) FROM ticker_data").fetchone()[0]

# 每股每分钟均价
rows = cur.execute(
    "SELECT stock_code, substr(datetime(timestamp/1000,'unixepoch','+8 hours'),12,5) m, AVG(price) "
    "FROM ticker_data WHERE trade_date=? AND price>0 GROUP BY stock_code,m", (D,)).fetchall()
ser = defaultdict(list)
for code, m, ap in rows:
    if '09:25' <= m <= '16:10' and ap:
        ser[code].append((int(m[:2])*60+int(m[3:5]), float(ap)))
for code in ser:
    ser[code].sort()
prep = {code: ([a for a, _ in v], [p for _, p in v]) for code, v in ser.items()}
LAST = max((am[-1] for am, _ in prep.values()), default=0)

def price_at(code, a):
    if code not in prep: return None
    am, pr = prep[code]; i = bisect.bisect_right(am, a)-1
    return pr[i] if i >= 0 else None

def price_ge(code, a):
    if code not in prep: return None
    am, pr = prep[code]; i = bisect.bisect_left(am, a)
    return pr[i] if i < len(am) else None

# 参考池：当日有≥30分钟数据的股票，用于算市场中位
refs = [c for c in prep if len(prep[c][0]) >= 30]
_mc = {}
def mkt(a, horizon):
    """从分钟 a 到 a+horizon(None=至今) 的全市场中位收益。"""
    key = (a, horizon)
    if key in _mc: return _mc[key]
    rr = []
    for c in refs:
        p0 = price_at(c, a)
        p1 = price_ge(c, a+horizon) if horizon else prep[c][1][-1]
        if p0 and p0 > 0 and p1:
            rr.append(p1/p0-1)
    v = st.median(rr) if rr else 0.0
    _mc[key] = v; return v

# 信号方向：+1=买盘(看涨为对)，-1=卖盘/警示(看跌为对)
DIRS = {'mega_buy': 1, 'accel_in': 1, 'reversal_bull': 1,
        'mega_sell': -1, 'sustained_out': -1, 'reversal_bear': -1,
        'green': 1, 'red': -1}

def collect():
    sigs = []
    for t, code, stp in cur.execute(
        "SELECT time, stock_code, signal_type FROM sniper_signals WHERE trade_date=?", (D,)).fetchall():
        if t and len(t) >= 5: sigs.append((t, code, stp, 'sniper:'+stp))
    for t, code, light in cur.execute(
        "SELECT time, stock_code, light FROM entry_timing_signals WHERE trade_date=?", (D,)).fetchall():
        if t and len(t) >= 5: sigs.append((t, code, light, '择时:'+('🟢可低吸' if light=='green' else '🔴别追')))
    out = []
    for t, code, key, label in sigs:
        a = int(t[:2])*60+int(t[3:5])
        ent = price_at(code, a)
        if not ent or ent <= 0: continue
        p30 = price_ge(code, a+30); plast = prep[code][1][-1] if code in prep else None
        r30 = (p30/ent-1) if p30 else None
        reod = (plast/ent-1) if plast else None
        r30_rel = (r30 - mkt(a, 30)) if r30 is not None else None
        reod_rel = (reod - mkt(a, None)) if reod is not None else None
        out.append(dict(key=key, label=label, dir=DIRS.get(key, 0),
                        r30=r30, reod=reod, r30_rel=r30_rel, reod_rel=reod_rel))
    return out

sigs = collect()
mkt_all = mkt(9*60+30, None)  # 市场从09:30至今中位
sess = '，盘中·EOD=至今' if LAST < 16*60 else ''
print(f"=== 信号质量 {D}  (逐笔至 {LAST//60:02d}:{LAST%60:02d}{sess}) ===")
print(f"参考池 {len(refs)} 只；当日全市场至今中位 = {mkt_all*100:+.2f}%\n")
hdr = f"{'信号':22} {'N':>4} {'+30相对中位%':>13} {'EOD相对中位%':>13} {'方向命中%':>10}"
print(hdr); print('-'*72)
bykey = defaultdict(list)
for s in sigs: bykey[s['label']].append(s)
def med(xs): return st.median(xs)*100 if xs else None
def fmt(v): return f"{v:>13.2f}" if v is not None else f"{'—':>13}"
order = ['sniper:mega_buy', 'sniper:accel_in', 'sniper:reversal_bull', '择时:🟢可低吸',
         'sniper:mega_sell', 'sniper:sustained_out', 'sniper:reversal_bear', '择时:🔴别追']
for lab in order:
    sel = bykey.get(lab, [])
    if not sel:
        print(f"{lab:22} {0:>4}"); continue
    d = sel[0]['dir']
    r30r = [s['r30_rel'] for s in sel if s['r30_rel'] is not None]
    reodr = [s['reod_rel'] for s in sel if s['reod_rel'] is not None]
    hit = [(s['reod_rel']*d > 0) for s in sel if s['reod_rel'] is not None]
    hitp = 100*sum(hit)/len(hit) if hit else None
    hs = f"{hitp:.0f}" if hitp is not None else "—"
    print(f"{lab:22} {len(sel):>4} {fmt(med(r30r))} {fmt(med(reodr))} {hs:>10}")

print("\n口径：'方向命中'=买盘信号后跑赢市场 / 卖盘(警示)信号后跑输市场 的占比(市场相对·去beta)。")
print("单日=噪音级，仅当日复盘，非边际证明。盘中则 EOD=至今、近30min信号无+30min。")
