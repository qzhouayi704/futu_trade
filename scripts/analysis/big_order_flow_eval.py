#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大买/大卖(大单/超大单/中小单分档) × 股价走势相关性评估 + 主力资金提醒事后成绩单。

口径版本 1.0 (2026-07-13)

Track A: capital_flow_minute × ticker_minute 重建每分钟 15min 滚动窗(对齐生产累加器 900s),
         按 大单合并/超大单/纯大单/中小单 分档抽事件 → 前向收益 / 安慰剂 lift / 领先滞后。
Track B: signal_pipeline(source='capital_trend') 已发提醒
         (大额流入/持仓流出/RISING/FALLING-retreat/FALLING-distribution) 事后收益 + 阈值-覆盖率曲线。

方法论对齐 canonical_signal_eval.py:
  安慰剂对照(同股同日随机分钟, 距同族事件≥GUARD) + bootstrap CI + N≥30/独立天数≥10 闸门 + 因果取价。
只读连库(mode=ro), 固定 seed, 结果可重复。

跑法(生产服务器):
  .venv/bin/python scripts/analysis/big_order_flow_eval.py [--json /tmp/bofe.json]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
import warnings
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np

warnings.filterwarnings("ignore")

KOUJING = "1.0"
SEED = 20260713
W = 15                      # 滚动窗(交易分钟), 对齐生产 CAPITAL_TICK_WINDOW_SEC=900
HORIZONS = (5, 15, 30, 60)  # 分钟级前向
ALL_H = (5, 15, 30, 60, "eod", "next")
CONTROLS = 5
GUARD = 20                  # 安慰剂距同族事件的最小分钟距离
BOOT = 1000
MIN_N = 30
MIN_DAYS = 10
MIN_DAY_ROWS = 5000         # ticker_minute 当日行数闸门(剔残缺日)
MIN_DAY_CFM_ROWS = 300      # capital_flow_minute 当日行数闸门
KEEP_LIFT = 0.003
KEEP_HIT = 0.58
DEDUP_MIN = 15              # 同(股,日,族)事件统计去重间隔
SUPER_MULT = 3.0            # 超大单门槛 = 大单门槛 × 3 (标定器 SUPER_MULT)
HK = timezone(timedelta(hours=8))
CHECK_CASES = (("HK.00100", "2026-07-09"),)  # 口径交叉校验: 备忘录 超大单净≈-5341万 纯大单净≈+5804万

DEFAULT_DB = "file:/opt/futu_trade_sys/simple_trade/data/trade.db?mode=ro"


