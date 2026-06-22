#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐分钟「交易视角」回放回测 —— **强势股**口径 (read-only)。

核心命题是"强势股低吸"，故只在**当日强势股(涨≥3%)**上回测：
- 低吸绿灯：逐分钟重放(强势 + judge_entry_timing 判 green)生成历史信号(因为 entry_timing_signals 无历史)。
- sniper 买盘(mega_buy/accel_in/reversal_bull)：过滤到强势股(信号时涨≥3%)作对照。
每条信号：信号后下一分钟进场(打滑点) → 逐分钟应用出场(止盈止损/移动/限时/收盘) → 扣往返成本 →
每笔净 P&L → 胜率/均/中位/期望/盈亏比/最大回撤/持有分钟；扫多组出场看哪种稳健；按 regime 分行情。

因果：进场/出场/特征只用 ≤当前分钟数据。仅 SELECT，--db 默认 mode=ro。
单日/<10 独立交易日=框架展示非结论。用法：python3 trade_replay_backtest.py [--db ...] [--friction-bps 30]
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
        today_min_gain = 0.03; dip_mom = -0.003; ofi_hot = 0.30; pos_low = 0.50; pos_strong_low = 0.34

DEDUP_MIN = 15
MIN_DAY_ROWS = 5000
MIN_DAYS = 10
STRONG_GAIN = 0.03           # 当日强势 = 涨幅(现价/前收-1) ≥ 3%
SLIP_FEE_BPS_DEFAULT = 30

RULES = [
    ('收盘持有',        {'kind': 'eod'}),
    ('TP1.5/SL1.0',     {'kind': 'tpsl', 'tp': 0.015, 'sl': 0.010}),
    ('TP2.0/SL1.5',     {'kind': 'tpsl', 'tp': 0.020, 'sl': 0.015}),
    ('TP3.0/SL2.0',     {'kind': 'tpsl', 'tp': 0.030, 'sl': 0.020}),
    ('移动·激活2回撤1.5', {'kind': 'trail', 'act': 0.020, 'trail': 0.015}),
    ('移动·激活3回撤2.0', {'kind': 'trail', 'act': 0.030, 'trail': 0.020}),
    ('限时30min',       {'kind': 'time', 'mins': 30}),
    ('限时60min',       {'kind': 'time', 'mins': 60}),
]


def to_min(s):
    return int(s[:2]) * 60 + int(s[3:5])


def is_green(mom5, ofi, pos):
    if judge_entry_timing is not None:
        return judge_entry_timing(mom5, ofi, pos, TH)[0] == 'green'
    if mom5 is None or pos is None:
        return False
    return mom5 <= TH.dip_mom and pos <= TH.pos_low and (ofi is None or ofi < TH.ofi_hot)


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
            tmp[(d, code)].append((to_min(m), float(p), float(hi or p), float(lo or p),
                                   float(ba or 0), float(sa or 0)))
        for key, v in tmp.items():
            v.sort()
            am = [x[0] for x in v]; pr = [x[1] for x in v]; hi = [x[2] for x in v]; lo = [x[3] for x in v]
            runhi = []; runlo = []; H = L = None
            for h, l in zip(hi, lo):
                H = h if H is None else max(H, h); L = l if L is None else min(L, l)
                runhi.append(H); runlo.append(L)
            pb = [0.0]; ps = [0.0]
            for x in v:
                pb.append(pb[-1] + x[4]); ps.append(ps[-1] + x[5])
            prep[key] = dict(am=am, pr=pr, hi=hi, lo=lo, runhi=runhi, runlo=runlo, pb=pb, ps=ps)
    kc = defaultdict(list)
    for code, tk, cl in cur.execute(
        "SELECT stock_code, substr(time_key,1,10) d, close_price FROM kline_data "
        "WHERE substr(time_key,1,10) <= ? AND close_price>0", (today,)).fetchall():
        kc[code].append((tk, float(cl)))
    for code in kc:
        kc[code].sort()
    return today, days, prep, kc


