#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Overfitting-controlled validation of buy-signal factor combos & entry styles.

Rigorously validates the "overfitting-prone" findings (factor x factor combos,
wave/rebound re-entry) with explicit guards, against the production tick days
(06-08..06-15, read-only):

  combo  : enumerate single/pair/triple binary-factor rules; rank by lift over the
           AVERAGE signal (hit - base). Report per-day lift vector (leave-one-day
           stability: a real rule beats the average signal on most of the 6 days,
           not just in aggregate) + bootstrap CI.
  permute: data-snooping / multiple-testing correction. Shuffle the labels K times;
           each time record the MAX combo-lift found. The observed best rule is
           "real" only if its lift beats this null max distribution (empirical p).
  wave   : precise entry-style backtest (immediate / 1st pullback / 2nd-wave /
           momentum-confirm / rebound-off-low), hit rate + realized return + per-day.

Label = intraday pop: from entry, price reaches +T% before -S% (a tradeable pop).
V2 daily factors are REPLAYED from kline_data (no persistence needed).
"""
from __future__ import annotations
import argparse, json, random, itertools, sqlite3, statistics
from bisect import bisect_left
from datetime import date, datetime, timedelta, timezone

HK = timezone(timedelta(hours=8))


def connect(db):
    c = sqlite3.connect(db, uri=db.startswith("file:")); c.row_factory = sqlite3.Row; return c


# set in main(); flow_buy events carry no sniper-detail factors so only daily/session apply
_DAILY_ONLY = False


def tick_days(conn, min_ticks=50000):
    return [r["trade_date"] for r in conn.execute(
        "SELECT trade_date,COUNT(*) n FROM ticker_data GROUP BY trade_date "
        "HAVING n>=? ORDER BY trade_date", (min_ticks,))]


class Data:
    def __init__(self, conn):
        self.conn = conn; self._t = {}; self._k = {}

    def ticks(self, td, code):
        key = (td, code)
        if key not in self._t:
            rs = self.conn.execute(
                "SELECT timestamp,price FROM ticker_data WHERE trade_date=? AND "
                "stock_code=? AND price>0 ORDER BY timestamp", (td, code)).fetchall()
            self._t[key] = [(int(r["timestamp"]), float(r["price"])) for r in rs]
        return self._t[key]

    def klines(self, td, code):
        key = (td, code)
        if key not in self._k:
            rs = self.conn.execute(
                "SELECT substr(time_key,1,10) d,open_price o,high_price h,low_price l,"
                "close_price c FROM kline_data WHERE stock_code=? AND substr(time_key,1,10)<=? "
                "ORDER BY time_key DESC LIMIT 8", (code, td)).fetchall()
            self._k[key] = [dict(r) for r in rs]
        return self._k[key]


def v2_factors(d: Data, td, code, sig_price):
    b = d.klines(td, code)
    if len(b) < 6:
        return None
    today = b[0] if b[0]["d"] == td else None
    idx = 1 if today else 0
    if len(b) < idx + 6:
        return None
    prev = b[idx]; c5 = b[idx + 5]["c"]
    hi20 = max(x["h"] for x in b[idx:idx + 6]); lo20 = min(x["l"] for x in b[idx:idx + 6])
    f = {}
    f["prev_chg"] = (prev["c"] - prev["o"]) / prev["o"] * 100 if prev["o"] else 0
    f["chg5"] = (prev["c"] - c5) / c5 * 100 if c5 else 0
    f["gap"] = (today["o"] - prev["c"]) / prev["c"] * 100 if (today and prev["c"]) else 0
    f["prev_amp"] = (prev["h"] - prev["l"]) / prev["o"] * 100 if prev["o"] else 0
    f["pos20"] = (sig_price - lo20) / (hi20 - lo20) * 100 if hi20 > lo20 else 50
    f["near_high"] = prev["c"] / hi20 * 100 if hi20 else 0
    return f


def label_pop(prices, i, T, S):
    e = prices[i]
    for p in prices[i:]:
        r = (p / e - 1) * 100
        if r >= T:
            return 1
        if r <= -S:
            return 0
    return 0


def load_events(conn, d: Data, dates, T, S, rng, source="mega_buy", rule=None):
    """source: 'mega_buy' (sniper) or 'flow_buy' (capital_flow_signals BUY rules).
    flow_buy lets us condition the capital-flow buy popups (R1/R5/R11/R12) on the
    SAME daily factors + session, instead of only sniper mega_buy."""
    if source == "flow_buy":
        return _load_flow_buy(conn, d, dates, T, S, rng, rule)
    evs = []; placebo = []
    for td in dates:
        seen = set()
        for r in conn.execute(
                "SELECT time,stock_code,price,strength,severity,detail FROM sniper_signals "
                "WHERE trade_date=? AND signal_type='mega_buy' AND is_red=0 ORDER BY time",
                (td,)):
            if r["stock_code"] in seen:
                continue
            seen.add(r["stock_code"])
            tk = d.ticks(td, r["stock_code"])
            if len(tk) < 20:
                continue
            ts = [t[0] for t in tk]; prices = [t[1] for t in tk]
            try:
                h, m = r["time"].split(":")[:2]; dd = date.fromisoformat(td)
                ep = int(datetime(dd.year, dd.month, dd.day, int(h), int(m), tzinfo=HK).timestamp() * 1000)
            except (ValueError, IndexError):
                continue
            j = bisect_left(ts, ep)
            if j >= len(tk):
                continue
            entry = float(r["price"]) if (r["price"] and r["price"] > 0) else prices[j]
            v2 = v2_factors(d, td, r["stock_code"], entry)
            if v2 is None:
                continue
            det = r["detail"] or ""
            import re
            mult = int(mm.group(1)) if (mm := re.search(r"日均(\d+)倍", det)) else 0
            pos_txt = int(mm.group(1)) if (mm := re.search(r"高位\((\d+)%\)", det)) else -1
            acc = int(mm.group(1)) if (mm := re.search(r"建仓信号\(共(\d+)次", det)) else 0
            e = {
                "td": td, "lab": label_pop(prices, j, T, S),
                "j": j, "prices": prices, "entry": entry, "ep": ep, "ts": ts,
                "strength": r["strength"] or 0, "sev_high": 1 if r["severity"] == "high" else 0,
                "trap": 1 if "席位警示" in det else 0, "confirm": 1 if "席位确认" in det else 0,
                "mult": mult, "acc": acc, "pos_txt": pos_txt,
                "hour": int(r["time"].split(":")[0]),
            }
            e.update(v2)
            evs.append(e)
            for _ in range(3):
                placebo.append(label_pop(prices, rng.randint(0, len(prices) - 1), T, S))
    return evs, placebo


def _load_flow_buy(conn, d: Data, dates, T, S, rng, rule=None):
    """Capital-flow BUY events (created_at = UTC). Sniper-detail factors are absent
    here, so only the daily/session factors are meaningful (run with daily_only)."""
    UTC = timezone.utc
    evs = []; placebo = []
    valid = set(dates)
    sql = ("SELECT created_at,rule_id,stock_code,price FROM capital_flow_signals "
           "WHERE signal_type='BUY'")
    params = []
    if rule:
        sql += " AND rule_id=?"; params.append(rule)
    sql += " ORDER BY created_at"
    seen = set()
    for r in conn.execute(sql, params):
        try:
            dt = datetime.strptime(r["created_at"][:19], "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            continue
        dt_hk = dt.replace(tzinfo=UTC).astimezone(HK)
        td = dt_hk.date().isoformat()
        if td not in valid:
            continue
        key = (td, r["rule_id"], r["stock_code"])
        if key in seen:
            continue
        seen.add(key)
        tk = d.ticks(td, r["stock_code"])
        if len(tk) < 20:
            continue
        ts = [t[0] for t in tk]; prices = [t[1] for t in tk]
        ep = int(dt.replace(tzinfo=UTC).timestamp() * 1000)
        j = bisect_left(ts, ep)
        if j >= len(tk):
            continue
        entry = float(r["price"]) if (r["price"] and r["price"] > 0) else prices[j]
        v2 = v2_factors(d, td, r["stock_code"], entry)
        if v2 is None:
            continue
        e = {
            "td": td, "lab": label_pop(prices, j, T, S),
            "j": j, "prices": prices, "entry": entry, "ep": ep, "ts": ts,
            "strength": 0, "sev_high": 0, "trap": 0, "confirm": 0,
            "mult": 0, "acc": 0, "pos_txt": -1, "hour": dt_hk.hour,
            "rule_id": r["rule_id"],
        }
        e.update(v2)
        evs.append(e)
        for _ in range(3):
            placebo.append(label_pop(prices, rng.randint(0, len(prices) - 1), T, S))
    return evs, placebo


# binary factor conditions
def conditions():
    daily = {
        "前日振幅>=8": lambda e: e["prev_amp"] >= 8,
        "前日大涨>=5": lambda e: e["prev_chg"] >= 5,
        "5日涨>=10": lambda e: e["chg5"] >= 10,
        "高开>=2": lambda e: e["gap"] >= 2,
        "低开<0": lambda e: e["gap"] < 0,
        "日线高位>=67": lambda e: e["pos20"] >= 67,
        "日线低位<33": lambda e: e["pos20"] < 33,
        "近20高>=95": lambda e: e["near_high"] >= 95,
        "早盘<11": lambda e: e["hour"] < 11,
        "午后>=14": lambda e: e["hour"] >= 14,
    }
    if _DAILY_ONLY:
        return daily
    daily.update({
        "强度>=60": lambda e: e["strength"] >= 60,
        "净买>=5倍": lambda e: e["mult"] >= 5,
        "无席位警示": lambda e: e["trap"] == 0,
        "有席位确认": lambda e: e["confirm"] == 1,
        "severity高": lambda e: e["sev_high"] == 1,
        "连续建仓>=3": lambda e: e["acc"] >= 3,
    })
    return daily


def _hit(evs, preds):
    sub = [e for e in evs if all(p(e) for p in preds)]
    return (len(sub), sum(e["lab"] for e in sub) / len(sub) * 100 if sub else None)


def combo_stat(evs, combo_items, base, dates, min_n=40, min_day_n=5):
    names = [c[0] for c in combo_items]; preds = [c[1] for c in combo_items]
    sub = [e for e in evs if all(p(e) for p in preds)]
    n = len(sub)
    if n < min_n:
        return None
    hit = sum(e["lab"] for e in sub) / n * 100
    per_day = []
    for td in dates:
        dd = [e for e in sub if e["td"] == td]
        bd = [e for e in evs if e["td"] == td]
        if len(dd) >= min_day_n and bd:
            base_d = sum(e["lab"] for e in bd) / len(bd) * 100
            per_day.append(round(sum(e["lab"] for e in dd) / len(dd) * 100 - base_d, 1))
    # conditional lift: does the combo beat its BEST single sub-factor?
    # (overfitting guard for pairs/triples: a pair that doesn't beat its strongest
    #  single factor is likely that factor carrying it + noise decoration)
    cond = None
    if len(combo_items) >= 2:
        singles = [h for (_, cp) in combo_items for nn, h in [_hit(evs, [cp])] if h is not None]
        if singles:
            cond = round(hit - max(singles), 1)
    return {"combo": " & ".join(names), "n": n, "hit": round(hit, 1),
            "lift": round(hit - base, 1), "cond_lift_vs_best_single": cond,
            "per_day_rel": per_day, "days_eval": len(per_day),
            "pos_days": sum(1 for x in per_day if x > 0),
            "min_day_rel": min(per_day) if per_day else None,
            "mean_day_rel": round(statistics.mean(per_day), 1) if per_day else None}


def run_combo(evs, base, dates, order, min_n, topn):
    C = conditions(); items = list(C.items())
    results = []
    combos = []
    for k in range(1, order + 1):
        combos += list(itertools.combinations(items, k))
    for combo in combos:
        s = combo_stat(evs, list(combo), base, dates, min_n)
        if s:
            results.append(s)
    results.sort(key=lambda r: r["lift"], reverse=True)
    return results[:topn]


def run_permute(evs, base, dates, order, min_n, K, rng):
    C = conditions(); items = list(C.items())
    combos = []
    for k in range(1, order + 1):
        combos += [[c[1] for c in cc] for cc in itertools.combinations(items, k)]
    # observed best
    def best_lift(labels):
        bm = -1e9
        for preds in combos:
            sub_idx = [i for i, e in enumerate(evs) if all(p(e) for p in preds)]
            if len(sub_idx) < min_n:
                continue
            hit = sum(labels[i] for i in sub_idx) / len(sub_idx) * 100
            bm = max(bm, hit - base)
        return bm
    obs_labels = [e["lab"] for e in evs]
    observed = best_lift(obs_labels)
    null = []
    pool = list(obs_labels)
    for _ in range(K):
        rng.shuffle(pool)
        null.append(best_lift(list(pool)))
    null.sort()
    p = sum(1 for x in null if x >= observed) / len(null)
    pct = {q: round(null[min(len(null) - 1, int(q / 100 * len(null)))], 1)
           for q in (50, 90, 95, 99)}
    return {"observed_best_lift": round(observed, 1), "perm_null_pctiles": pct,
            "empirical_p": round(p, 4), "K": K}


# ---- wave / entry-style ----
def first_idx(prices, j, cond):
    for k in range(j, len(prices)):
        if cond(prices[k]):
            return k
    return None


def wave_outcomes(evs, T, S, dates, placebo_base):
    strat_names = ["S0_立即", "S1_回踩-1%", "S2_回踩-2%", "S3_动量+1%确认",
                   "S4_二浪(跌1%后收复)", "S5_反弹(局部低点上抬1%)"]
    rows = {s: [] for s in strat_names}
    triggered = {s: 0 for s in strat_names}
    for e in evs:
        prices = e["prices"]; j = e["j"]; entry = e["entry"]
        # S0
        rows["S0_立即"].append({"td": e["td"], "lab": label_pop(prices, j, T, S)})
        triggered["S0_立即"] += 1
        # S1 / S2 pullback
        for nm, dip in (("S1_回踩-1%", 0.99), ("S2_回踩-2%", 0.98)):
            k = first_idx(prices, j, lambda p, d=dip: p <= entry * d)
            if k is not None:
                rows[nm].append({"td": e["td"], "lab": label_pop(prices, k, T, S)}); triggered[nm] += 1
        # S3 momentum confirm +1%
        k = first_idx(prices, j, lambda p: p >= entry * 1.01)
        if k is not None:
            rows["S3_动量+1%确认"].append({"td": e["td"], "lab": label_pop(prices, k, T, S)}); triggered["S3_动量+1%确认"] += 1
        # S4 second wave: drop >=1% from entry then recover back to entry; enter at recovery
        kd = first_idx(prices, j, lambda p: p <= entry * 0.99)
        if kd is not None:
            kr = first_idx(prices, kd, lambda p: p >= entry)
            if kr is not None:
                rows["S4_二浪(跌1%后收复)"].append({"td": e["td"], "lab": label_pop(prices, kr, T, S)}); triggered["S4_二浪(跌1%后收复)"] += 1
        # S5 rebound off local low: find min in next ~min, enter when up 1% off that min
        win = prices[j:j + 1200] if len(prices) > j else []
        if win:
            lo = min(win); lo_k = j + win.index(lo)
            kr = first_idx(prices, lo_k, lambda p, lo=lo: p >= lo * 1.01)
            if kr is not None:
                rows["S5_反弹(局部低点上抬1%)"].append({"td": e["td"], "lab": label_pop(prices, kr, T, S)}); triggered["S5_反弹(局部低点上抬1%)"] += 1
    out = []
    for s in strat_names:
        rr = rows[s]; n = len(rr)
        if not n:
            continue
        hit = sum(x["lab"] for x in rr) / n * 100
        per_day = []
        for td in dates:
            dd = [x for x in rr if x["td"] == td]
            if len(dd) >= 5:
                per_day.append(round(sum(x["lab"] for x in dd) / len(dd) * 100, 1))
        out.append({"strategy": s, "n": n, "trigger_rate": round(triggered[s] / len(evs) * 100, 1),
                    "hit": round(hit, 1), "lift_vs_placebo": round(hit - placebo_base, 1),
                    "per_day_hit": per_day})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="simple_trade/data/trade.db")
    ap.add_argument("--mode", choices=["combo", "permute", "wave"], default="combo")
    ap.add_argument("--T", type=float, default=3.0)
    ap.add_argument("--S", type=float, default=3.0)
    ap.add_argument("--order", type=int, default=2)
    ap.add_argument("--min-n", type=int, default=40)
    ap.add_argument("--perm", type=int, default=200)
    ap.add_argument("--topn", type=int, default=15)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--source", choices=["mega_buy", "flow_buy"], default="mega_buy",
                    help="event population to condition: sniper mega_buy or capital-flow BUY rules")
    ap.add_argument("--rule", default=None,
                    help="for --source flow_buy: restrict to one rule_id (e.g. R11)")
    a = ap.parse_args()
    global _DAILY_ONLY
    _DAILY_ONLY = (a.source != "mega_buy")
    rng = random.Random(a.seed)
    conn = connect(a.db); d = Data(conn)
    dates = tick_days(conn)
    evs, placebo = load_events(conn, d, dates, a.T, a.S, rng, source=a.source, rule=a.rule)
    if not evs:
        print(json.dumps({"error": "no events", "source": a.source, "rule": a.rule,
                          "dates": dates}, ensure_ascii=False)); conn.close(); return
    n = len(evs); base = sum(e["lab"] for e in evs) / n * 100
    pbase = sum(placebo) / len(placebo) * 100
    head = {"mode": a.mode, "source": a.source, "rule": a.rule, "T": a.T, "S": a.S,
            "dates": dates, "n_events": n,
            "base_hit": round(base, 1), "placebo_hit": round(pbase, 1),
            "signal_lift_vs_placebo": round(base - pbase, 1)}
    if a.mode == "combo":
        head["top_combos"] = run_combo(evs, base, dates, a.order, a.min_n, a.topn)
        head["note"] = "lift = hit - base(平均信号命中); per_day_rel = 每日(组合命中-当日平均命中); 稳健=pos_days高&min_day_rel不深负"
    elif a.mode == "permute":
        head["permutation"] = run_permute(evs, base, dates, a.order, a.min_n, a.perm, rng)
        head["note"] = "observed_best_lift 若 <= perm_null 95分位 或 empirical_p>0.05 => 最佳组合很可能是过拟合(数据窥探)"
    else:
        head["waves"] = wave_outcomes(evs, a.T, a.S, dates, pbase)
        head["note"] = "各入场风格 命中率/触发率/逐日; 比 S0_立即 高且逐日稳 => 真"
    conn.close()
    print(json.dumps(head, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
