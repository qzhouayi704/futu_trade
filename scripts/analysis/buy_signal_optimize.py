#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""买入信号「优化阶梯」多日回测 (read-only)。

在强势股(涨≥3%)的买入信号上(低吸=judge逐分钟重放, sniper买盘过滤强势)，逐层叠加候选优化看净收益变化：
  L0 naive          : 全部强势买入信号, 收盘出场
  L1 +行情门        : 只在 涨/平盘(regime∈up,flat) 交易
  L2 +避脉冲顶      : 再剔除"急涨别碰"(信号前3min急涨≥6% 或 当日已涨≥12%)
  L3 +移动止盈出场  : 出场改 移动·激活2%回撤1.5%(替代收盘持有)
每层报 N/天/胜率/均净%/中位/盈亏比 并分行情。净收益扣往返成本。诚实：样本不足(涨市仅1天)不下结论。
仅 SELECT，--db 默认 mode=ro。用法：python3 buy_signal_optimize.py [--db ...] [--friction-bps 30]
"""
import sqlite3, sys, bisect, argparse
import statistics as st
from collections import defaultdict

sys.path.insert(0, '/opt/futu_trade_sys')
try:
    from simple_trade.services.trading.entry_timing import judge_entry_timing, EntryTimingThresholds
    TH = EntryTimingThresholds()
except Exception:
    judge_entry_timing = None
    class TH:  # noqa
        today_min_gain = 0.03; dip_mom = -0.003; ofi_hot = 0.30; pos_low = 0.50

DEDUP_MIN = 15; MIN_DAY_ROWS = 5000; STRONG_GAIN = 0.03
PULSE_PRE3 = 0.06; PULSE_GAIN = 0.12
EXIT_TRAIL = {'act': 0.020, 'trail': 0.015}
SLIP_FEE_BPS = 30


def to_min(s):
    return int(s[:2]) * 60 + int(s[3:5])


def is_green(mom5, ofi, pos):
    if judge_entry_timing is not None:
        return judge_entry_timing(mom5, ofi, pos, TH)[0] == 'green'
    return (mom5 is not None and pos is not None and mom5 <= TH.dip_mom
            and pos <= TH.pos_low and (ofi is None or ofi < TH.ofi_hot))


def load(conn):
    cur = conn.cursor()
    today = cur.execute("SELECT MAX(trade_date) FROM ticker_minute").fetchone()[0]
    drows = cur.execute("SELECT trade_date, COUNT(*) FROM ticker_minute GROUP BY trade_date").fetchall()
    days = sorted(d for d, n in drows if d and d < today and n >= MIN_DAY_ROWS)
    prep = {}
    if days:
        ph = ",".join("?" * len(days))
        tmp = defaultdict(list)
        for code, d, m, p, hi, lo, ba, sa in cur.execute(
            f"SELECT stock_code, trade_date, minute, price, high, low, buy_amt, sell_amt "
            f"FROM ticker_minute WHERE trade_date IN ({ph}) AND price>0", days).fetchall():
            tmp[(d, code)].append((to_min(m), float(p), float(hi or p), float(lo or p), float(ba or 0), float(sa or 0)))
        for key, v in tmp.items():
            v.sort()
            am = [x[0] for x in v]; pr = [x[1] for x in v]; hi = [x[2] for x in v]; lo = [x[3] for x in v]
            runhi = []; runlo = []; H = L = None
            for h, l in zip(hi, lo):
                H = h if H is None else max(H, h); L = l if L is None else min(L, l); runhi.append(H); runlo.append(L)
            pb = [0.0]; ps = [0.0]
            for x in v:
                pb.append(pb[-1] + x[4]); ps.append(ps[-1] + x[5])
            prep[key] = dict(am=am, pr=pr, hi=hi, lo=lo, runhi=runhi, runlo=runlo, pb=pb, ps=ps)
    kc = defaultdict(list)
    for code, tk, cl in cur.execute(
        "SELECT stock_code, substr(time_key,1,10) d, close_price FROM kline_data WHERE substr(time_key,1,10)<=? AND close_price>0", (today,)).fetchall():
        kc[code].append((tk, float(cl)))
    for code in kc:
        kc[code].sort()
    return today, days, prep, kc


def prev_close(kc, code, day):
    pc = None
    for dd, c in kc.get(code, []):
        if dd < day:
            pc = c
        else:
            break
    return pc


def regime_of(day, prep, kc):
    rets = []
    for (d, code), P in prep.items():
        if d != day or len(P['am']) < 30:
            continue
        cD = next((c for dd, c in kc.get(code, []) if dd == day), None)
        cP = prev_close(kc, code, day)
        if cD and cP and cP > 0:
            rets.append(cD / cP - 1)
    if not rets:
        return "flat"
    m = st.median(rets)
    return "up" if m >= 0.005 else ("down" if m <= -0.005 else "flat")


def feats(P, i):
    am, pr = P['am'], P['pr']; cp = pr[i]
    if cp <= 0:
        return None
    j = bisect.bisect_right(am, am[i] - 5) - 1
    mom5 = (cp / pr[j] - 1) if (j >= 0 and pr[j] > 0) else None
    H, L = P['runhi'][i], P['runlo'][i]
    pos = (cp - L) / (H - L) if H > L else 0.5
    li = bisect.bisect_right(am, am[i] - 15)
    b = P['pb'][i + 1] - P['pb'][li]; s = P['ps'][i + 1] - P['ps'][li]
    ofi = (b - s) / (b + s) if (b + s) > 0 else None
    return cp, mom5, ofi, pos


def pre_jump3(P, i):
    am, pr = P['am'], P['pr']
    j = bisect.bisect_right(am, am[i] - 3) - 1
    return (pr[i] / pr[j] - 1) if (j >= 0 and pr[j] > 0) else 0.0


def net_ret(P, e, exitk, friction):
    am, pr, hi, lo = P['am'], P['pr'], P['hi'], P['lo']
    entry = pr[e]
    if entry <= 0:
        return None
    if exitk == 'eod':
        g = pr[-1] / entry - 1
    else:
        peak = entry; act = False; g = pr[-1] / entry - 1
        for j in range(e + 1, len(am)):
            if hi[j] > peak:
                peak = hi[j]
            if not act and peak >= entry * (1 + EXIT_TRAIL['act']):
                act = True
            if act and pr[j] <= peak * (1 - EXIT_TRAIL['trail']):
                g = pr[j] / entry - 1; break
    return g - friction


def metrics(rs):
    if not rs:
        return None
    vals = [x[1] for x in rs]
    wins = [v for v in vals if v > 0]; losses = [v for v in vals if v < 0]
    pf = (sum(wins) / -sum(losses)) if losses else (float('inf') if wins else 0.0)
    return dict(N=len(vals), days=len({x[0] for x in rs}),
                win=100 * len(wins) / len(vals), avg=st.mean(vals) * 100, med=st.median(vals) * 100,
                pf=('∞' if pf == float('inf') else f"{pf:.2f}"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="file:/opt/futu_trade_sys/simple_trade/data/trade.db?mode=ro")
    ap.add_argument("--friction-bps", type=float, default=SLIP_FEE_BPS)
    args = ap.parse_args()
    friction = args.friction_bps / 10000.0
    conn = sqlite3.connect(args.db, uri=True)
    today, days, prep, kc = load(conn)
    print(f"# 买入信号优化阶梯·多日  DB={args.db}")
    if not days:
        print("无完整交易日。"); return
    reg = {d: regime_of(d, prep, kc) for d in days}
    print(f"# 完整交易日={len(days)}  regime={reg}  成本={args.friction_bps:.0f}bps")

    # 市场分钟级中位涨幅(算相对强度): active = 有前收且≥30min 的股
    active_by_day = defaultdict(list)
    for (d, code), P in prep.items():
        pc = prev_close(kc, code, d)
        if pc and pc > 0 and len(P['am']) >= 30:
            active_by_day[d].append((pc, P))
    _mkt = {}
    def mkt_gain_at(d, m):
        key = (d, m)
        if key in _mkt:
            return _mkt[key]
        gs = []
        for pc, P in active_by_day[d]:
            am, pr = P['am'], P['pr']
            i = bisect.bisect_right(am, m) - 1
            if i >= 0 and pr[i] > 0:
                gs.append(pr[i] / pc - 1)
        v = st.median(gs) if gs else 0.0
        _mkt[key] = v
        return v

    sig = []
    for (d, code), P in prep.items():
        pc = prev_close(kc, code, d)
        if not pc or pc <= 0:
            continue
        am, pr = P['am'], P['pr']; last = -999
        for i in range(len(am)):
            gain = pr[i] / pc - 1
            if gain < STRONG_GAIN:
                continue
            f = feats(P, i)
            if not f or not is_green(f[1], f[2], f[3]):
                continue
            if am[i] - last < DEDUP_MIN:
                continue
            last = am[i]; e = i + 1
            if e >= len(am):
                continue
            sig.append(dict(date=d, code=code, type='低吸', regime=reg[d], pre3=pre_jump3(P, i), gain=gain,
                            pos=f[3], ofi=f[2], rs=gain - mkt_gain_at(d, am[i]),
                            eod=net_ret(P, e, 'eod', friction), trail=net_ret(P, e, 'trail', friction)))
    cur = conn.cursor(); ph = ",".join("?" * len(days))
    snraw = defaultdict(list)
    for d, t, code, stp in cur.execute(
        f"SELECT trade_date,time,stock_code,signal_type FROM sniper_signals WHERE trade_date IN ({ph})", days).fetchall():
        if stp in ('mega_buy', 'accel_in', 'reversal_bull') and t and len(t) >= 5:
            snraw[(d, code, stp)].append(to_min(t))
    for (d, code, stp), mins in snraw.items():
        P = prep.get((d, code)); pc = prev_close(kc, code, d)
        if not P or not pc or pc <= 0:
            continue
        am, pr = P['am'], P['pr']; last = -999
        for a in sorted(mins):
            k = bisect.bisect_right(am, a) - 1
            if k < 0 or pr[k] / pc - 1 < STRONG_GAIN or a - last < DEDUP_MIN:
                continue
            last = a; e = bisect.bisect_right(am, a)
            if e >= len(am):
                continue
            fk = feats(P, k); gaink = pr[k] / pc - 1
            sig.append(dict(date=d, code=code, type=stp, regime=reg[d], pre3=pre_jump3(P, k), gain=gaink,
                            pos=(fk[3] if fk else 0.5), ofi=(fk[2] if fk else None), rs=gaink - mkt_gain_at(d, a),
                            eod=net_ret(P, e, 'eod', friction), trail=net_ret(P, e, 'trail', friction)))

    sig = [s for s in sig if s['eod'] is not None]
    print(f"\n强势股买入信号(去重后) 共 {len(sig)} 条")

    def rows(sel, exitk):
        return [(s['date'], s[exitk]) for s in sel if s[exitk] is not None]

    def show(name, sel, exitk):
        m = metrics(rows(sel, exitk))
        if not m:
            print(f"   {name:24} N=0"); return
        print(f"   {name:24} N={m['N']:>4} 天{m['days']} 胜率{m['win']:>4.0f}% 均净{m['avg']:>+6.2f}% "
              f"中位{m['med']:>+6.2f}% 盈亏比{m['pf']:>5}")
        bits = []
        for rr in ('up', 'flat', 'down'):
            mm = metrics(rows([s for s in sel if s['regime'] == rr], exitk))
            if mm:
                bits.append(f"{rr}:N{mm['N']}/{mm['days']}天/均{mm['avg']:+.2f}%/胜{mm['win']:.0f}%")
        print(f"      [分行情] " + ("  ".join(bits) if bits else "—"))

    print("\n=== 优化阶梯(逐层叠加) ===")
    show("L0 naive·收盘", sig, 'eod')
    L1 = [s for s in sig if s['regime'] in ('up', 'flat')]
    show("L1 +行情门·收盘", L1, 'eod')
    L2 = [s for s in L1 if not (s['pre3'] >= PULSE_PRE3 or s['gain'] >= PULSE_GAIN)]
    show("L2 +避脉冲顶·收盘", L2, 'eod')
    show("L3 +移动止盈出场", L2, 'trail')
    print(f"   (避脉冲顶剔除 {len(L1)-len(L2)} 条; 脉冲口径: 前3min急涨≥{PULSE_PRE3*100:.0f}% 或 当日已涨≥{PULSE_GAIN*100:.0f}%)")

    print("\n=== L3(行情门+避脉冲顶+移动止盈) 分信号类型 ===")
    for tp in ('低吸', 'mega_buy', 'accel_in', 'reversal_bull'):
        show("  " + tp, [s for s in L2 if s['type'] == tp], 'trail')

    # ===== 跌市收紧扫描：能否用更强参数在跌市仍开仓 =====
    down = [s for s in sig if s['regime'] == 'down' and s['eod'] is not None]
    ndd = len({s['date'] for s in down})
    print(f"\n=== 跌市收紧扫描 (down regime, {ndd}天) —— 能否加强参数救回正收益 ===")
    print(f"   {'收紧条件':26} {'N':>4} {'天':>3} {'胜率%':>6} {'均净%(收盘)':>11} {'盈亏比':>6}")

    def dshow(name, sel, exitk='eod'):
        m = metrics([(s['date'], s[exitk]) for s in sel if s[exitk] is not None])
        if not m:
            print(f"   {name:26} N=0"); return None
        print(f"   {name:26} {m['N']:>4} {m['days']:>3} {m['win']:>6.0f} {m['avg']:>+11.2f} {m['pf']:>6}")
        return m

    dshow("baseline 全部down买入", down)
    dshow("+gain≥5%", [s for s in down if s['gain'] >= 0.05])
    dshow("+gain≥7%", [s for s in down if s['gain'] >= 0.07])
    dshow("+gain≥10%", [s for s in down if s['gain'] >= 0.10])
    dshow("+相对强度≥+5%", [s for s in down if s['rs'] >= 0.05])
    dshow("+相对强度≥+8%", [s for s in down if s['rs'] >= 0.08])
    dshow("+深低吸 pos≤0.34", [s for s in down if s['pos'] <= 0.34])
    dshow("+冷单流 ofi≤0.15", [s for s in down if s['ofi'] is not None and s['ofi'] <= 0.15])
    dshow("组合 gain≥7%&RS≥+5%", [s for s in down if s['gain'] >= 0.07 and s['rs'] >= 0.05])
    dshow("组合 RS≥+8%&pos≤0.34", [s for s in down if s['rs'] >= 0.08 and s['pos'] <= 0.34])
    best = [s for s in down if s['gain'] >= 0.07 and s['rs'] >= 0.05]
    dshow("↑组合 + 移动止盈出场", best, 'trail')
    print(f"   (跌市仅 {ndd} 天 → 任何转正都是 directional·待累积，绝不直接上生产;相对强度=信号时涨幅−当时市场中位)")

    print(f"\n口径：强势股(涨≥3%)买入信号；低吸=judge逐分钟重放；净收益扣{args.friction_bps:.0f}bps；移动止盈=激活2%回撤1.5%。")
    print(f"诚实：涨市仅1天(06-15)→'分行情'里 up 是单日,别当结论;L1/L2 主要靠剔除跌市/脉冲减少亏损,需累积涨/平盘日确认。")


if __name__ == "__main__":
    main()
