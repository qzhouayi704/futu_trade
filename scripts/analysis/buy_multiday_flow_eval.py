#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""买点多日资金流回测（read-only research track）。

诊断结论(2026-06-24)：买点信号(TREND/狙击/动量)几乎只看日内资金流，多日表 capital_flow_daily
基本不入买点；而"多日连续流入买点"R11 曾回测无边际被降级。本脚本在动手改买点逻辑前，
先用现成日线数据**验证**多日资金流是否对**次日前向收益**有边际(alpha)：

  假设1(否决/降权)：连续净流出 K 天 → 次日前向收益偏负？（若是，可作为买点 veto/降权）
  假设2(确认)      ：连续净流入 K 天 → 次日前向收益偏正？（若是，可作为买点确认）

口径：
- 事件 = capital_flow_daily 里每个 (stock, date)，按 net_inflow 符号求"连续同向天数"streak。
- 前向收益 = kline_data 次一交易日 close / 当日 close − 1（close-to-close）。
- **市场相对**(关键)：rel = 个股前向 − 当日所有评估股前向的中位数（剔市场 beta，看真 alpha）。
  记忆教训：很多资金流"边际"在市场相对口径下 ≈ 0，只是肥尾/偏收盘撑出来的。
- 样本闸门：每格 N>=30 且独立交易日>=10 才出判决，否则 insufficient_data（诚实）。
- bootstrap 1000 次给 rel 均值 95% CI；CI 排除 0 且 |rel|>=0.2% 才算有边际。

只 SELECT，--db 默认 mode=ro。用法：
  python3 buy_multiday_flow_eval.py [--db 'file:/path/trade.db?mode=ro']