def prev_close(kc, code, day):
    ser = kc.get(code)
    if not ser:
        return None
    pc = None
    for dd, c in ser:
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
    am, pr = P['am'], P['pr']
    cp = pr[i]
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


def exit_trade(P, e, rule):
    am, pr, hi, lo = P['am'], P['pr'], P['hi'], P['lo']
    entry = pr[e]; em = am[e]; kind = rule['kind']
    if entry <= 0:
        return None
    if kind == 'eod':
        return pr[-1] / entry - 1, am[-1] - em
    if kind == 'tpsl':
        tp = entry * (1 + rule['tp']); sl = entry * (1 - rule['sl'])
        for j in range(e + 1, len(am)):
            if lo[j] <= sl:
                return -rule['sl'], am[j] - em
            if hi[j] >= tp:
                return rule['tp'], am[j] - em
        return pr[-1] / entry - 1, am[-1] - em
    if kind == 'trail':
        peak = entry; act = False
        for j in range(e + 1, len(am)):
            if hi[j] > peak:
                peak = hi[j]
            if not act and peak >= entry * (1 + rule['act']):
                act = True
            if act and pr[j] <= peak * (1 - rule['trail']):
                return pr[j] / entry - 1, am[j] - em
        return pr[-1] / entry - 1, am[-1] - em
    if kind == 'time':
        for j in range(e + 1, len(am)):
            if am[j] - em >= rule['mins']:
                return pr[j] / entry - 1, am[j] - em
        return pr[-1] / entry - 1, am[-1] - em
    return None