# ---------------------------------------------------------------- 分钟格
def _build_grid():
    mins = []
    t = 9 * 60 + 30
    while t < 12 * 60:
        mins.append(t)
        t += 1
    t = 13 * 60
    while t <= 16 * 60:
        mins.append(t)
        t += 1
    return ["%02d:%02d" % (t // 60, t % 60) for t in mins]


GRID = _build_grid()
IDX = {m: i for i, m in enumerate(GRID)}
NG = len(GRID)
LUNCH_OPEN = IDX["13:00"]
TOD_SPLIT1 = IDX["10:30"]


def clip_minute(m: str) -> str:
    if m < "09:30":
        return "09:30"
    if "12:00" <= m < "13:00":
        return "11:59"
    if m > "16:00":
        return "16:00"
    return m


def tod_bucket(i: int) -> str:
    if i <= TOD_SPLIT1:
        return "早盘≤10:30"
    if i < LUNCH_OPEN:
        return "上午盘中"
    return "午后"


# ---------------------------------------------------------------- 数据加载
def full_days(conn):
    tm = dict(conn.execute("SELECT trade_date, COUNT(*) FROM ticker_minute GROUP BY 1"))
    cf = dict(conn.execute("SELECT trade_date, COUNT(*) FROM capital_flow_minute GROUP BY 1"))
    today = datetime.now(HK).strftime("%Y-%m-%d")
    days, dropped = [], []
    for d in sorted(set(tm) | set(cf)):
        if d >= today:
            dropped.append((d, "当日未收盘"))
        elif tm.get(d, 0) < MIN_DAY_ROWS:
            dropped.append((d, "ticker_minute行数%d<%d" % (tm.get(d, 0), MIN_DAY_ROWS)))
        elif cf.get(d, 0) < MIN_DAY_CFM_ROWS:
            dropped.append((d, "capital_flow_minute行数%d<%d" % (cf.get(d, 0), MIN_DAY_CFM_ROWS)))
        else:
            days.append(d)
    return days, dropped


def load_kline(conn, codes_hint_days):
    """(code -> [(date, close), ...升序]) 用于次日收益。"""
    kmap = defaultdict(list)
    for code, tk, close in conn.execute(
        "SELECT stock_code, substr(time_key,1,10), close_price FROM kline_data "
        "WHERE time_key >= '2026-06-01' ORDER BY stock_code, time_key"
    ):
        if close:
            kmap[code].append((tk, float(close)))
    nxt = {}
    for code, rows in kmap.items():
        for j in range(len(rows) - 1):
            nxt[(code, rows[j][0])] = rows[j + 1][1]
    return nxt  # (code, date) -> 次一交易日 close


_FIELDS = ("tmb", "tms", "bb", "bs", "sb", "ss", "cb", "cs")


def load_day(conn, day):
    recs = {}

    def rec(code):
        r = recs.get(code)
        if r is None:
            r = {k: np.zeros(NG) for k in _FIELDS}
            r["price"] = np.full(NG, np.nan)
            recs[code] = r
        return r

    for code, m, price, buy, sell in conn.execute(
        "SELECT stock_code, minute, price, buy_amt, sell_amt FROM ticker_minute "
        "WHERE trade_date=? ORDER BY minute", (day,)
    ):
        i = IDX[clip_minute(m)]
        r = rec(code)
        if price and price > 0:
            r["price"][i] = float(price)  # 同格多源分钟时后写覆盖(ORDER BY minute)
        r["tmb"][i] += float(buy or 0)
        r["tms"][i] += float(sell or 0)
    for code, m, bb, bs, sb, ss, cb, cs, thr in conn.execute(
        "SELECT stock_code, minute, big_buy_amt, big_sell_amt, super_buy_amt, super_sell_amt, "
        "big_buy_count, big_sell_count, big_order_threshold FROM capital_flow_minute "
        "WHERE trade_date=? ORDER BY minute", (day,)
    ):
        r = recs.get(code)
        if r is None:
            continue  # 有大单归档却缺 ticker_minute(异常), 跳过
        i = IDX[clip_minute(m)]
        r["bb"][i] += float(bb or 0)
        r["bs"][i] += float(bs or 0)
        r["sb"][i] += float(sb or 0)
        r["ss"][i] += float(ss or 0)
        r["cb"][i] += float(cb or 0)
        r["cs"][i] += float(cs or 0)
        if thr and thr > 0:
            r["thr"] = float(thr)
    return recs


# ---------------------------------------------------------------- 派生序列
def _ffill(p):
    mask = np.isfinite(p)
    if mask.sum() < 30:  # 全天成交分钟太少, 前向收益没意义
        return None
    idx = np.where(mask, np.arange(NG), 0)
    np.maximum.accumulate(idx, out=idx)
    out = p[idx]
    out[: int(np.argmax(mask))] = np.nan
    return out


def _roll(x):
    c = np.cumsum(x)
    r = c.copy()
    r[W:] = c[W:] - c[:-W]
    return r


def derive(r, code, day, nxt_close):
    p = _ffill(r["price"])
    if p is None:
        return None
    d = {"p": p, "thr": r.get("thr")}
    big = r["bb"] - r["bs"]
    sup = r["sb"] - r["ss"]
    d["big_m"], d["sup_m"] = big, sup
    d["ms_m"] = (r["tmb"] - r["tms"]) - big
    d["Wbig"], d["Wsup"] = _roll(big), _roll(sup)
    d["Wpl"] = d["Wbig"] - d["Wsup"]
    d["Wms"] = _roll(d["ms_m"])
    d["Wbb"], d["Wbs"] = _roll(r["bb"]), _roll(r["bs"])
    d["nb"] = r["cb"] > 0        # 该分钟有新大单买(含超大)
    d["ns"] = r["cs"] > 0
    d["sbnz"] = r["sb"] > 0      # 该分钟有超大单买
    d["ssnz"] = r["ss"] > 0
    d["plb"] = (r["bb"] - r["sb"]) > 0   # 该分钟有纯大单买
    d["pls"] = (r["bs"] - r["ss"]) > 0
    ret = {}
    for h in HORIZONS:
        a = np.full(NG, np.nan)
        a[:-h] = p[h:] / p[:-h] - 1.0
        ret[h] = a
    ret["eod"] = p[-1] / p - 1.0
    nc = nxt_close.get((code, day))
    ret["next"] = (nc / p - 1.0) if nc else np.full(NG, np.nan)
    d["ret"] = ret
    a = np.full(NG, np.nan)
    a[W:] = p[W:] / p[:-W] - 1.0
    d["prev"] = a                # 事件前 15min 已走幅度
    r1 = np.full(NG, np.nan)
    r1[1:] = p[1:] / p[:-1] - 1.0
    r1[LUNCH_OPEN] = np.nan      # 午休跳空不算 1min 收益
    d["r1"] = r1
    return d


# ---------------------------------------------------------------- 事件族
FAM_ORDER = [
    "IN_1", "IN_2", "IN_3", "IN_5", "OUT_1", "OUT_2", "OUT_3", "OUT_5",
    "IN3_prod", "OUT1_prod",
    "SUP_IN_1", "SUP_IN_2", "SUP_OUT_1", "SUP_OUT_2",
    "PL_IN", "PL_OUT", "MS_IN", "MS_OUT",
    "DIV_SELL", "DIV_BUY",
]

FAM_DESC = {
    "IN_1": "大单净流入≥1×门槛", "IN_2": "大单净流入≥2×", "IN_3": "大单净流入≥3×", "IN_5": "大单净流入≥5×",
    "OUT_1": "大单净流出≥1×门槛", "OUT_2": "大单净流出≥2×", "OUT_3": "大单净流出≥3×", "OUT_5": "大单净流出≥5×",
    "IN3_prod": "生产口径·大额流入(3×+买占75%)", "OUT1_prod": "生产口径·净流出(1×,持仓提醒同款)",
    "SUP_IN_1": "超大单净流入≥1×超大门槛", "SUP_IN_2": "超大单净流入≥2×超大",
    "SUP_OUT_1": "超大单净流出≥1×超大门槛", "SUP_OUT_2": "超大单净流出≥2×超大",
    "PL_IN": "纯大单(不含超大)净流入≥同额", "PL_OUT": "纯大单净流出≥同额",
    "MS_IN": "中小单净流入≥同额", "MS_OUT": "中小单净流出≥同额",
    "DIV_SELL": "背离·超大卖+中小买(出货形态)", "DIV_BUY": "背离·超大买+价未涨(吸筹形态)",
}


def families(d):
    L = d.get("thr")
    if not L:
        return {}
    S = SUPER_MULT * L
    ok = np.isfinite(d["p"])
    fams = {}
    for k in (1, 2, 3, 5):
        fams["IN_%d" % k] = (+1, (d["Wbig"] >= k * L) & d["nb"])
        fams["OUT_%d" % k] = (-1, (d["Wbig"] <= -k * L) & d["ns"])
    fams["IN3_prod"] = (+1, (d["Wbig"] >= 3 * L) & (d["Wbb"] >= 3 * d["Wbs"]) & d["nb"])
    fams["OUT1_prod"] = (-1, (d["Wbig"] <= -L) & d["ns"])
    for m in (1, 2):
        fams["SUP_IN_%d" % m] = (+1, (d["Wsup"] >= m * S) & d["sbnz"])
        fams["SUP_OUT_%d" % m] = (-1, (d["Wsup"] <= -m * S) & d["ssnz"])
    # 同额对照: 三个档位都用同一金额门槛(=1×超大门槛), 比"同样一笔钱由谁买"的信息量
    fams["PL_IN"] = (+1, (d["Wpl"] >= S) & d["plb"])
    fams["PL_OUT"] = (-1, (d["Wpl"] <= -S) & d["pls"])
    fams["MS_IN"] = (+1, (d["Wms"] >= S) & (d["ms_m"] > 0))
    fams["MS_OUT"] = (-1, (d["Wms"] <= -S) & (d["ms_m"] < 0))
    fams["DIV_SELL"] = (-1, (d["Wsup"] <= -S) & (d["Wms"] > 0) & d["ssnz"])
    fams["DIV_BUY"] = (+1, (d["Wsup"] >= S) & (d["prev"] <= 0) & d["sbnz"])
    return {name: (dr, m & ok) for name, (dr, m) in fams.items()}


def pick_events(mask):
    ev, last = [], -(10 ** 9)
    for i in np.where(mask)[0]:
        if i - last >= DEDUP_MIN:
            ev.append(int(i))
            last = i
    return ev


def control_pool(mask, d, ret30):
    bad = np.zeros(NG, bool)
    for j in np.where(mask)[0]:
        bad[max(0, j - GUARD): j + GUARD + 1] = True
    ok = (~bad) & np.isfinite(d["p"]) & np.isfinite(ret30)
    return np.where(ok)[0]


# ---------------------------------------------------------------- 统计
class Agg:
    """按 (族, horizon) 聚合 lift/rel/raw。"""

    def __init__(self):
        self.cells = defaultdict(lambda: {"lift": [], "rel": [], "raw": [], "days": set()})
        self.prev = defaultdict(list)      # fam -> 已走幅度(方向签名)
        self.events = defaultdict(list)    # fam -> [(day, tod, {h: lift})]
        self.vol = defaultdict(lambda: defaultdict(int))  # fam -> day -> 去重前分钟数

    def add_event(self, fam, day, i, dr, d, ctrl_idx, med, code=""):
        rets, lifts = {}, {}
        for h in ALL_H:
            raw = float(d["ret"][h][i])
            if not np.isfinite(raw):
                continue
            cell = self.cells[(fam, h)]
            cell["raw"].append(dr * raw)
            cell["days"].add(day)
            if med is not None and np.isfinite(med[h][i]):
                cell["rel"].append(dr * (raw - float(med[h][i])))
            if len(ctrl_idx):
                cvals = d["ret"][h][ctrl_idx]
                cvals = cvals[np.isfinite(cvals)]
                if len(cvals):
                    lift = dr * (raw - float(cvals.mean()))
                    cell["lift"].append(lift)
                    lifts[h] = lift
        pv = float(d["prev"][i])
        if np.isfinite(pv):
            self.prev[fam].append(dr * pv)
        self.events[fam].append((day, tod_bucket(i), lifts, code))


_rng_np = np.random.default_rng(SEED)


def boot_ci(vals):
    arr = np.asarray(vals, float)
    n = len(arr)
    if n == 0:
        return float("nan"), float("nan")
    means = np.empty(BOOT)
    step = 100  # 分块防大 N 内存尖峰
    for s in range(0, BOOT, step):
        idx = _rng_np.integers(0, n, size=(step, n))
        means[s: s + step] = arr[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def verdict(n, days, lift_mean, ci, hit):
    if n < MIN_N or days < MIN_DAYS:
        return "样本不足"
    lo, hi = ci
    if lo > 0 and lift_mean >= KEEP_LIFT and hit >= KEEP_HIT:
        return "有边际"
    if lo > 0:
        return "弱边际"
    if hi < 0:
        return "反向!"
    return "无差异"


def cell_stats(cell):
    lifts = np.asarray(cell["lift"], float)
    n = len(lifts)
    days = len(cell["days"])
    if n == 0:
        return None
    hit = float((lifts > 0).mean())
    mean = float(lifts.mean())
    ci = boot_ci(lifts)
    rel = float(np.mean(cell["rel"])) if cell["rel"] else float("nan")
    raw = float(np.mean(cell["raw"])) if cell["raw"] else float("nan")
    return {"n": n, "days": days, "hit": hit, "lift": mean, "ci": ci, "rel": rel, "raw": raw,
            "verdict": verdict(n, days, mean, ci, hit)}


# ---------------------------------------------------------------- 领先/滞后
LL_LAGS = list(range(-30, 31))


class LeadLag:
    def __init__(self):
        self.acc = {src: {L: np.zeros(6) for L in LL_LAGS} for src in ("big", "sup")}

    def add(self, d):
        L_thr = d.get("thr")
        if not L_thr:
            return
        y = d["r1"]
        for src, x in (("big", d["big_m"] / L_thr), ("sup", d["sup_m"] / (SUPER_MULT * L_thr))):
            for L in LL_LAGS:
                if L >= 0:
                    xs = x[: NG - L] if L else x
                    ys = y[L:] if L else y
                else:
                    xs = x[-L:]
                    ys = y[: NG + L]
                m = np.isfinite(xs) & np.isfinite(ys)
                if not m.any():
                    continue
                a, b = xs[m], ys[m]
                acc = self.acc[src][L]
                acc += (len(a), a.sum(), b.sum(), (a * a).sum(), (b * b).sum(), (a * b).sum())

    def corr(self, src, L):
        n, sx, sy, sxx, syy, sxy = self.acc[src][L]
        if n < 100:
            return float("nan")
        num = n * sxy - sx * sy
        den = np.sqrt(max(n * sxx - sx * sx, 0) * max(n * syy - sy * sy, 0))
        return float(num / den) if den > 0 else float("nan")


# ---------------------------------------------------------------- Track B
CAT_DIR = {"large_inflow": +1, "RISING": +1,
           "held_outflow": -1, "FALLING_retreat": -1, "FALLING_distribution": -1}


def classify_alert(d):
    if d.get("is_held_outflow"):
        return "held_outflow"
    if d.get("is_large_inflow"):
        return "large_inflow"
    if d.get("direction") == "RISING":
        return "RISING"
    return "FALLING_distribution" if "拉高出货" in (d.get("reason") or "") else "FALLING_retreat"


def load_alerts(conn, days):
    dayset = set(days)
    by_day = defaultdict(list)
    n_bad = 0
    for td, rd in conn.execute(
        "SELECT trade_date, raw_detail FROM signal_pipeline WHERE source='capital_trend'"
    ):
        if td not in dayset:
            continue
        try:
            d = json.loads(rd)
            ts = float(d["timestamp"])
            minute = datetime.fromtimestamp(ts, HK).strftime("%H:%M")
            i = IDX[clip_minute(minute)]
            cat = classify_alert(d)
            thr = float(d.get("big_order_threshold") or 0)
            wnet = float(d.get("window_main_net") or 0)
            by_day[td].append({
                "code": d.get("stock_code"), "i": i, "cat": cat,
                "mult": abs(wnet) / thr if thr > 0 else float("nan"),
                "smult": float(d.get("strength_mult") or 0),
                "chg": float(d.get("intraday_change_pct") or 0),
            })
        except Exception:
            n_bad += 1
    return by_day, n_bad


# ---------------------------------------------------------------- 输出
def fmt_pct(x, nd=3):
    return ("%+." + str(nd) + "f%%") % (x * 100) if np.isfinite(x) else "  n/a "


def print_cell_row(name, desc, st, extra=""):
    if st is None:
        print("  %-12s %-30s 无事件" % (name, desc))
        return
    print("  %-12s %-30s N=%-6d 天=%-3d 命中=%5.1f%% lift=%s CI=[%s,%s] 市场相对=%s %s%s" % (
        name, desc, st["n"], st["days"], st["hit"] * 100, fmt_pct(st["lift"]),
        fmt_pct(st["ci"][0]), fmt_pct(st["ci"][1]), fmt_pct(st["rel"]),
        st["verdict"], extra))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--json", default=None, help="结构化结果输出路径")
    ap.add_argument("--no-leadlag", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    conn = sqlite3.connect(args.db, uri=True)
    days, dropped = full_days(conn)
    print("【大买/大卖 × 股价走势相关性评估 · 口径 v%s · seed %d · 窗口 %dmin】" % (KOUJING, SEED, W))
    print()
    print("一、数据概览")
    print("  完整交易日 %d 天: %s" % (len(days), " ".join(days)))
    for d, why in dropped:
        print("  剔除 %s (%s)" % (d, why))

    nxt_close = load_kline(conn, days)
    alerts_by_day, n_bad_alerts = load_alerts(conn, days)

    agg = Agg()
    bagg = Agg()          # Track B, fam = 提醒类别
    bevents = defaultdict(list)  # cat -> [{day,tod,mult,smult,chg,lifts{h}}]
    ll = LeadLag()
    rng = np.random.default_rng(SEED)
    day_stock_counts = []
    check_lines = []

    for day in days:
        recs = load_day(conn, day)
        derived = {}
        for code in sorted(recs):
            d = derive(recs[code], code, day, nxt_close)
            if d is not None:
                derived[code] = d
        day_stock_counts.append(len(derived))
        if not derived:
            continue
        # 当日横截面中位数(市场基准)
        med = {}
        for h in ALL_H:
            mat = np.vstack([derived[c]["ret"][h] for c in derived])
            med[h] = np.nanmedian(mat, axis=0)

        for code in sorted(derived):
            d = derived[code]
            # 口径交叉校验
            if (code, day) in CHECK_CASES:
                sup_net = float(d["sup_m"].sum())
                big_net = float(d["big_m"].sum())
                check_lines.append(
                    "  校验 %s %s: 超大单净=%.0f万 纯大单净=%.0f万 大单合并净=%.0f万"
                    " (2026-07-13 已验证与 ticker_data 同门槛全天复算精确一致;"
                    "备忘录-5341万/+5804万系当日~14:00盘中快照且门槛快照不同,不可直比)" % (
                        code, day, sup_net / 1e4, (big_net - sup_net) / 1e4, big_net / 1e4))
                row = conn.execute(
                    "SELECT cum_main_net FROM tick_capital_flow WHERE stock_code=? AND trade_date=?"
                    " ORDER BY timestamp DESC LIMIT 1", (code, day)).fetchone()
                if row:
                    check_lines.append(
                        "  对照 tick_capital_flow 收盘累计=%.0f万 (重启会清零, 仅参考)" % (float(row[0]) / 1e4))
            fams = families(d)
            for fam in FAM_ORDER:
                if fam not in fams:
                    continue
                dr, mask = fams[fam]
                cnt = int(mask.sum())
                if cnt == 0:
                    continue
                agg.vol[fam][day] += cnt
                pool = control_pool(mask, d, d["ret"][30])
                for i in pick_events(mask):
                    ctrl = (rng.choice(pool, size=min(CONTROLS, len(pool)), replace=False)
                            if len(pool) else np.empty(0, int))
                    agg.add_event(fam, day, i, dr, d, ctrl, med, code)
            if not args.no_leadlag:
                ll.add(d)

        # Track B: 该日已发提醒
        guard_minutes = defaultdict(list)
        for a in alerts_by_day.get(day, []):
            guard_minutes[(a["code"], a["cat"])].append(a["i"])
        for a in alerts_by_day.get(day, []):
            d = derived.get(a["code"])
            if d is None:
                continue
            i, cat = a["i"], a["cat"]
            dr = CAT_DIR[cat]
            mask = np.zeros(NG, bool)
            mask[guard_minutes[(a["code"], cat)]] = True
            pool = control_pool(mask, d, d["ret"][30])
            ctrl = (rng.choice(pool, size=min(CONTROLS, len(pool)), replace=False)
                    if len(pool) else np.empty(0, int))
            nev = len(bagg.events[cat])
            bagg.add_event(cat, day, i, dr, d, ctrl, med, a["code"])
            lifts = bagg.events[cat][nev][2] if len(bagg.events[cat]) > nev else {}
            bevents[cat].append({"day": day, "tod": tod_bucket(i), "mult": a["mult"],
                                 "smult": a["smult"], "chg": a["chg"], "lifts": lifts})

    print("  股票数/日: %d ~ %d; 解析失败提醒 %d 条" % (
        min(day_stock_counts or [0]), max(day_stock_counts or [0]), n_bad_alerts))
    for line in check_lines:
        print(line)
    print()

    results = {"koujing": KOUJING, "days": days, "trackA": {}, "trackB": {}, "leadlag": {}, "sweep": {}}

    # ---------------- Track A 主表
    print("二、Track A 事件网格 (lift=方向×(事件前向收益−同股同日安慰剂均值); 判决闸门 N≥%d 且 天≥%d)" % (MIN_N, MIN_DAYS))
    groups = [
        ("大单合并·净流入阶梯", ["IN_1", "IN_2", "IN_3", "IN_5"]),
        ("大单合并·净流出阶梯", ["OUT_1", "OUT_2", "OUT_3", "OUT_5"]),
        ("生产口径复刻", ["IN3_prod", "OUT1_prod"]),
        ("超大单单独", ["SUP_IN_1", "SUP_IN_2", "SUP_OUT_1", "SUP_OUT_2"]),
        ("同额对照(1×超大门槛额)", ["SUP_IN_1", "PL_IN", "MS_IN", "SUP_OUT_1", "PL_OUT", "MS_OUT"]),
        ("背离形态", ["DIV_SELL", "DIV_BUY"]),
    ]
    for h in ALL_H:
        hname = ("+%dmin" % h) if isinstance(h, int) else ("当日收盘" if h == "eod" else "次日收盘")
        print("  --- horizon %s ---" % hname)
        for gname, fams_ in groups:
            if h not in (30, "eod") and gname in ("同额对照(1×超大门槛额)",):
                continue  # 对照组只打印关键 horizon, 免刷屏
            print("  [%s]" % gname)
            for fam in fams_:
                st = cell_stats(agg.cells[(fam, h)])
                pv = np.mean(agg.prev[fam]) if agg.prev[fam] else float("nan")
                extra = " 已走=%s" % fmt_pct(pv, 2) if h == 30 else ""
                print_cell_row(fam, FAM_DESC[fam], st, extra)
                if st:
                    results["trackA"].setdefault(fam, {})[str(h)] = {
                        k: (list(v) if isinstance(v, tuple) else v) for k, v in st.items()}
        print()

    # ---------------- 时段分桶(关键族 30min)
    print("三、时段分桶 (30min lift, 关键族)")
    for fam in ("IN_3", "OUT_1", "SUP_OUT_1", "SUP_IN_1", "IN3_prod", "DIV_SELL"):
        buckets = defaultdict(lambda: {"lift": [], "days": set()})
        for day, tod, lifts, _code in agg.events[fam]:
            if 30 in lifts:
                buckets[tod]["lift"].append(lifts[30])
                buckets[tod]["days"].add(day)
        parts = []
        for tod in ("早盘≤10:30", "上午盘中", "午后"):
            b = buckets[tod]
            if b["lift"]:
                arr = np.asarray(b["lift"])
                parts.append("%s N=%d lift=%s 命中=%.0f%%" % (
                    tod, len(arr), fmt_pct(float(arr.mean())), (arr > 0).mean() * 100))
        print("  %-10s %s" % (fam, " | ".join(parts) if parts else "无"))
    print()

    # ---------------- 提醒量估算
    print("四、提醒量估算 (去重前满足条件的分钟数≈60s冷却下的每日触发条数, 全池%d~%d只)" % (
        min(day_stock_counts or [0]), max(day_stock_counts or [0])))
    for fam in FAM_ORDER:
        v = agg.vol[fam]
        if v:
            per_day = [v[d] for d in days if d in v]
            print("  %-12s 平均 %.0f 条/天 (max %d)" % (fam, np.mean(per_day), max(per_day)))
            results["trackA"].setdefault(fam, {})["vol_per_day"] = float(np.mean(per_day))
    print()

    # ---------------- 领先/滞后
    if not args.no_leadlag:
        print("五、领先/滞后 (分钟净流入 与 分钟收益 的池化互相关; lag>0=资金领先价格)")
        show = [-30, -15, -10, -5, -3, -1, 0, 1, 2, 3, 5, 10, 15, 30]
        for src, label in (("big", "大单合并"), ("sup", "超大单")):
            row = "  %s: " % label + " ".join(
                "r(%+d)=%.4f" % (L, ll.corr(src, L)) for L in show)
            print(row)
            pos = np.nansum([ll.corr(src, L) for L in range(1, 31)])
            neg = np.nansum([ll.corr(src, L) for L in range(-30, 0)])
            print("    Σr(lag 1..30)=%.4f (领先端)  Σr(lag -30..-1)=%.4f (滞后端)" % (pos, neg))
            results["leadlag"][src] = {str(L): ll.corr(src, L) for L in LL_LAGS}
        print()

    # ---------------- Track B
    print("六、Track B 已发提醒事后成绩单 (对照=同股同日随机分钟)")
    for cat in ("large_inflow", "held_outflow", "RISING", "FALLING_retreat", "FALLING_distribution"):
        print("  [%s] 共 %d 条" % (cat, len(bevents[cat])))
        for h in (5, 15, 30, 60, "eod", "next"):
            st = cell_stats(bagg.cells[(cat, h)])
            if st:
                hname = ("+%dmin" % h) if isinstance(h, int) else ("EOD" if h == "eod" else "次日")
                print_cell_row("%s" % hname, "", st)
                results["trackB"].setdefault(cat, {})[str(h)] = {
                    k: (list(v) if isinstance(v, tuple) else v) for k, v in st.items()}
        pv = np.mean(bagg.prev[cat]) if bagg.prev[cat] else float("nan")
        print("    触发时已走(方向签名, 15min): %s" % fmt_pct(pv, 2))
    print()

    # ---------------- 阈值-覆盖率曲线
    print("七、阈值-覆盖率曲线 (调 CAPITAL_TREND_INFLOW_MIN / HELD_MIN_OUTFLOW 的依据)")
    sweeps = {"large_inflow": [3.0, 3.5, 4.0, 5.0, 6.0, 8.0],
              "held_outflow": [1.0, 1.5, 2.0, 3.0],
              "RISING": None, "FALLING_retreat": None, "FALLING_distribution": None}
    for cat, ks in sweeps.items():
        evs = bevents[cat]
        if not evs:
            continue
        ndays = len({e["day"] for e in evs})
        if ks:
            print("  [%s] 按 |窗口净额|/大单门槛 倍数从当前值上扫:" % cat)
            for k in ks:
                sub = [e for e in evs if np.isfinite(e["mult"]) and e["mult"] >= k]
                l30 = [e["lifts"][30] for e in sub if 30 in e["lifts"]]
                leod = [e["lifts"]["eod"] for e in sub if "eod" in e["lifts"]]
                if not l30:
                    print("    ≥%.1f×: 0 条" % k)
                    continue
                a30, aeod = np.asarray(l30), np.asarray(leod) if leod else np.asarray([np.nan])
                print("    ≥%.1f×: %4d条 (%.0f条/天) 30min: lift=%s 命中=%.0f%% | EOD: lift=%s" % (
                    k, len(sub), len(sub) / max(ndays, 1), fmt_pct(float(a30.mean())),
                    (a30 > 0).mean() * 100, fmt_pct(float(np.nanmean(aeod)))))
                results["sweep"].setdefault(cat, {})[str(k)] = {
                    "n": len(sub), "per_day": len(sub) / max(ndays, 1),
                    "lift30": float(a30.mean()), "hit30": float((a30 > 0).mean()),
                    "lift_eod": float(np.nanmean(aeod))}
        else:
            print("  [%s] 按力度 strength_mult 分桶:" % cat)
            for lo, hi in ((0, 1), (1, 2), (2, 3), (3, 99)):
                sub = [e for e in evs if lo <= e["smult"] < hi]
                l30 = [e["lifts"][30] for e in sub if 30 in e["lifts"]]
                if not l30:
                    continue
                a30 = np.asarray(l30)
                print("    力度[%g,%g): %4d条 30min: lift=%s 命中=%.0f%%" % (
                    lo, hi, len(sub), fmt_pct(float(a30.mean())), (a30 > 0).mean() * 100))
    # large_inflow 按触发时日内涨跌幅分桶
    evs = bevents["large_inflow"]
    if evs:
        print("  [large_inflow] 按触发时日内涨跌幅分桶 (30min lift):")
        for name, cond in (("跌(<0%)", lambda c: c < 0), ("平涨(0~3%)", lambda c: 0 <= c < 3),
                           ("大涨(≥3%)", lambda c: c >= 3)):
            sub = [e for e in evs if cond(e["chg"])]
            l30 = [e["lifts"][30] for e in sub if 30 in e["lifts"]]
            if l30:
                a30 = np.asarray(l30)
                print("    %-10s %4d条 lift=%s 命中=%.0f%%" % (
                    name, len(sub), fmt_pct(float(a30.mean())), (a30 > 0).mean() * 100))
    print()

    # ---------------- 稳健性: 集中度 + 逐日一致性
    print("八、稳健性检查 (关键族: 事件是否集中在个别股票/个别日)")
    for fam in ("DIV_SELL", "DIV_BUY", "IN3_prod", "OUT_1", "SUP_OUT_1", "SUP_IN_1"):
        evs = agg.events[fam]
        if not evs:
            continue
        by_code = defaultdict(list)
        by_day = defaultdict(list)
        for day, _tod, lifts, code in evs:
            if "eod" in lifts:
                by_code[code].append(lifts["eod"])
                by_day[day].append(lifts["eod"])
        total = sum(len(v) for v in by_code.values())
        if not total:
            continue
        top = sorted(by_code.items(), key=lambda kv: -len(kv[1]))[:6]
        top_share = sum(len(v) for _, v in top) / total
        print("  [%s] N(eod)=%d 股票数=%d; top6 占比=%.0f%%: %s" % (
            fam, total, len(by_code), top_share * 100,
            " ".join("%s×%d(%s)" % (c, len(v), fmt_pct(float(np.mean(v)), 2)) for c, v in top)))
        pos_days = sum(1 for v in by_day.values() if np.mean(v) > 0)
        print("      逐日EOD lift为正的天数: %d/%d; 去掉事件数最多的1只后 lift=%s" % (
            pos_days, len(by_day),
            fmt_pct(float(np.mean([x for c, v in by_code.items() if c != top[0][0] for x in v])))))
    print()
    print("跑完 %.1fs" % (time.time() - t0))

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=1, default=str)
        print("JSON → %s" % args.json)


if __name__ == "__main__":
    main()