"""
import argparse
import random
import sqlite3
import statistics as st
from collections import defaultdict

SEED = 20260624
MIN_N = 30
MIN_DAYS = 10
BOOT = 1000
EDGE_REL = 0.002          # |市场相对均值| >= 0.2% 才算有边际
HIT_FLOOR = 0.005         # |前向| < 0.5% 记 NEUTRAL，不计命中分母


def _date(s):
    return s[:10] if s else s


def load(conn):
    cur = conn.cursor()
    # 多日资金流符号：{code: [(date, sign)]}（按日期升序）
    flow = defaultdict(list)
    for code, d, net in cur.execute(
        "SELECT stock_code, date, net_inflow FROM capital_flow_daily "
        "WHERE net_inflow IS NOT NULL ORDER BY stock_code, date"
    ):
        flow[code].append((_date(d), 1 if net > 0 else (-1 if net < 0 else 0)))
    # 日线收盘：{code: [(date, close)]}（按日期升序）
    kl = defaultdict(list)
    for code, tk, close in cur.execute(
        "SELECT stock_code, time_key, close_price FROM kline_data "
        "WHERE close_price IS NOT NULL AND close_price > 0 ORDER BY stock_code, time_key"
    ):
        kl[code].append((_date(tk), float(close)))
    return flow, kl


def streak_at(signs, idx):
    """signs[idx] 结尾的连续同向天数（带号）：返回 (方向, 长度)。0 视为中断。"""
    s = signs[idx]
    if s == 0:
        return 0, 0
    n = 1
    j = idx - 1
    while j >= 0 and signs[j] == s:
        n += 1
        j -= 1
    return s, n


def build_events(flow, kl):
    """对齐 flow 与 kline，产出事件 [(date, code, dir, streak_len, fwd_raw)]。"""
    events = []
    for code, fl in flow.items():
        kdates = kl.get(code)
        if not kdates or len(kdates) < 2:
            continue
        # kline 日期→收盘 + 次一交易日收盘
        kmap = {d: c for d, c in kdates}
        korder = [d for d, _ in kdates]
        kpos = {d: i for i, d in enumerate(korder)}
        signs = [s for _, s in fl]
        fdates = [d for d, _ in fl]
        for i, d in enumerate(fdates):
            if d not in kpos:
                continue
            pi = kpos[d]
            if pi + 1 >= len(korder):
                continue  # 无次日
            c0 = kmap[korder[pi]]
            c1 = kmap[korder[pi + 1]]
            if c0 <= 0:
                continue
            fwd = c1 / c0 - 1.0
            dr, ln = streak_at(signs, i)
            if dr == 0:
                continue
            events.append((d, code, dr, ln, fwd))
    return events


def market_relative(events):
    """rel = 个股前向 − 当日所有事件前向中位数。返回 [(date,code,dir,len,fwd,rel)]。"""
    by_day = defaultdict(list)
    for d, code, dr, ln, fwd in events:
        by_day[d].append(fwd)
    med = {d: st.median(v) for d, v in by_day.items() if v}
    out = []
    for d, code, dr, ln, fwd in events:
        out.append((d, code, dr, ln, fwd, fwd - med.get(d, 0.0)))
    return out


def boot_ci(xs, rng, n=BOOT):
    if len(xs) < 2:
        return (float("nan"), float("nan"))
    means = []
    k = len(xs)
    for _ in range(n):
        s = sum(xs[rng.randrange(k)] for _ in range(k)) / k
        means.append(s)
    means.sort()
    return means[int(0.025 * n)], means[int(0.975 * n)]


def verdict(n, days, rel_mean, lo, hi):
    if n < MIN_N or days < MIN_DAYS:
        return "insufficient_data"
    if lo > 0 and rel_mean >= EDGE_REL:
        return "EDGE+ (利多/确认有效)"
    if hi < 0 and rel_mean <= -EDGE_REL:
        return "EDGE- (利空/可做否决)"
    return "no_edge (~0, 别加进买点)"


def report_bucket(name, rows, rng):
    """rows: [(date,code,dir,len,fwd,rel)]。"""
    if not rows:
        print(f"  {name:<28} N=0")
        return
    n = len(rows)
    days = len(set(r[0] for r in rows))
    raws = [r[4] for r in rows]
    rels = [r[5] for r in rows]
    rel_mean = st.mean(rels)
    raw_mean = st.mean(raws)
    lo, hi = boot_ci(rels, rng)
    # 命中：rel 方向（事件方向 dir：+1 期望 rel>0；−1 期望 rel<0），|raw|>=0.5% 才计
    eff = [r for r in rows if abs(r[4]) >= HIT_FLOOR]
    if eff:
        hit = sum(1 for r in eff if (r[5] > 0) == (r[2] > 0)) / len(eff) * 100
    else:
        hit = float("nan")
    v = verdict(n, days, rel_mean, lo, hi)
    print(f"  {name:<28} N={n:<5} 天={days:<3} 原始={raw_mean*100:+.2f}% "
          f"市场相对={rel_mean*100:+.2f}% CI[{lo*100:+.2f},{hi*100:+.2f}]% "
          f"命中={hit:.0f}% → {v}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="file:simple_trade/data/trade.db?mode=ro")
    args = ap.parse_args()
    rng = random.Random(SEED)
    conn = sqlite3.connect(args.db, uri=True)
    flow, kl = load(conn)
    conn.close()
    events = build_events(flow, kl)
    rows = market_relative(events)
    print(f"== 买点多日资金流回测 == 事件={len(rows)} 股票={len(set(r[1] for r in rows))} "
          f"交易日={len(set(r[0] for r in rows))}")
    if rows:
        base = st.mean([r[4] for r in rows])
        print(f"   baseline 次日前向(全样本)={base*100:+.2f}% （市场相对均值≈0 是定义使然）\n")

    print("【假设1：连续净流出 → 次日是否偏弱(可做买点否决)】")
    out1 = [r for r in rows if r[2] < 0 and r[3] == 1]
    out2 = [r for r in rows if r[2] < 0 and r[3] == 2]
    out3 = [r for r in rows if r[2] < 0 and r[3] >= 3]
    outge2 = [r for r in rows if r[2] < 0 and r[3] >= 2]
    report_bucket("流出 1 天", out1, rng)
    report_bucket("流出 2 天", out2, rng)
    report_bucket("流出 >=3 天", out3, rng)
    report_bucket("流出 >=2 天(合并)", outge2, rng)

    print("\n【假设2：连续净流入 → 次日是否偏强(可做买点确认)】")
    in1 = [r for r in rows if r[2] > 0 and r[3] == 1]
    in2 = [r for r in rows if r[2] > 0 and r[3] == 2]
    in3 = [r for r in rows if r[2] > 0 and r[3] >= 3]
    inge2 = [r for r in rows if r[2] > 0 and r[3] >= 2]
    report_bucket("流入 1 天", in1, rng)
    report_bucket("流入 2 天", in2, rng)
    report_bucket("流入 >=3 天", in3, rng)
    report_bucket("流入 >=2 天(合并)", inge2, rng)

    print("\n判读：只有「市场相对」CI 排除 0 且 |均值|>=0.2% 才算真边际；否则别加进买点(印证 R11)。")


if __name__ == "__main__":
    main()
