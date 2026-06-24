#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""早段突破抢筹 合流判据回测 (read-only) —— Part C：开 EARLY_BREAKOUT_ENABLED 的闸。

复用唯一口径评估器 canonical_signal_eval 的 load/regime_of/fwd/boot_ci/sign_p/verdict
(不改它)，额外加 capital_flow_cache 资金评分序列加载器。

合成事件 synth:early_breakout：在 sniper accel_in/reversal_bull 行的分钟 a，当
  1) 合流：±6min 内有 {accel_in,reversal_bull,mega_buy}(触发行自身算一个)；
  2) 资金评分 capital_score 在 [a-12, a] 向上穿过 60 且斜率≥5；
  3) 仍早段：当日(对开盘首价)涨幅 < +4% 且 日内价位 <= 0.70。
按 (日,股) 15min 去重。

同跑未过滤 accel_in / reversal_bull / mega_buy 作 baseline——赢的条件是**相对未过滤
转强信号有正的市场相对边际**。另跑 "去掉资金评分判据②" 的 noscore 变体作对照，并诚实
报每日资金评分覆盖率(cache 近因有限，老日可能稀疏)。

指标：分 regime 报 N/天/+15m/+30m placebo 对照 lift/95%CI/命中%/verdict。
开闸条件(冻结)：synth:early_breakout 在 up 和/或 flat 下 verdict==keep(+30m) 且 +15m
中位>0 且 +30m lift 超同 regime baseline(accel_in/reversal_bull)。仅 down 命中→不开。

只 SELECT，--db 默认 mode=ro。用法：
  python3 early_breakout_eval.py [--probe] [--db 'file:/path/trade.db?mode=ro'] [--json out.json]
