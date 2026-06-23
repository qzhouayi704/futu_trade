#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""入场择时 🟢/🔴 「regime 分行情」边际回测 (read-only)。

回答一个问题：把 regime 分类从「只看涨幅中位 ±0.5%」(A·旧) 升级为「中位+均值+宽度」(B·新)后，
- 防守日(down) 的 🟢green 是否如 2026-06-23 实测那样负边际(anti)？
- 进攻/中性日(up/flat) 的 🟢green 是否仍保留正边际(不被误伤)？
- 🔴red(别追) 是否各行情都站得住？
据此为 entry_timing.py 的 regime_mean_down / regime_breadth_down 选阈值（先上保守默认、再据此调）。

**不是**逐信号"企稳确认门"——那条路(entry_timing_gate_backtest.py G1/G2/G3)已全部 placebo 不显著、别重做。
这里只重切 regime 标签、复用唯一口径评估器的前向/对照/判决，保持口径一致、可比、可复现。

复用 canonical_signal_eval 的 load/regime_of(旧·冻结)/fwd/boot_ci/verdict/常量；新增 regime_of_new。
只 SELECT，--db 默认 mode=ro。用法：
  python3 entry_regime_split_backtest.py [--db 'file:/path/trade.db?mode=ro'] [--grid]
"""
import argparse
import random
import statistics as st
from collections import defaultdict

import canonical_signal_eval as C


def regime_of_new(day, minute, kc, mean_down, breadth_down):
    """新 regime：中位+均值+宽度。中位/均值偏空 *或* 上涨股不过半 → down。

    与 entry_timing.market_regime 同口径(口径升级，非临时 flag)。返回 (reg, med, mean, up_ratio, n)。
    """
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
        return "flat", 0.0, 0.0, 0.0, 0
    med = st.median(rets)
    mean_v = st.mean(rets)
    up_ratio = sum(1 for r in rets if r > 0) / len(rets)
    is_up = (med >= C.REGIME_BAND and up_ratio >= 0.5)
    is_down = (not is_up and (med <= -C.REGIME_BAND or mean_v <= mean_down
                              or up_ratio <= breadth_down))
    reg = "up" if is_up else ("down" if is_down else "flat")
    return reg, med, mean_v, up_ratio, len(rets)


def gather_entry_signals(conn, days):
    """entry:green / entry:red，15min 同(日,股,灯)去重。返回 [(date, code, type, abs_min)]。"""
    cur = conn.cursor()
    ph = ",".join("?" * len(days))
    sigs = []
    for d, t, code, light in cur.execute(
        f"SELECT trade_date, time, stock_code, light FROM entry_timing_signals "
        f"WHERE trade_date IN ({ph})", days).fetchall():
        k = 'entry:' + (light or '')
        if k in C.DIRS and t and len(t) >= 5:
            sigs.append((d, code, k, C.to_min(t)))
    sigs.sort(key=lambda x: (x[0], x[2], x[1], x[3]))
    last, ded = {}, []
    for d, code, k, a in sigs:
        kk = (d, k, code)
        if kk in last and a - last[kk] < C.DEDUP_MIN:
            continue
        last[kk] = a
        ded.append((d, code, k, a))
    return ded


def eval_cells(ded, minute, reg_map, rng):
    """对每条信号算 +30m placebo 对照 lift，按 (type × regime) 聚合。复用唯一口径。"""
    realmins = defaultdict(set)
    for d, code, k, a in ded:
        realmins[(d, code)].add(a)
    cells = defaultdict(lambda: {'l30': [], 'hit': [], 'neu': 0, 'days': set()})
    for d, code, k, a in ded:
        key = (d, code)
        if key not in minute:
            continue
        am, pr = minute[key]
        s30 = C.fwd(am, pr, a, C.H_PRIMARY)
        if s30 is None:
            continue
        forb = realmins[key]
        cand = [m for m in am if all(abs(m - r) >= C.GUARD for r in forb)
                and (m + C.H_PRIMARY) <= am[-1]]
        if len(cand) < 2:
            continue
        pick = rng.sample(cand, min(C.CONTROLS, len(cand)))
        c30s = [C.fwd(am, pr, c, C.H_PRIMARY) for c in pick]
        c30s = [x for x in c30s if x is not None]
        if not c30s:
            continue
        c30 = st.mean(c30s)
        dr = C.DIRS[k]
        lift = dr * (s30 - c30)
        cell = cells[(k, reg_map.get(d))]
        cell['l30'].append(lift)
        cell['days'].add(d)
        if abs(s30) < C.NOISE:
            cell['neu'] += 1
        else:
            cell['hit'].append(1 if lift > 0 else 0)
    return cells


def print_table(title, cells, rng):
    print(f"\n=== {title} ===")
    hdr = (f"{'信号':12} {'regime':6} {'N':>4} {'天':>3} {'lift中位%':>9} "
           f"{'CI95%':>16} {'命中%':>6} {'verdict'}")
    print(hdr)
    print('-' * len(hdr))
    for k in ('entry:green', 'entry:red'):
        for r in ('up', 'flat', 'down'):
            c = cells.get((k, r))
            if not c or not c['l30']:
                print(f"{k:12} {r:6} {'0':>4} {'0':>3} {'—':>9} {'—':>16} {'—':>6} insufficient_data")
                continue
            l30 = c['l30']
            N = len(l30)
            nd = len(c['days'])
            med = st.median(l30)
            ci = C.boot_ci(l30, rng)
            hit = (100 * sum(c['hit']) / len(c['hit'])) if c['hit'] else None
            v = C.verdict(N, nd, ci, med, hit)
            cis = f"[{ci[0]*100:+.2f},{ci[1]*100:+.2f}]" if ci[0] is not None else f"{'—':>16}"
            hs = f"{hit:.0f}" if hit is not None else "—"
            print(f"{k:12} {r:6} {N:>4} {nd:>3} {med*100:>+9.2f} {cis:>16} {hs:>6} {v}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="file:/opt/futu_trade_sys/simple_trade/data/trade.db?mode=ro")
    ap.add_argument("--grid", action="store_true", help="网格扫描 breadth_down × mean_down 选阈值")
    ap.add_argument("--mean-down", type=float, default=-0.005)
    ap.add_argument("--breadth-down", type=float, default=0.45)
    args = ap.parse_args()
    import sqlite3
    conn = sqlite3.connect(args.db, uri=True)
    rng = random.Random(C.SEED)

    today, days, minute, kc = C.load(conn)
    print(f"# 入场择时 regime 分行情边际回测  (复用 canonical KOUJING={C.KOUJING_VERSION})")
    print(f"# DB={args.db}  完整交易日={len(days)} ({days[0] if days else '-'}..{days[-1] if days else '-'})  today(剔除)={today}")
    if not days:
        print("无完整交易日数据。")
        return

    # 逐日 regime 台账：A(旧·只中位) vs B(新·中位+均值+宽度)
    regA, regB = {}, {}
    print("\n=== 逐日 regime 台账  A=旧(中位±0.5%)  B=新(中位+均值+宽度) ===")
    print(f"   {'date':10} {'A':5} {'B':5} {'中位%':>7} {'均值%':>7} {'上涨占比':>7} {'活跃':>5}  {'重判'}")
    for i, d in enumerate(days):
        ra, medA, _ = C.regime_of(d, days[i-1] if i > 0 else None, minute, kc)
        rb, med, mean_v, up_ratio, n = regime_of_new(d, minute, kc, args.mean_down, args.breadth_down)
        regA[d], regB[d] = ra, rb
        flag = "← 重判" if ra != rb else ""
        print(f"   {d:10} {ra:5} {rb:5} {med*100:>+7.2f} {mean_v*100:>+7.2f} {up_ratio:>7.2f} {n:>5}  {flag}")

    ded = gather_entry_signals(conn, days)
    print(f"\n入场择时信号(去重后) 共 {len(ded)} 条")

    cellsA = eval_cells(ded, minute, regA, rng)
    cellsB = eval_cells(ded, minute, regB, rng)
    print_table("A·旧 regime(中位±0.5%)  per-(灯 × regime) +30m placebo lift", cellsA, rng)
    print_table("B·新 regime(中位+均值+宽度) per-(灯 × regime) +30m placebo lift", cellsB, rng)

    if args.grid:
        def summ(cell):
            if not cell or not cell['l30']:
                return "0/—/—/insuf"
            l = cell['l30']
            med = st.median(l)
            hit = (100 * sum(cell['hit']) / len(cell['hit'])) if cell['hit'] else None
            hit_s = f"{hit:.0f}" if hit is not None else "—"
            v = C.verdict(len(l), len(cell['days']), C.boot_ci(l, rng), med, hit)
            return f"{len(l)}/{med*100:+.2f}/{hit_s}/{v}"

        print("\n=== 网格扫描：找『杀掉 down-green 负边际、不伤 up/flat-green』的阈值 ===")
        print(f"   {'breadth_down':>12} {'mean_down':>10}  down-green(N/lift%/hit/verdict)   up+flat-green(N/lift%/hit)")
        for bd in (0.40, 0.45, 0.50):
            for md in (-0.003, -0.005, -0.007):
                regG = {d: regime_of_new(d, minute, kc, md, bd)[0] for d in days}
                cg = eval_cells(ded, minute, regG, rng)
                dn = cg.get(('entry:green', 'down'))
                upf_l = [x for r in ('up', 'flat') if cg.get(('entry:green', r))
                         for x in cg[('entry:green', r)]['l30']]
                if upf_l:
                    upf_hit = 100 * sum(1 for x in upf_l if x > 0) / len(upf_l)
                    upf_s = f"{len(upf_l)}/{st.median(upf_l)*100:+.2f}/{upf_hit:.0f}"
                else:
                    upf_s = "0/—/—"
                print(f"   {bd:>12.2f} {md:>10.3f}  {summ(dn):<32} {upf_s}")

    print(f"\n注：ticker_minute 现仅 {len(days)} 个完整交易日 → 多数格子 insufficient_data＝正确诚实输出。"
          f" 每周累积重跑，待 down-green 出现稳定 anti / up-flat-green 站住 keep，再冻结阈值回填 entry_timing.py。")


if __name__ == "__main__":
    main()
