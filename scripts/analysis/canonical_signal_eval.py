#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""信号质量「唯一口径」评估器 (read-only)。

终结"同一信号不同回测给出 +0.30%/−0.09%/−0.35% 互相打架"的问题：把 universe /
归一化 / 样本+horizon 三条自由轴全部冻结成单一固定口径，**按行情(regime)分行情**统计，
带样本量 + bootstrap 置信区间 + N<30=样本不足闸门，使结果今后可比、可复现。

口径(KOUJING_VERSION，改任一常量=版本升级，非临时 flag)：
- universe=全量：每类型每完整交易日所有触发行；方向按类型固定(DIRS)。
- dedup：同(日,股,类型) 15min 冷却。
- horizon：主 +30min，次 EOD、次日收盘；前向价取自 ticker_minute，只用 minute>=信号分钟(因果)。
- 归一化=placebo 对照：同股同日、随机其它分钟、距真实事件>=20min；lift=信号前向−对照均值(按方向取号)。
- 命中：sign(前向−对照)==方向 且 |前向|>=0.5%；<0.5% 记 NEUTRAL。
- 仅完整交易日(trade_date<today 且当日 ticker_minute 行数>=下限)。
- regime：当日活跃股 close/prev_close−1 的横截面中位；>=+0.5%=up / <=−0.5%=down / 其余 flat。
- verdict：N<30→insufficient_data；CI排0&lift>=+0.3%&hit>=58→keep；CI排0&lift<=−0.3%→anti；否则 watch。

数据源 ticker_minute 现仅 ~6 天、每日累积；现在多数格子会显示 insufficient_data＝正确诚实输出。
只 SELECT，--db 默认 mode=ro。用法：
  python3 canonical_signal_eval.py [--probe] [--db 'file:/path/trade.db?mode=ro'] [--json out.json]
