#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日线多因子建仓信号回测(read-only)。

用户设计:资金因子(主力流入达到该股**历史上涨时**的流入基准,自适应每股)+ 技术因子(日线位置),
两者满足才建仓。破"同类股用绝对值"(用自身上涨基准)、破"高位接盘"(加日线位置)。

口径:
- 上涨流入基准 = 每股、信号日**之前**当日涨幅≥3% 的日子的 capital_flow_daily.net_inflow 中位(≥3个才有)。
- 资金达标 = 信号日 net_inflow ≥ 该基准。
- 日线位置(两组): 低位组 = close 在近20日区间下半部(pos<0.5); 突破组 = close 突破前20日最高。
- 前向 = 次日 close/close - 1。
严格防前视(基准/位置只用信号日及之前);placebo=全部可评估信号日的前向均值(市场基准);bootstrap CI。
只 SELECT,mode=ro。用法: python3 buy_daily_factor_eval.py [--db ...]
"""
import argparse
import random
import sqlite3
import statistics as st
from collections import defaultdict

UP_TH = 0.03          # 上涨日: 当日涨幅≥3%
POS_LOW = 0.5         # 低位组: 近20日区间位置 < 0.5
W = 20               # 近20日窗口
MIN_BASE = 3         # 至少3个历史上涨日才有基准
MIN_N = 30
MIN_DAYS = 10
BOOT = 1000
rng = random.Random(20260624)


def boot_ci(xs, base):
    if len(xs) < 2:
        return (float("nan"), float("nan"))
    k = len(xs)
    ms = sorted(sum(xs[rng.randrange(k)] for _ in range(k)) / k - base for _ in range(BOOT))
    return ms[int(0.025 * BOOT)], ms[int(0.975 * BOOT)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="file:simple_trade/data/trade.db?mode=ro")
    args = ap.parse_args()
    con = sqlite3.connect(args.db, uri=True)
    c = con.cursor()
    kl = defaultdict(list)
    for code, tk, close in c.execute(
        "SELECT stock_code, time_key, close_price FROM kline_data "
        "WHERE close_price > 0 ORDER BY stock_code, time_key"):
        kl[code].append((tk[:10], float(close)))
    cfd = {}
    for code, d, net in c.execute(
        "SELECT stock_code, date, net_inflow FROM capital_flow_daily WHERE net_inflow IS NOT NULL"):
        cfd[(code, d[:10])] = float(net)
    con.close()

    low_grp, brk_grp, placebo = [], [], []
    samples = []
    for code, seq in kl.items():
        dates = [d for d, _ in seq]
        closes = [cl for _, cl in seq]
        n = len(seq)
        up_pool = []
        for i in range(n):
            d, close = dates[i], closes[i]
            has = (code, d) in cfd
            if has and len(up_pool) >= MIN_BASE and i >= W and i + 1 < n:
                base = st.median(up_pool)
                netd = cfd[(code, d)]
                fwd = closes[i + 1] / close - 1.0
                placebo.append(fwd)
                if netd >= base:                      # 资金达标
                    win = closes[i - W + 1:i + 1]
                    mx, mn = max(win), min(win)
                    pos = (close - mn) / (mx - mn) if mx > mn else 0.5
                    breakout = close > max(closes[i - W:i])
                    if pos < POS_LOW:
                        low_grp.append((d, fwd))
                        samples.append(("低位", code, d, base, netd, pos, fwd))
                    if breakout:
                        brk_grp.append((d, fwd))
                        samples.append(("突破", code, d, base, netd, pos, fwd))
            if has and i > 0 and close / closes[i - 1] - 1.0 >= UP_TH:
                up_pool.append(cfd[(code, d)])

    pbase = st.mean(placebo) if placebo else 0.0
    print("== 日线多因子建仓回测(资金达标 + 日线位置) ==")
    print("可评估信号日(市场基准池) N=%d  次日前向均值(placebo)=%+.3f%%\n" % (len(placebo), pbase * 100))

    def rep(name, g):
        rs = [r for _, r in g]
        if not rs:
            print("  %s N=0" % name); return
        n = len(rs); nd = len(set(d for d, _ in g))
        mean = st.mean(rs)
        lift = mean - pbase
        lo, hi = boot_ci(rs, pbase)
        hit = sum(1 for r in rs if r > 0) / n * 100
        gate = "" if (n >= MIN_N and nd >= MIN_DAYS) else "  [样本不足]"
        v = "EDGE+" if (lo > 0 and lift >= 0.003) else ("no_edge" if lo <= 0 <= hi else "")
        print("  %-12s N=%-5d 天=%d 次日前向=%+.3f%% lift=%+.3f%% CI[%+.3f,%+.3f]%% 涨命中=%.0f%% %s%s"
              % (name, n, nd, mean * 100, lift * 100, lo * 100, hi * 100, hit, v, gate))

    rep("低位组", low_grp)
    rep("突破组", brk_grp)
    rep("两组合并", low_grp + brk_grp)

    print("\n【多股抽样(每只≤1笔,看是否真在'资金达标+位置')】")
    seen = set()
    for s in samples:
        grp, code, d, base, netd, pos, fwd = s
        if code in seen:
            continue
        seen.add(code)
        print("  [%s] %s %s | 上涨基准=%+.0f万 当日流入=%+.0f万(达标) 位置=%.2f 次日%+.2f%%"
              % (grp, code, d, base / 1e4, netd / 1e4, pos, fwd * 100))
        if len(seen) >= 14:
            break
    print("\n注:capital_flow_daily 仅46天→每股上涨日少、基准薄=初步;严格防前视;前向次日close→close;"
          "lift=信号前向−全样本前向(剔市场);CI 排0且lift≥0.3%%才算边际。")


if __name__ == "__main__":
    main()