def metrics(trades, friction):
    if not trades:
        return None
    nets = [(d, a, g - friction, h) for d, a, g, h in trades]
    rs = [x[2] for x in nets]
    wins = [r for r in rs if r > 0]; losses = [r for r in rs if r < 0]
    pf = (sum(wins) / -sum(losses)) if losses else (float('inf') if wins else 0.0)
    seq = sorted(nets, key=lambda x: (x[0], x[1]))
    cum = peak = dd = 0.0
    for _, _, r, _ in seq:
        cum += r; peak = max(peak, cum); dd = max(dd, peak - cum)
    return dict(N=len(rs), days=len({x[0] for x in nets}),
                win=100 * len(wins) / len(rs), avg=st.mean(rs) * 100, med=st.median(rs) * 100,
                pf=pf, maxdd=dd * 100, hold=st.mean([x[3] for x in nets]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="file:/opt/futu_trade_sys/simple_trade/data/trade.db?mode=ro")
    ap.add_argument("--friction-bps", type=float, default=SLIP_FEE_BPS_DEFAULT)
    args = ap.parse_args()
    friction = args.friction_bps / 10000.0
    conn = sqlite3.connect(args.db, uri=True)
    today, days, prep, kc = load(conn)
    print(f"# 逐分钟交易回放·**强势股口径**(涨≥{STRONG_GAIN*100:.0f}%)  DB={args.db}")
    print(f"# 完整交易日={len(days)} ({days[0] if days else '-'}..{days[-1] if days else '-'})  "
          f"成本={args.friction_bps:.0f}bps  进场=信号后下一分钟  judge={'线上' if judge_entry_timing else '内置'}")
    if not days:
        print("无完整交易日。"); return
    reg = {d: regime_of(d, prep, kc) for d in days}
    print("# regime:", reg)

    # ---- 信号生成(强势股) ----
    # A) 低吸绿灯：逐分钟重放(强势 + judge green)
    greens = []
    for (d, code), P in prep.items():
        pc = prev_close(kc, code, d)
        if not pc or pc <= 0:
            continue
        am, pr = P['am'], P['pr']
        lastlog = -999
        for i in range(len(am)):
            if pr[i] / pc - 1 < STRONG_GAIN:       # 非强势
                continue
            f = feats(P, i)
            if not f:
                continue
            _, mom5, ofi, pos = f
            if is_green(mom5, ofi, pos):
                if am[i] - lastlog < DEDUP_MIN:
                    continue
                lastlog = am[i]
                greens.append((d, code, '强势·低吸(重放)', am[i]))
    # B) sniper 买盘过滤到强势股
    cur = conn.cursor(); ph = ",".join("?" * len(days))
    snraw = defaultdict(list)
    for d, t, code, stp in cur.execute(
        f"SELECT trade_date, time, stock_code, signal_type FROM sniper_signals WHERE trade_date IN ({ph})", days).fetchall():
        if stp in ('mega_buy', 'accel_in', 'reversal_bull') and t and len(t) >= 5:
            snraw[(d, code, '强势·' + stp)].append(to_min(t))
    snstrong = []
    for (d, code, lab), mins in snraw.items():
        P = prep.get((d, code)); pc = prev_close(kc, code, d)
        if not P or not pc or pc <= 0:
            continue
        am, pr = P['am'], P['pr']
        last = -999
        for a in sorted(mins):
            k = bisect.bisect_right(am, a) - 1
            if k < 0 or pr[k] / pc - 1 < STRONG_GAIN:   # 信号时非强势 → 剔除
                continue
            if a - last < DEDUP_MIN:
                continue
            last = a
            snstrong.append((d, code, lab, a))

    allsig = greens + snstrong

    # ---- 交易回放 ----
    res = defaultdict(lambda: defaultdict(list))
    reg_res = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))   # [lab][regime][rule]
    n_ent = defaultdict(int)
    for d, code, lab, a in allsig:
        P = prep.get((d, code))
        if not P:
            continue
        am = P['am']; e = bisect.bisect_right(am, a)
        if e >= len(am):
            continue
        n_ent[lab] += 1
        for rname, rule in RULES:
            r = exit_trade(P, e, rule)
            if r is None:
                continue
            g, hold = r
            res[lab][rname].append((d, am[e], g, hold))
            reg_res[lab][reg[d]][rname].append((d, am[e], g, hold))

    order = ['强势·低吸(重放)', '强势·mega_buy', '强势·accel_in', '强势·reversal_bull']
    for lab in order:
        ent = n_ent.get(lab, 0)
        print(f"\n=== {lab}  进场 {ent} 笔 ===")
        if ent == 0:
            print("   (无)"); continue
        hdr = f"   {'出场规则':18} {'N':>4} {'天':>3} {'胜率%':>6} {'均净%':>7} {'中位%':>7} {'盈亏比':>6} {'回撤%':>8} {'持有m':>6}  判定"
        print(hdr)
        for rname, _ in RULES:
            m = metrics(res[lab][rname], friction)
            if not m:
                continue
            v = "样本不足" if m['days'] < MIN_DAYS else ("正期望" if m['avg'] > 0 else "负期望")
            pf = '∞' if m['pf'] == float('inf') else f"{m['pf']:.2f}"
            print(f"   {rname:18} {m['N']:>4} {m['days']:>3} {m['win']:>6.0f} {m['avg']:>+7.2f} "
                  f"{m['med']:>+7.2f} {pf:>6} {m['maxdd']:>8.1f} {m['hold']:>6.0f}  {v}")
        # regime 分行情(收盘持有 基准)
        bits = []
        for rr in ('up', 'flat', 'down'):
            m = metrics(reg_res[lab][rr]['收盘持有'], friction)
            if m:
                bits.append(f"{rr}:N{m['N']}/{m['days']}天/均{m['avg']:+.2f}%/胜{m['win']:.0f}%")
        print("   [收盘持有·分行情] " + ("  ".join(bits) if bits else "—"))

    print(f"\n口径：仅当日涨≥{STRONG_GAIN*100:.0f}%的强势股；低吸绿灯按 judge_entry_timing 逐分钟重放;"
          f" 净收益扣 {args.friction_bps:.0f}bps;盘中止盈止损用分钟high/low(先止损)。")
    print(f"ticker_minute 仅 {len(days)} 个完整交易日(1涨3跌)→多'样本不足'＝诚实;每周重跑、攒够涨/平盘日再分行情下结论。")


if __name__ == "__main__":
    main()
