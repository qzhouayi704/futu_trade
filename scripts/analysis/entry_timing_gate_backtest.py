#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""入场择时「企稳确认门」回测 — read-only，不写库。

逐分钟重放当日强势股池 + judge_entry_timing(线上同函数)，对每个 🟢可低吸
评估候选门 G1(自身序列企稳)/G2(VWAP回收)/G3(sniper落刀/转向)，比较
naive🟢 vs 各门/组合 在 +30min/EOD 的前向收益(含市场相对·day-demean)、
命中率、最大有利/不利、信号留存率，并用 placebo bootstrap 防小样本误判。

因果：门只用 ≤t0 数据；事后只用 ≥t0 同日分钟价。仅 SELECT，不写任何表。
用法：python entry_timing_gate_backtest.py [/path/to/trade.db]
"""
import sys, bisect, sqlite3, random, statistics as st
from collections import defaultdict

sys.path.insert(0, '/opt/futu_trade_sys')
try:
    from simple_trade.services.trading.entry_timing import judge_entry_timing, EntryTimingThresholds
except Exception:  # 本地无法 import 时退回内置阈值副本（仅用于语法/本地试跑）
    judge_entry_timing = None
    class EntryTimingThresholds:  # noqa
        today_min_gain=0.03; pool_top_pct=0.20; pool_max_n=40
        dip_mom=-0.003; spike_mom=0.003; ofi_hot=0.30; pos_low=0.50; pos_high=0.70; pos_strong_low=0.34
TH = EntryTimingThresholds()
DB = sys.argv[1] if len(sys.argv) > 1 else "/opt/futu_trade_sys/simple_trade/data/trade.db"
COOLDOWN = 15
random.seed(42)


def _judge(mom5, ofi15, pos):
    """优先用线上 judge_entry_timing；不可用时内置等价逻辑。返回 light。"""
    if judge_entry_timing is not None:
        return judge_entry_timing(mom5, ofi15, pos, TH)[0]
    if mom5 is None or pos is None:
        return "neutral"
    if mom5 >= TH.spike_mom and ((ofi15 is not None and ofi15 >= TH.ofi_hot) or pos >= TH.pos_high):
        return "red"
    if mom5 <= TH.dip_mom and pos <= TH.pos_low and (ofi15 is None or ofi15 < TH.ofi_hot):
        return "green"
    return "neutral"


def load_day(cur, D):
    rows = cur.execute(
        "SELECT stock_code, substr(datetime(timestamp/1000,'unixepoch','+8 hours'),12,5) m, "
        "direction, SUM(turnover), AVG(price) FROM ticker_data WHERE trade_date=? "
        "GROUP BY stock_code,m,direction", (D,)).fetchall()
    agg = defaultdict(lambda: defaultdict(lambda: {'p':0.0,'b':0.0,'s':0.0,'n':0}))
    for code, m, d, tv, ap in rows:
        if not ('09:25' <= m <= '16:10'):
            continue
        e = agg[code][m]; tv = float(tv or 0)
        if d == 'BUY': e['b'] += tv
        elif d == 'SELL': e['s'] += tv
        if ap and float(ap) > 0: e['p'] += float(ap); e['n'] += 1
    prep = {}
    for code in agg:
        lst = sorted((int(m[:2])*60+int(m[3:5]),
                      (agg[code][m]['p']/agg[code][m]['n'] if agg[code][m]['n'] else 0),
                      agg[code][m]['b'], agg[code][m]['s']) for m in agg[code])
        am = [x[0] for x in lst]; pr = [x[1] for x in lst]
        hi=[];lo=[];ph=pl=None
        for p in pr:
            ph=p if ph is None else max(ph,p); pl=p if pl is None else min(pl,p); hi.append(ph); lo.append(pl)
        pb=[0.0];psl=[0.0];ptr=[0.0];ppv=[0.0]
        for a,p,b,s in lst:
            pb.append(pb[-1]+b); psl.append(psl[-1]+s); ptr.append(ptr[-1]+b+s); ppv.append(ppv[-1]+p*(b+s))
        prep[code] = (am, pr, hi, lo, pb, psl, ptr, ppv, {am[i]:i for i in range(len(am))})
    return prep


def features(prep_code, idx):
    am, pr, hi, lo, *_ = prep_code
    a = am[idx]; cp = pr[idx]
    if cp <= 0: return None
    j = bisect.bisect_right(am, a-5)-1
    mom5 = (cp/pr[j]-1) if (j>=0 and pr[j]>0) else None
    H, L = hi[idx], lo[idx]; pos = (cp-L)/(H-L) if H>L else 0.5
    am2 = am; li = bisect.bisect_right(am2, a-15)
    pb, psl, ptr = prep_code[4], prep_code[5], prep_code[6]
    b = pb[idx+1]-pb[li]; s = psl[idx+1]-psl[li]; ofi = (b-s)/(b+s) if (b+s)>0 else None
    return cp, mom5, ofi, pos


def eval_gates(prep_code, idx, sniper_flags):
    am, pr, hi, lo, pb, psl, ptr, ppv, _ = prep_code
    a = am[idx]; cp = pr[idx]
    # G1a mom5 回收
    def ple(t):
        k = bisect.bisect_right(am, t)-1
        return pr[k] if k>=0 else None
    p5, p6 = ple(a-5), ple(a-6); pprev = pr[idx-1] if idx>0 else None
    mom5 = (cp/p5-1) if (p5 and p5>0) else None
    mom5p = (pprev/p6-1) if (pprev and p6 and p6>0) else None
    g1a = (mom5 is not None and mom5p is not None and mom5 > mom5p and mom5 >= -0.001)
    # G1b higher-low
    li = bisect.bisect_right(am, a-15); win = pr[li:idx+1]
    if win:
        wlo = min(win); wpos = li + win.index(wlo)
        g1b = (wpos < idx-1) and (cp >= wlo*1.002)
    else:
        g1b = False
    # G1c 卖量衰减
    i5 = bisect.bisect_right(am, a-5); i10 = bisect.bisect_right(am, a-10)
    s5 = psl[idx+1]-psl[i5]; s10 = psl[i5]-psl[i10]
    g1c = s10 > 0 and s5 < s10
    g1 = (int(g1a)+int(g1b)+int(g1c)) >= 2
    # G2 VWAP 回收
    turn = ptr[idx+1]; pv = ppv[idx+1]; vwap = pv/turn if turn>0 else cp
    g2 = cp <= vwap*1.003
    # G3 sniper 落刀/转向
    knife = bool(sniper_flags & {'sustained_out', 'mega_sell', 'reversal_bear'})
    turning = bool(sniper_flags & {'reversal_bull', 'accel_in'})
    g3 = not knife
    return {'g1':g1, 'g1a':g1a, 'g1b':g1b, 'g1c':g1c, 'g2':g2, 'g3':g3,
            'knife':knife, 'turning':turning,
            'vwap_dev': round((cp/vwap-1)*100, 2) if vwap>0 else None}


def outcomes(prep_code, idx):
    am, pr, *_ = prep_code; a = am[idx]; cp = pr[idx]
    j = bisect.bisect_left(am, a+30)
    r30 = (pr[j]/cp-1) if j < len(am) else None
    reod = pr[-1]/cp-1
    after = pr[idx+1:]
    mx = (max(after)/cp-1) if after else 0.0
    mn = (min(after)/cp-1) if after else 0.0
    return r30, reod, mx, mn


def main():
    con = sqlite3.connect(DB); cur = con.cursor()
    days = [r[0] for r in cur.execute("SELECT DISTINCT trade_date FROM ticker_data ORDER BY trade_date").fetchall()]
    days = [d for d in days if d]
    print(f"DB={DB}  交易日={len(days)} ({days[0]}..{days[-1]})")
    greens = []  # 每个🟢: dict(day,t,code,price,gain,r30,reod,mx,mn, gateflags...)
    for D in days:
        prep = load_day(cur, D)
        codes = list(prep)
        if not codes:
            continue
        # prev_close
        prevc = {}
        for i in range(0, len(codes), 300):
            ch = codes[i:i+300]; ph = ",".join("?"*len(ch))
            for c2, cl in cur.execute(
                f"SELECT stock_code,close_price FROM kline_data WHERE stock_code IN ({ph}) "
                f"AND substr(time_key,1,10)<? AND close_price>0 ORDER BY stock_code,time_key",
                (*ch, D)).fetchall():
                prevc[c2] = float(cl)
        # sniper signals for the day -> {code: [(amin, type)]}
        snip = defaultdict(list)
        for c2, t, stp in cur.execute(
            "SELECT stock_code, time, signal_type FROM sniper_signals WHERE trade_date=?", (D,)).fetchall():
            if t and len(t) >= 5:
                snip[c2].append((int(t[:2])*60+int(t[3:5]), stp))
        axis = sorted({a for code in codes for a in prep[code][0]})
        last_log = {}  # (code) -> last green amin (15min dedup)
        for a in axis:
            gl = []
            for code in codes:
                am, pr = prep[code][0], prep[code][1]
                k = bisect.bisect_right(am, a)-1
                if k < 0 or pr[k] <= 0: continue
                pc = prevc.get(code)
                if not pc or pc <= 0: continue
                gl.append((code, pr[k]/pc-1))
            if not gl: continue
            gl.sort(key=lambda x: -x[1]); cut = TH.today_min_gain
            if len(gl) > 5: cut = max(cut, gl[int(TH.pool_top_pct*len(gl))][1])
            pool = [(c2, g) for c2, g in gl if g >= cut][:TH.pool_max_n]
            for code, g in pool:
                idx = prep[code][8].get(a)
                if idx is None: continue
                f = features(prep[code], idx)
                if not f: continue
                cp, mom5, ofi, pos = f
                if _judge(mom5, ofi, pos) != "green": continue
                if code in last_log and a - last_log[code] < COOLDOWN: continue
                last_log[code] = a
                flags = set(st_ for fa, st_ in snip.get(code, []) if a-20 < fa <= a)
                gate = eval_gates(prep[code], idx, flags)
                r30, reod, mx, mn = outcomes(prep[code], idx)
                greens.append(dict(day=D, t=f"{a//60:02d}:{a%60:02d}", code=code, price=round(cp,3),
                                   gain=round(g*100,2), r30=r30, reod=reod, mx=mx, mn=mn, **gate))
    con.close()

    # ---- day-demean (市场相对): 每🟢 r30/reod 减当日所有🟢均值 ----
    byday = defaultdict(list)
    for x in greens: byday[x['day']].append(x)
    dmean = {D: (st.mean([x['r30'] for x in g if x['r30'] is not None]) if any(x['r30'] is not None for x in g) else 0.0,
                 st.mean([x['reod'] for x in g])) for D, g in byday.items()}
    for x in greens:
        m30, meod = dmean[x['day']]
        x['r30_rel'] = (x['r30']-m30) if x['r30'] is not None else None
        x['reod_rel'] = x['reod']-meod

    def stats(sel):
        if not sel: return None
        r30 = [x['r30'] for x in sel if x['r30'] is not None]
        r30r = [x['r30_rel'] for x in sel if x['r30_rel'] is not None]
        reodr = [x['reod_rel'] for x in sel]
        return dict(n=len(sel),
                    r30_med=st.median(r30)*100 if r30 else None,
                    r30rel_med=st.median(r30r)*100 if r30r else None,
                    r30rel_mean=st.mean(r30r)*100 if r30r else None,
                    hit30=100*sum(1 for v in r30r if v>0)/len(r30r) if r30r else None,
                    reodrel_med=st.median(reodr)*100 if reodr else None,
                    mx=st.mean([x['mx'] for x in sel])*100, mn=st.mean([x['mn'] for x in sel])*100)

    N = len(greens)
    print(f"\n=== naive🟢 总数 N={N}（{len(byday)} 个交易日）===")
    defs = {
        'naive': lambda x: True,
        '+G1企稳': lambda x: x['g1'],
        '+G2vwap': lambda x: x['g2'],
        '+G3未落刀': lambda x: x['g3'],
        'G1&G2': lambda x: x['g1'] and x['g2'],
        'G1&G3': lambda x: x['g1'] and x['g3'],
        'G2&G3': lambda x: x['g2'] and x['g3'],
        'G1&G2&G3': lambda x: x['g1'] and x['g2'] and x['g3'],
    }
    hdr = f"{'门':10} {'N':>4} {'留存%':>6} {'r30相对中位%':>11} {'r30相对均值%':>11} {'命中%':>6} {'EOD相对中位%':>11} {'maxFav%':>7} {'maxAdv%':>7}"
    print(hdr); print("-"*len(hdr))
    base = stats(greens)
    results = {}
    for name, f in defs.items():
        sel = [x for x in greens if f(x)]; s = stats(sel); results[name] = (sel, s)
        if not s:
            print(f"{name:10} {0:>4}"); continue
        keep = 100*s['n']/N
        def fmt(v): return f"{v:>11.2f}" if v is not None else f"{'—':>11}"
        hit_s = f"{s['hit30']:.0f}" if s['hit30'] is not None else "—"
        print(f"{name:10} {s['n']:>4} {keep:>6.0f} {fmt(s['r30rel_med'])} {fmt(s['r30rel_mean'])} "
              f"{hit_s:>6} {fmt(s['reodrel_med'])} {s['mx']:>7.2f} {s['mn']:>7.2f}")

    # ---- placebo: 对每个门, 随机抽同等留存数的🟢, 看真门 r30相对中位 是否优于随机分布 ----
    print("\n=== placebo (随机留同等数量🟢, 1000次): 真门 r30相对中位 在随机分布的分位 ===")
    valid = [x for x in greens if x['r30_rel'] is not None]
    pool_r = [x['r30_rel'] for x in valid]
    for name, f in defs.items():
        if name == 'naive': continue
        sel = [x for x in valid if f(x)]
        if not sel: print(f"  {name:10} N=0"); continue
        real = st.median([x['r30_rel'] for x in sel])
        k = len(sel); dist = []
        for _ in range(1000):
            dist.append(st.median(random.sample(pool_r, k)))
        pct = 100*sum(1 for d in dist if d < real)/len(dist)
        print(f"  {name:10} N={k:>4} 真门中位={real*100:+.2f}%  优于随机的{pct:.0f}%分位"
              + ("  ✓显著" if pct >= 95 else ("  ~偏好" if pct >= 80 else "  ✗不显著")))

    # ---- SMIC 06-22 专项核对 ----
    print("\n=== 中芯国际 HK.00981 各🟢 被各门 杀/留 ===")
    for x in sorted([g for g in greens if g['code']=='HK.00981'], key=lambda z:(z['day'],z['t'])):
        print(f"  {x['day']} {x['t']} @{x['price']} 涨{x['gain']}% r30={None if x['r30'] is None else round(x['r30']*100,2)} "
              f"| G1={int(x['g1'])} G2={int(x['g2'])} G3={int(x['g3'])} knife={int(x['knife'])} vwap离={x['vwap_dev']}%")


if __name__ == "__main__":
    main()