"""
import os
import sys
import bisect
import sqlite3
import random
import argparse
import statistics as st
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from canonical_signal_eval import (  # noqa: E402
    load, regime_of, fwd, boot_ci, sign_p, verdict, to_min,
    GUARD, CONTROLS, NOISE, DEDUP_MIN, H_PRIMARY,
)

# —— 合流判据常量(冻结) ——
CONF_WINDOW = 6
SCORE_CROSS = 60.0
SCORE_SLOPE = 5.0
SCORE_LOOKBACK = 12
EARLY_GAIN_CAP = 0.04
EARLY_POS_MAX = 0.70
H_SECOND = 15
TRIGGER_TYPES = ("accel_in", "reversal_bull")
POOL_TYPES = ("accel_in", "reversal_bull", "mega_buy")


def crossed_up(series, upto, thr, slope, lookback):
    pts = [(m, s) for m, s in series if (upto - lookback) <= m <= upto]
    for i in range(1, len(pts)):
        if pts[i - 1][1] < thr <= pts[i][1] and (pts[i][1] - pts[i - 1][1]) >= slope:
            return True
    return False


def gain_pos(am, pr, a):
    i = bisect.bisect_right(am, a) - 1
    if i < 0:
        return None, None
    p = pr[i]
    op = pr[0]
    seg = pr[: i + 1]
    lo, hi = min(seg), max(seg)
    gain = (p / op - 1) if op > 0 else None
    pos = (p - lo) / (hi - lo) if hi > lo else 0.0
    return gain, pos


def load_capital_scores(conn, days):
    """{(date, code): [(min, score)] 升序}。timestamp='YYYY-MM-DD HH:MM:SS'(本地/HK)。"""
    if not days:
        return {}
    ph = ",".join("?" * len(days))
    rows = conn.cursor().execute(
        f"SELECT substr(timestamp,1,10) d, substr(timestamp,12,5) hm, stock_code, capital_score "
        f"FROM capital_flow_cache "
        f"WHERE substr(timestamp,1,10) IN ({ph}) AND capital_score IS NOT NULL",
        days,
    ).fetchall()
    out = defaultdict(list)
    for d, hm, code, score in rows:
        if not hm or len(hm) < 5 or hm[2] != ":":
            continue
        try:
            out[(d, code)].append((to_min(hm), float(score)))
        except (ValueError, TypeError):
            continue
    for k in out:
        out[k].sort()
    return out


def dedup(events):
    """同(日,股) 15min 去重，输入/输出 [(d, code, a)]。"""
    events = sorted(events, key=lambda x: (x[0], x[1], x[2]))
    last = {}
    out = []
    for d, code, a in events:
        kk = (d, code)
        if kk in last and a - last[kk] < DEDUP_MIN:
            continue
        last[kk] = a
        out.append((d, code, a))
    return out


def eval_cells(events, minute, reg, realmins, rng):
    """对 [(d,code,a)] 评估，方向固定 +1(买)。返回 {regime: stats}。"""
    cells = defaultdict(lambda: {"l15": [], "l30": [], "leod": [], "hit": [],
                                 "neu": 0, "nctl": 0, "days": set()})
    for d, code, a in events:
        key = (d, code)
        if key not in minute:
            continue
        am, pr = minute[key]
        s15 = fwd(am, pr, a, H_SECOND)
        s30 = fwd(am, pr, a, H_PRIMARY)
        seod = fwd(am, pr, a, None)
        if s15 is None and s30 is None:
            continue
        forb = realmins.get(key, set())
        cand = [m for m in am if all(abs(m - r) >= GUARD for r in forb) and (m + H_PRIMARY) <= am[-1]]
        c15 = c30 = ceod = None
        if len(cand) >= 2:
            pick = rng.sample(cand, min(CONTROLS, len(cand)))

            def _avg(h):
                xs = [fwd(am, pr, c, h) for c in pick]
                xs = [x for x in xs if x is not None]
                return st.mean(xs) if xs else None

            c15, c30, ceod = _avg(H_SECOND), _avg(H_PRIMARY), _avg(None)
            cells[reg.get(d)]["nctl"] += len(pick)
        cell = cells[reg.get(d)]
        if s30 is not None and c30 is not None:
            lift = s30 - c30
            cell["l30"].append(lift)
            cell["days"].add(d)
            if abs(s30) < NOISE:
                cell["neu"] += 1
            else:
                cell["hit"].append(1 if lift > 0 else 0)
        if s15 is not None and c15 is not None:
            cell["l15"].append(s15 - c15)
        if seod is not None and ceod is not None:
            cell["leod"].append(seod - ceod)
    return cells


def summarize(cells, rng):
    """{regime: row-dict}。"""
    res = {}
    for r in ("up", "flat", "down"):
        c = cells.get(r)
        if not c or not c["l30"]:
            continue
        l30 = c["l30"]
        N = len(l30)
        nd = len(c["days"])
        med = st.median(l30)
        ci = boot_ci(l30, rng)
        hit = (100 * sum(c["hit"]) / len(c["hit"])) if c["hit"] else None
        l15med = st.median(c["l15"]) if c["l15"] else None
        eod = st.median(c["leod"]) if c["leod"] else None
        res[r] = dict(N=N, ndays=nd, lift30_med=med, ci=ci, hit=hit,
                      l15_med=l15med, eod_med=eod, neutral=100 * c["neu"] / N,
                      sign_p=sign_p(l30), verdict=verdict(N, nd, ci, med, hit))
    return res


def print_table(title, res):
    print(f"\n=== {title} (+30min placebo 对照 lift) ===")
    hdr = f"{'regime':6} {'N':>4} {'天':>3} {'+15m%':>7} {'+30m%':>7} {'CI95%':>16} {'命中%':>6} {'EOD%':>7} {'p':>5}  verdict"
    print(hdr)
    print("-" * len(hdr))
    for r in ("up", "flat", "down"):
        row = res.get(r)
        if not row:
            continue
        ci = row["ci"]
        cis = f"[{ci[0]*100:+.2f},{ci[1]*100:+.2f}]" if ci[0] is not None else f"{'—':>16}"
        l15 = f"{row['l15_med']*100:+.2f}" if row["l15_med"] is not None else "—"
        hs = f"{row['hit']:.0f}" if row["hit"] is not None else "—"
        es = f"{row['eod_med']*100:+.2f}" if row["eod_med"] is not None else "—"
        print(f"{r:6} {row['N']:>4} {row['ndays']:>3} {l15:>7} {row['lift30_med']*100:>+7.2f} "
              f"{cis:>16} {hs:>6} {es:>7} {row['sign_p']:>5}  {row['verdict']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="file:/opt/futu_trade_sys/simple_trade/data/trade.db?mode=ro")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    conn = sqlite3.connect(args.db, uri=True)
    rng = random.Random(20260624)

    try:
        today, days, minute, kc = load(conn)
    except sqlite3.OperationalError as e:
        print(f"无法加载 ticker_minute（本表仅生产库有，180天聚合）：{e}")
        print("本回测须在生产库(只读)运行：")
        print("  --db 'file:/opt/futu_trade_sys/simple_trade/data/trade.db?mode=ro'")
        return
    print("# 早段突破抢筹 合流判据回测 (read-only)")
    print(f"# DB={args.db}  完整交易日={len(days)} ({days[0] if days else '-'}..{days[-1] if days else '-'})  today(剔除)={today}")
    if not days:
        print("无完整交易日数据。")
        return

    reg = {}
    for i, d in enumerate(days):
        prev = days[i - 1] if i > 0 else None
        reg[d], _, _ = regime_of(d, prev, minute, kc)

    # 触发/合流池信号：accel_in / reversal_bull / mega_buy
    ph = ",".join("?" * len(days))
    pool = defaultdict(list)  # (d,code) -> [(min, type)]
    for d, t, code, stp in conn.cursor().execute(
        f"SELECT trade_date, time, stock_code, signal_type FROM sniper_signals "
        f"WHERE trade_date IN ({ph}) AND signal_type IN ('accel_in','reversal_bull','mega_buy')",
        days,
    ).fetchall():
        if t and len(t) >= 5:
            pool[(d, code)].append((to_min(t), stp))

    scores = load_capital_scores(conn, days)

    # 资金评分覆盖率(诚实报)
    trig_keys = set()
    for (d, code), lst in pool.items():
        if any(stp in TRIGGER_TYPES for _, stp in lst):
            trig_keys.add((d, code))
    cov_by_day = defaultdict(lambda: [0, 0])  # day -> [有评分, 总]
    for (d, code) in trig_keys:
        cov_by_day[d][1] += 1
        if scores.get((d, code)):
            cov_by_day[d][0] += 1

    # 合成 early_breakout(全判据) + noscore 变体 + baseline
    synth, synth_noscore = [], []
    base = {t: [] for t in POOL_TYPES}
    for (d, code), lst in pool.items():
        mins = [m for m, _ in lst]
        for m, stp in lst:
            base[stp].append((d, code, m))
            if stp not in TRIGGER_TYPES:
                continue
            conf = any(abs(m2 - m) <= CONF_WINDOW for m2 in mins)  # 触发行自身满足
            if not conf:
                continue
            if (d, code) not in minute:
                continue
            am, pr = minute[(d, code)]
            g, pos = gain_pos(am, pr, m)
            early = (g is not None and g < EARLY_GAIN_CAP and (pos is None or pos <= EARLY_POS_MAX))
            if not early:
                continue
            synth_noscore.append((d, code, m))
            ser = scores.get((d, code), [])
            if crossed_up(ser, m, SCORE_CROSS, SCORE_SLOPE, SCORE_LOOKBACK):
                synth.append((d, code, m))

    sets = {
        "synth:early_breakout": dedup(synth),
        "synth:early_breakout_noscore": dedup(synth_noscore),
        "base:accel_in": dedup(base["accel_in"]),
        "base:reversal_bull": dedup(base["reversal_bull"]),
        "base:mega_buy": dedup(base["mega_buy"]),
    }

    print("\n=== 逐日 regime + 资金评分覆盖率(触发股有 capital_score 占比) ===")
    for d in days:
        cov = cov_by_day.get(d, [0, 0])
        pct = (100 * cov[0] / cov[1]) if cov[1] else 0
        print(f"   {d}  {reg[d]:5}  资金评分覆盖 {cov[0]}/{cov[1]} ({pct:.0f}%)")

    if args.probe:
        print("\n=== 各事件集计数(去重后, 分 regime) ===")
        for label, evs in sets.items():
            cnt = defaultdict(int)
            for d, _c, _a in evs:
                cnt[reg.get(d)] += 1
            print(f"   {label:30} 总{len(evs):>4}  " + str({r: cnt.get(r, 0) for r in ('up', 'flat', 'down')}))
        return

    # placebo guard：所有评估事件分钟的并集
    realmins = defaultdict(set)
    for evs in sets.values():
        for d, code, a in evs:
            realmins[(d, code)].add(a)

    results = {}
    for label, evs in sets.items():
        results[label] = summarize(eval_cells(evs, minute, reg, realmins, rng), rng)
        print_table(label, results[label])

    # ---- 开闸判定 ----
    print("\n=== 开 EARLY_BREAKOUT_ENABLED 闸判定 ===")
    eb = results.get("synth:early_breakout", {})
    base_best = {}
    for r in ("up", "flat", "down"):
        cands = [results[b].get(r, {}).get("lift30_med") for b in ("base:accel_in", "base:reversal_bull")]
        cands = [x for x in cands if x is not None]
        base_best[r] = max(cands) if cands else None
    gate_pass = False
    for r in ("up", "flat"):
        row = eb.get(r)
        if not row:
            print(f"   {r}: 无数据/insufficient")
            continue
        cond_keep = row["verdict"] == "keep"
        cond_15 = row["l15_med"] is not None and row["l15_med"] > 0
        cond_base = base_best[r] is not None and row["lift30_med"] > base_best[r]
        ok = cond_keep and cond_15 and cond_base
        gate_pass = gate_pass or ok
        print(f"   {r}: verdict={row['verdict']} keep={cond_keep} +15m>0={cond_15} "
              f">baseline({(base_best[r] or 0)*100:+.2f}%)={cond_base} → {'PASS' if ok else 'no'}")
    down_row = eb.get("down")
    if down_row and down_row["verdict"] == "keep" and not gate_pass:
        print("   注意：仅 down 命中——追红入跌(placebo 陷阱)，**不开**。")
    print(f"\n   >>> 开闸结论：{'PASS — 可翻 EARLY_BREAKOUT_ENABLED=True' if gate_pass else 'FAIL/不足 — 保持 OFF，每周累积重跑'}")

    if args.json:
        import json
        def _clean(res):
            o = {}
            for r, row in res.items():
                rr = dict(row)
                rr["ci"] = [round(x, 5) if x is not None else None for x in row["ci"]]
                for k in ("lift30_med", "l15_med", "eod_med"):
                    if rr.get(k) is not None:
                        rr[k] = round(rr[k], 5)
                o[r] = rr
            return o
        out = {"days": days, "regime": reg, "gate_pass": gate_pass,
               "results": {k: _clean(v) for k, v in results.items()}}
        with open(args.json, "w") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(f"JSON → {args.json}")


if __name__ == "__main__":
    main()