"""
import sqlite3, sys, bisect, random, math, json, argparse
import statistics as st
from collections import defaultdict

KOUJING_VERSION = "1.1"
DEDUP_MIN = 15
MIN_DAYS = 10            # 一个格子还须 >= 这么多"独立交易日"才出方向判决(N条信号可能全来自1天)
H_PRIMARY = 30
GUARD = 20
CONTROLS = 5
SEED = 20260622
NOISE = 0.005
REGIME_BAND = 0.005
MIN_DAY_ROWS = 5000      # 完整交易日：当日 ticker_minute 行数下限(剔节假日零碎)
MIN_N = 30
KEEP_LIFT = 0.003
KEEP_HIT = 58.0
ANTI_LIFT = -0.003
BOOT = 1000

DIRS = {
    'sniper:mega_buy': 1, 'sniper:accel_in': 1, 'sniper:reversal_bull': 1,
    'sniper:mega_sell': -1, 'sniper:sustained_out': -1, 'sniper:reversal_bear': -1,
    'entry:green': 1, 'entry:red': -1,
}
TYPES = list(DIRS.keys())


def to_min(hhmm):
    return int(hhmm[:2]) * 60 + int(hhmm[3:5])


# ---------- 数据加载 ----------

def load(conn, probe=False):
    cur = conn.cursor()
    today = cur.execute("SELECT MAX(trade_date) FROM ticker_minute").fetchone()[0]
    # 完整交易日：行数>=下限 且 < today
    drows = cur.execute(
        "SELECT trade_date, COUNT(*) FROM ticker_minute GROUP BY trade_date").fetchall()
    days = sorted(d for d, n in drows if d and d < today and n >= MIN_DAY_ROWS)
    # ticker_minute 分钟序列 {(date,code): (am[], price[])}
    ser = defaultdict(list)
    if days:
        ph = ",".join("?" * len(days))
        for code, d, m, p in cur.execute(
            f"SELECT stock_code, trade_date, minute, price FROM ticker_minute "
            f"WHERE trade_date IN ({ph}) AND price>0", days).fetchall():
            ser[(d, code)].append((to_min(m), float(p)))
    minute = {}
    for k, v in ser.items():
        v.sort()
        minute[k] = ([a for a, _ in v], [p for _, p in v])
    # kline 收盘 {code: [(date, close)]}(用于 regime 前收 + 次日收)
    kc = defaultdict(list)
    for code, tk, cl in cur.execute(
        "SELECT stock_code, substr(time_key,1,10) d, close_price FROM kline_data "
        "WHERE substr(time_key,1,10) <= ? AND close_price>0", (today,)).fetchall():
        kc[code].append((tk, float(cl)))
    for code in kc:
        kc[code].sort()
    return today, days, minute, kc


def regime_of(day, prevday, minute, kc):
    """当日活跃股 close/prevclose-1 横截面中位 → up/down/flat。"""
    rets = []
    for (d, code), (am, pr) in minute.items():
        if d != day or len(am) < 30:
            continue
        ser = kc.get(code)
        if not ser:
            continue
        cD = next((c for dd, c in ser if dd == day), None)
        cP = None
        for dd, c in ser:
            if dd < day:
                cP = c
            else:
                break
        if cD and cP and cP > 0:
            rets.append(cD / cP - 1)
    if not rets:
        return "flat", 0.0, 0
    m = st.median(rets)
    reg = "up" if m >= REGIME_BAND else ("down" if m <= -REGIME_BAND else "flat")
    return reg, m, len(rets)


# ---------- 前向收益 ----------

def price_at(am, pr, a):
    i = bisect.bisect_right(am, a) - 1
    return pr[i] if i >= 0 else None

def price_ge(am, pr, a):
    i = bisect.bisect_left(am, a)
    return pr[i] if i < len(am) else None

def fwd(am, pr, a, h):
    p0 = price_at(am, pr, a)
    if not p0 or p0 <= 0:
        return None
    p1 = price_ge(am, pr, a + h) if h else pr[-1]
    return (p1 / p0 - 1) if p1 else None


# ---------- 统计 ----------

def boot_ci(vals, rng):
    if len(vals) < 8:
        return (None, None)
    n = len(vals); meds = []
    for _ in range(BOOT):
        meds.append(st.median(vals[rng.randrange(n)] for _ in range(n)))
    meds.sort()
    return (meds[int(0.025 * BOOT)], meds[int(0.975 * BOOT)])

def sign_p(vals):
    nz = [v for v in vals if v != 0]
    n = len(nz)
    if n == 0:
        return 1.0
    k = sum(1 for v in nz if v > 0)
    z = (k - n / 2) / math.sqrt(n / 4)
    return round(2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2)))), 3)

def verdict(N, ndays, ci, lift_med, hit):
    if N < MIN_N or ndays < MIN_DAYS:
        return "insufficient_data"
    lo, hi = ci
    if lo is not None and lo > 0 and lift_med is not None and lift_med >= KEEP_LIFT and hit is not None and hit >= KEEP_HIT:
        return "keep"
    if hi is not None and hi < 0 and lift_med is not None and lift_med <= ANTI_LIFT:
        return "anti"
    return "watch"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="file:/opt/futu_trade_sys/simple_trade/data/trade.db?mode=ro")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    conn = sqlite3.connect(args.db, uri=True)
    rng = random.Random(SEED)

    today, days, minute, kc = load(conn)
    print(f"# 唯一口径信号质量评估 KOUJING_VERSION={KOUJING_VERSION}")
    print(f"# DB={args.db}  完整交易日={len(days)} ({days[0] if days else '-'}..{days[-1] if days else '-'})  today(剔除)={today}")
    if not days:
        print("无完整交易日数据。"); return

    # regime 台账
    reg = {}
    print("\n=== 逐日 regime 台账 ===")
    for i, d in enumerate(days):
        prev = days[i-1] if i > 0 else None
        r, med, na = regime_of(d, prev, minute, kc)
        reg[d] = r
        print(f"   {d}  {r:5}  中位{med*100:+.2f}%  活跃股{na}")

    # 信号(8类) + 15min 去重
    cur = conn.cursor(); ph = ",".join("?" * len(days))
    sigs = []  # (date, code, type, abs_min)
    for d, t, code, stp in cur.execute(
        f"SELECT trade_date, time, stock_code, signal_type FROM sniper_signals WHERE trade_date IN ({ph})", days).fetchall():
        k = 'sniper:' + stp
        if k in DIRS and t and len(t) >= 5:
            sigs.append((d, code, k, to_min(t)))
    for d, t, code, light in cur.execute(
        f"SELECT trade_date, time, stock_code, light FROM entry_timing_signals WHERE trade_date IN ({ph})", days).fetchall():
        k = 'entry:' + light
        if k in DIRS and t and len(t) >= 5:
            sigs.append((d, code, k, to_min(t)))
    # dedup 同(日,股,类型) 15min
    sigs.sort(key=lambda x: (x[0], x[2], x[1], x[3]))
    last = {}; ded = []
    for d, code, k, a in sigs:
        kk = (d, k, code)
        if kk in last and a - last[kk] < DEDUP_MIN:
            continue
        last[kk] = a; ded.append((d, code, k, a))
    print(f"\n信号(去重后) 共 {len(ded)} 条")
    if args.probe:
        cnt = defaultdict(int)
        for d, code, k, a in ded:
            cnt[(k, reg.get(d))] += 1
        for k in TYPES:
            print("  ", k, {r: cnt.get((k, r), 0) for r in ('up', 'flat', 'down')})
        return

    # 每(日,股)真实信号分钟集合(用于 placebo guard)
    realmins = defaultdict(set)
    for d, code, k, a in ded:
        realmins[(d, code)].add(a)

    # 评估每条信号：+30m / EOD lift(vs placebo 对照)
    cells = defaultdict(lambda: {'l30': [], 'leod': [], 'hit': [], 'neu': 0, 'nctl': 0, 'days': set()})
    cohort = defaultdict(list)  # entry:green up-regime day-demean +30m
    cohort_day = defaultdict(lambda: defaultdict(list))
    for d, code, k, a in ded:
        key = (d, code)
        if key not in minute:
            continue
        am, pr = minute[key]
        s30 = fwd(am, pr, a, H_PRIMARY); seod = fwd(am, pr, a, None)
        if s30 is None and seod is None:
            continue
        dr = DIRS[k]
        # placebo 候选：同股日、距所有真实事件>=GUARD、且 +30m 可算
        forb = realmins[key]
        cand = [m for m in am if all(abs(m - r) >= GUARD for r in forb) and (m + H_PRIMARY) <= am[-1]]
        c30 = ceod = None
        if len(cand) >= 2:
            pick = rng.sample(cand, min(CONTROLS, len(cand)))
            c30s = [fwd(am, pr, c, H_PRIMARY) for c in pick]; c30s = [x for x in c30s if x is not None]
            ceods = [fwd(am, pr, c, None) for c in pick]; ceods = [x for x in ceods if x is not None]
            c30 = st.mean(c30s) if c30s else None
            ceod = st.mean(ceods) if ceods else None
            cells[(k, reg.get(d))]['nctl'] += len(pick)
        cell = cells[(k, reg.get(d))]
        if s30 is not None and c30 is not None:
            lift = dr * (s30 - c30)
            cell['l30'].append(lift)
            cell['days'].add(d)
            if abs(s30) < NOISE:
                cell['neu'] += 1
            else:
                cell['hit'].append(1 if lift > 0 else 0)
        if seod is not None and ceod is not None:
            cell['leod'].append(dr * (seod - ceod))
        # cohort：entry:green / up / day-demean +30m
        if k == 'entry:green' and reg.get(d) == 'up' and s30 is not None:
            cohort_day[d]['vals'].append(s30)

    # 输出主表
    print(f"\n=== per-(信号 × regime) +30min lift(placebo 对照·去 beta) ===")
    hdr = f"{'信号':22} {'regime':6} {'N':>4} {'天':>3} {'lift中位%':>9} {'CI95%':>16} {'命中%':>6} {'中性%':>6} {'EOD中位%':>9} {'p':>5}  verdict"
    print(hdr); print('-' * len(hdr))
    out = {'version': KOUJING_VERSION, 'days': days, 'regime': reg, 'cells': []}
    for k in TYPES:
        for r in ('up', 'flat', 'down'):
            c = cells.get((k, r))
            if not c or not c['l30']:
                continue
            l30 = c['l30']; N = len(l30); nd = len(c['days'])
            med = st.median(l30); ci = boot_ci(l30, rng)
            hit = (100 * sum(c['hit']) / len(c['hit'])) if c['hit'] else None
            neu = 100 * c['neu'] / N
            eod = st.median(c['leod']) if c['leod'] else None
            p = sign_p(l30); v = verdict(N, nd, ci, med, hit)
            cis = f"[{ci[0]*100:+.2f},{ci[1]*100:+.2f}]" if ci[0] is not None else f"{'—':>16}"
            hs = f"{hit:.0f}" if hit is not None else "—"
            es = f"{eod*100:+.2f}" if eod is not None else "—"
            print(f"{k:22} {r:6} {N:>4} {nd:>3} {med*100:>+9.2f} {cis:>16} {hs:>6} {neu:>6.0f} {es:>9} {p:>5}  {v}")
            out['cells'].append(dict(type=k, regime=r, N=N, ndays=nd, nctl=c['nctl'],
                                     lift30_med=round(med, 5), ci=[round(x, 5) if x is not None else None for x in ci],
                                     hit=hit, neutral=round(neu, 1), eod_med=round(eod, 5) if eod is not None else None,
                                     sign_p=p, verdict=v))

    # cohort 对账：复现旧 "+0.30%/56%"
    print(f"\n=== 对账 cohort: entry:green / regime=up / day-demean +30m (复现旧'+0.30%/56%') ===")
    demeaned = []
    for d, dd in cohort_day.items():
        vals = dd.get('vals', [])
        if len(vals) >= 2:
            m = st.mean(vals)
            demeaned += [v - m for v in vals]
    if demeaned:
        med = st.median(demeaned); hit = 100 * sum(1 for v in demeaned if v > 0) / len(demeaned)
        print(f"   N={len(demeaned)}  day-demean +30m 中位={med*100:+.2f}%  命中={hit:.0f}%  (旧脚注口径，仅 up 行情、强势池、未 placebo)")
        out['cohort'] = dict(N=len(demeaned), median=round(med, 5), hit=round(hit, 1))
    else:
        print("   样本不足(up 行情天数/绿灯太少)")

    print(f"\n口径冻结于 KOUJING_VERSION={KOUJING_VERSION}；N<30 一律 insufficient_data。"
          f" ticker_minute 仅 {len(days)} 个完整交易日 → 多为样本不足＝正确诚实输出，每周重跑累积 N。")
    if args.json:
        with open(args.json, 'w') as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(f"JSON → {args.json}")


if __name__ == "__main__":
    main()
