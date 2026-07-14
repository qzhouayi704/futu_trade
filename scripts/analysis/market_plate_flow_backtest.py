#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三级市场/板块资金流确认策略回放（热门 AI/半导体股票）。"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Dict, Iterable, Optional

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import big_order_flow_eval as flow  # noqa: E402


WINDOW = 10
ROUND_TRIP_COST = 0.0025
NORMAL_BREADTH = 0.55
WEAK_BREADTH = 0.40
MIN_PLATE_SIZE = 5
MODE_RULES = {
    "NORMAL": {"amount": 3.0, "ratio": 3.0, "mult": 1.0, "top": 0.20,
               "plate": 0.0, "relative": -float("inf"), "confirmations": 2, "timeout": 15},
    "WEAK": {"amount": 4.0, "ratio": 4.0, "mult": 1.5, "top": 0.20,
             "plate": 0.60, "relative": 1.5, "confirmations": 2, "timeout": 15},
    "EXTREME": {"amount": 5.0, "ratio": 5.0, "mult": 2.0, "top": 0.10,
                "plate": 0.70, "relative": 2.5, "confirmations": 3, "timeout": 60},
}


def pct(value: float) -> str:
    return f"{value * 100:+.2f}%" if np.isfinite(value) else "--"


def rolling_sum(values: np.ndarray, window: int = WINDOW) -> np.ndarray:
    result = np.zeros(len(values), dtype=float)
    for start, end in ((0, flow.LUNCH_OPEN), (flow.LUNCH_OPEN, len(values))):
        segment = np.asarray(values[start:end], dtype=float)
        cumulative = np.cumsum(segment)
        rolled = cumulative.copy()
        if len(segment) > window:
            rolled[window:] = cumulative[window:] - cumulative[:-window]
        result[start:end] = rolled
    return result


def window_arrays(record: dict) -> dict:
    buy = rolling_sum(record["bb"])
    sell = rolling_sum(record["bs"])
    return {"buy": buy, "sell": sell, "net": buy - sell}


def causal_scale(history: deque, threshold: float) -> Optional[float]:
    if len(history) < 3:
        return None
    values = np.concatenate(list(history))
    values = values[np.isfinite(values)]
    return max(float(threshold), float(np.median(values))) if len(values) else None


def pick_confirmations(mask: np.ndarray, min_gap: int = 5) -> list:
    result = []
    last = -10**9
    for index in np.where(mask)[0]:
        index = int(index)
        if index - last >= min_gap:
            result.append(index)
            last = index
    return result


def load_hot_universe(
    conn: sqlite3.Connection, start_day: str, end_day: str, limit: int,
) -> list:
    rows = conn.execute(
        "WITH target AS ("
        " SELECT DISTINCT s.code,s.name FROM stocks s "
        " JOIN stock_plates sp ON sp.stock_id=s.id JOIN plates p ON p.id=sp.plate_id "
        " WHERE p.market='HK' AND (p.category IN ('AI','芯片') OR "
        " p.plate_name IN ('人工智能','半导体','半导体设备与材料','AI次新股'))"
        "), liquidity AS ("
        " SELECT stock_code,COUNT(DISTINCT trade_date) data_days,"
        " SUM(COALESCE(buy_amt,0)+COALESCE(sell_amt,0)) amount "
        " FROM ticker_minute WHERE trade_date BETWEEN ? AND ? GROUP BY stock_code"
        ") SELECT t.code,t.name,l.data_days,l.amount FROM target t "
        " JOIN liquidity l ON l.stock_code=t.code ORDER BY l.amount DESC LIMIT ?",
        (start_day, end_day, limit),
    ).fetchall()
    return [
        {"code": str(code), "name": str(name or ""),
         "data_days": int(data_days or 0), "amount": float(amount or 0.0)}
        for code, name, data_days, amount in rows
    ]


def load_closes(conn: sqlite3.Connection) -> Dict[str, list]:
    latest = {}
    for code, day, close, row_id in conn.execute(
        "SELECT stock_code,substr(time_key,1,10),close_price,id FROM kline_data "
        "WHERE time_key>='2025-12-01' ORDER BY id"
    ):
        if code and day and close and float(close) > 0:
            latest[(str(code), str(day))] = (int(row_id), float(close))
    result = defaultdict(list)
    for (code, day), (_row_id, close) in latest.items():
        result[code].append((day, close))
    for rows in result.values():
        rows.sort()
    return dict(result)


def primary_plates(conn: sqlite3.Connection) -> Dict[str, str]:
    """复用线上 GROUP_CONCAT 后取首板块的口径。"""
    rows = conn.execute(
        "SELECT s.code, GROUP_CONCAT(DISTINCT p.plate_name) "
        "FROM stocks s LEFT JOIN stock_plates sp ON sp.stock_id=s.id "
        "LEFT JOIN plates p ON p.id=sp.plate_id GROUP BY s.id, s.code"
    )
    return {
        str(code): str(names).split(",", 1)[0].strip()
        for code, names in rows if code and names
    }


def previous_closes(closes: Dict[str, list]) -> Dict[tuple, float]:
    return {
        (code, rows[index][0]): rows[index - 1][1]
        for code, rows in closes.items()
        for index in range(1, len(rows))
    }


def latest_close_before(closes: Dict[str, list], code: str, day: str) -> Optional[float]:
    values = [close for close_day, close in closes.get(code, []) if close_day < day]
    return float(values[-1]) if values else None


def make_event(code: str, day: str, index: int, base: dict) -> dict:
    prices = base["p"]
    entry = float(prices[index])

    def forward(horizon: int) -> float:
        target = index + horizon
        return float(prices[target] / entry - 1.0) if target < len(prices) else float("nan")

    future60 = prices[index + 1:min(len(prices), index + 61)]
    future = prices[index + 1:]
    return {
        "code": code, "day": day, "index": index, "price": entry,
        "r15": forward(15), "r30": forward(30), "r60": forward(60),
        "mfe60": float(np.nanmax(future60) / entry - 1.0) if len(future60) else 0.0,
        "mae60": float(np.nanmin(future60) / entry - 1.0) if len(future60) else 0.0,
        "mfe_eod": float(np.nanmax(future) / entry - 1.0) if len(future) else 0.0,
        "eod": float(prices[-1] / entry - 1.0),
    }


def mode_for_breadth(value: float) -> str:
    if value >= NORMAL_BREADTH:
        return "NORMAL"
    if value >= WEAK_BREADTH:
        return "WEAK"
    return "EXTREME"


def build_contexts(
    records: Dict[str, dict],
    derived: Dict[str, dict],
    prev_close: Dict[str, Optional[float]],
    plates: Dict[str, str],
    candidates: Iterable[str],
) -> Dict[str, list]:
    contexts = {code: [None] * flow.NG for code in candidates}
    turnover = {
        code: np.cumsum(record["tmb"] + record["tms"])
        for code, record in records.items()
    }
    for index in range(flow.NG):
        rows = []
        for code, base in derived.items():
            previous = prev_close.get(code)
            price = base["p"][index] if base is not None else np.nan
            if (not code.startswith("HK.") or previous is None or previous <= 0
                    or not np.isfinite(price)):
                continue
            rows.append({
                "code": code,
                "change": (float(price) / previous - 1.0) * 100.0,
                "turnover": float(turnover[code][index]),
                "plate": plates.get(code, ""),
            })
        if len(rows) < 20:
            continue
        breadth = sum(row["change"] > 0 for row in rows) / len(rows)
        mode = mode_for_breadth(breadth)
        rule = MODE_RULES[mode]
        ranked = sorted((row for row in rows if row["turnover"] > 0),
                        key=lambda row: row["turnover"], reverse=True)
        hot_count = max(1, int(np.ceil(len(ranked) * rule["top"]))) if ranked else 0
        hot = {row["code"] for row in ranked[:hot_count]}
        rank = {
            row["code"]: 1.0 - position / len(ranked)
            for position, row in enumerate(ranked)
        } if ranked else {}
        by_plate = defaultdict(list)
        for row in rows:
            if row["plate"]:
                by_plate[row["plate"]].append(row["change"])

        for row in rows:
            code = row["code"]
            if code not in contexts:
                continue
            members = by_plate.get(row["plate"], [])
            plate_breadth = (sum(value > 0 for value in members) / len(members)
                             if members else 0.0)
            plate_median = float(np.median(members)) if members else 0.0
            relative = row["change"] - plate_median
            plate_ok = (
                rule["plate"] <= 0
                or (len(members) >= MIN_PLATE_SIZE
                    and plate_breadth >= rule["plate"]
                    and relative >= rule["relative"])
            )
            contexts[code][index] = {
                "eligible": code in hot and plate_ok,
                "mode": mode,
                "breadth": breadth,
                "universe": len(rows),
                "rank": rank.get(code, 0.0),
                "plate": row["plate"],
                "plate_breadth": plate_breadth,
                "plate_size": len(members),
                "relative": relative,
            }
    return contexts


def strong_mask(
    record: dict,
    item: dict,
    contexts: list,
    threshold: float,
    scale: float,
) -> np.ndarray:
    result = np.zeros(flow.NG, dtype=bool)
    for index, context in enumerate(contexts):
        if not context or not context["eligible"] or record["cb"][index] <= 0:
            continue
        rule = MODE_RULES[context["mode"]]
        buy = float(item["buy"][index])
        sell = float(item["sell"][index])
        net = float(item["net"][index])
        result[index] = (
            net >= rule["amount"] * threshold
            and net >= rule["mult"] * scale
            and (sell <= 0 < buy or buy >= rule["ratio"] * sell)
        )
    return result


def watch_exit(prices: np.ndarray, start: int, end: int) -> Optional[int]:
    entry = float(prices[start])
    peak = entry
    for index in range(start + 1, min(end + 1, len(prices))):
        price = float(prices[index])
        if not np.isfinite(price):
            continue
        peak = max(peak, price)
        if peak >= entry * 1.015 and price <= peak * 0.99:
            return index
    return None


def confirmed_exit(prices: np.ndarray, start: int, end: Optional[int] = None) -> int:
    peak = float(prices[start])
    last = len(prices) - 1 if end is None else min(int(end), len(prices) - 1)
    for index in range(start + 1, last + 1):
        price = float(prices[index])
        if not np.isfinite(price):
            continue
        peak = max(peak, price)
        if price <= peak * 0.985:
            return index
    return last


def sustained_target(prices: np.ndarray, start: int, target: float) -> bool:
    """至少连续两个分钟价达到目标，过滤单笔碎股造成的瞬时假高。"""
    level = float(prices[start]) * (1.0 + target)
    future = prices[start + 1:]
    valid = np.isfinite(future) & (future >= level)
    return bool(np.any(valid[:-1] & valid[1:])) if len(valid) >= 2 else False


def simulate_sequence(
    prices: np.ndarray,
    item: dict,
    confirmations: list,
    contexts: list,
    threshold: float,
    end_index: Optional[int] = None,
) -> dict:
    first = int(confirmations[0])
    first_context = contexts[first]
    rule = MODE_RULES[first_context["mode"]]
    observed_end = len(prices) - 1 if end_index is None else int(end_index)
    full_deadline = min(first + int(rule["timeout"]), len(prices) - 1)
    deadline = min(full_deadline, observed_end)
    required = int(rule["confirmations"])
    later = [int(index) for index in confirmations[1:] if index <= deadline]
    result = {
        "status": "EXPIRED", "first": first, "confirm": None,
        "exit": deadline, "mode": first_context["mode"], "context": first_context,
        "sequence": 1 + len(later),
    }
    if len(later) < required - 1:
        trial_exit = watch_exit(prices, first, deadline)
        if trial_exit is not None:
            result.update(status="WATCH_TRAIL_EXIT", exit=trial_exit)
        elif observed_end < full_deadline:
            result["status"] = "PENDING"
        return result

    confirm = later[required - 2]
    outflow = np.where(item["net"][first + 1:confirm + 1] <= -threshold)[0]
    if len(outflow):
        result.update(status="INVALIDATED", exit=first + 1 + int(outflow[0]))
        return result
    trial_exit = watch_exit(prices, first, confirm)
    if trial_exit is not None:
        result.update(status="WATCH_TRAIL_EXIT", exit=trial_exit)
        return result
    peak = float(np.nanmax(prices[first:confirm + 1]))
    confirm_price = float(prices[confirm])
    peak_pullback = (peak - confirm_price) / peak if peak > 0 else 0.0
    if confirm_price < float(prices[first]) or peak_pullback > 0.01:
        result.update(status="REJECTED", exit=confirm)
        return result
    result.update(status="CONFIRMED", confirm=confirm,
                  exit=confirmed_exit(prices, confirm, observed_end))
    return result


def today_records(conn: sqlite3.Connection, day: str) -> Dict[str, dict]:
    thresholds = dict(conn.execute(
        "SELECT c.stock_code, c.big_order_threshold FROM capital_flow_minute c "
        "JOIN (SELECT stock_code, MAX(trade_date||' '||minute) key_ "
        "      FROM capital_flow_minute WHERE trade_date<? GROUP BY stock_code) x "
        "ON x.stock_code=c.stock_code AND x.key_=c.trade_date||' '||c.minute",
        (day,),
    ))
    records = {}

    def get_record(code: str) -> dict:
        record = records.get(code)
        if record is None:
            record = {key: np.zeros(flow.NG) for key in flow._FIELDS}
            record["price"] = np.full(flow.NG, np.nan)
            record["thr"] = float(thresholds.get(code) or 0.0)
            records[code] = record
        return record

    rows = conn.execute(
        "SELECT stock_code, trade_time, price, volume, turnover, direction "
        "FROM ticker_data WHERE trade_date=? ORDER BY id", (day,),
    )
    for code, trade_time, price, volume, turnover, direction in rows:
        minute = str(trade_time or "")[11:16]
        if not minute:
            continue
        index = flow.IDX[flow.clip_minute(minute)]
        record = get_record(str(code))
        price = float(price or 0.0)
        amount = float(turnover or 0.0) or price * float(volume or 0.0)
        if price > 0:
            record["price"][index] = price
        side = str(direction or "").upper()
        if "BUY" in side:
            record["tmb"][index] += amount
        elif "SELL" in side:
            record["tms"][index] += amount
        threshold = float(record.get("thr") or 0.0)
        if threshold <= 0 or amount < threshold:
            continue
        if "BUY" in side:
            record["bb"][index] += amount
            record["cb"][index] += 1
        elif "SELL" in side:
            record["bs"][index] += amount
            record["cs"][index] += 1
    return records


def summarize(rows: list) -> dict:
    if not rows:
        return {"n": 0}
    base = {"n": len(rows)}
    for key in ("r15", "r30", "r60"):
        values = np.asarray([row[key] for row in rows], dtype=float)
        base[f"{key}_mean"] = float(np.nanmean(values))
    base["mfe60_median"] = float(np.median([row["mfe60"] for row in rows]))
    base["target_1_5"] = float(np.mean([row["target_1_5"] for row in rows]))
    base["target_3"] = float(np.mean([row["target_3"] for row in rows]))
    base["target_5"] = float(np.mean([row["target_5"] for row in rows]))
    mae = [row["mae60"] for row in rows if row.get("mae60") is not None]
    base["mae60_median"] = float(np.median(mae)) if mae else float("nan")
    base["trail_mean"] = float(np.mean([row["trail_return"] for row in rows]))
    base["trail_after_cost"] = base["trail_mean"] - ROUND_TRIP_COST
    base["trail_hit"] = float(np.mean([row["trail_return"] > 0 for row in rows]))
    return base


def strategy_summary(rows: list) -> dict:
    values = np.asarray([row["strategy_return"] for row in rows], dtype=float)
    if not len(values):
        return {"n": 0}
    return {
        "n": len(values),
        "mean": float(values.mean()),
        "median": float(np.median(values)),
        "after_cost": float(values.mean() - ROUND_TRIP_COST),
        "hit": float((values > 0).mean()),
    }


def print_summary(label: str, result: dict) -> None:
    if not result.get("n"):
        print(f"  {label:<12} 无样本")
        return
    print(
        f"  {label:<12} N={result['n']:3d} 15m={pct(result['r15_mean'])} "
        f"30m={pct(result['r30_mean'])} 60m={pct(result['r60_mean'])} "
        f"MFE60={pct(result['mfe60_median'])} MAE60={pct(result['mae60_median'])} "
        f"持续达1.5/3/5%={result['target_1_5']*100:.0f}/{result['target_3']*100:.0f}/{result['target_5']*100:.0f}% "
        f"回撤退出={pct(result['trail_mean'])} 成本后={pct(result['trail_after_cost'])}"
    )


def print_strategy(label: str, result: dict) -> None:
    if not result.get("n"):
        print(f"  {label:<12} 无样本")
        return
    print(
        f"  {label:<12} N={result['n']:3d} 毛收益={pct(result['mean'])} "
        f"中位={pct(result['median'])} 成本后={pct(result['after_cost'])} "
        f"胜率={result['hit']*100:.0f}%"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=flow.DEFAULT_DB)
    parser.add_argument("--days", type=int, default=10)
    parser.add_argument("--universe-limit", type=int, default=30)
    parser.add_argument("--today", default="")
    parser.add_argument("--json", default="")
    parser.add_argument("--normal-amount", type=float, default=4.0)
    parser.add_argument("--normal-ratio", type=float, default=4.0)
    parser.add_argument("--normal-mult", type=float, default=1.5)
    parser.add_argument("--normal-plate", type=float, default=0.55)
    parser.add_argument("--normal-relative", type=float, default=0.0)
    parser.add_argument("--weak-plate", type=float, default=0.50)
    parser.add_argument("--weak-relative", type=float, default=2.5)
    args = parser.parse_args()

    MODE_RULES["NORMAL"].update(
        amount=args.normal_amount,
        ratio=args.normal_ratio,
        mult=args.normal_mult,
        plate=args.normal_plate,
        relative=args.normal_relative,
    )
    MODE_RULES["WEAK"].update(
        plate=args.weak_plate,
        relative=args.weak_relative,
    )

    conn = sqlite3.connect(args.db, uri=True)
    conn.execute("PRAGMA query_only=ON")
    all_days, dropped = flow.full_days(conn)
    eval_days = set(all_days[-max(1, args.days):])
    universe = load_hot_universe(
        conn, all_days[0], all_days[-1], max(1, args.universe_limit),
    )
    allowed = {row["code"] for row in universe}
    names = {row["code"]: row["name"] for row in universe}
    closes = load_closes(conn)
    prev_map = previous_closes(closes)
    plates = primary_plates(conn)
    histories = defaultdict(lambda: deque(maxlen=5))
    confirmed_rows = []
    sequences = []
    message_counts = Counter()
    today_diagnostics = []

    def process(day: str, records: Dict[str, dict], evaluate: bool) -> None:
        derived = {
            code: flow.derive(record, code, day, {})
            for code, record in records.items()
        }
        prev = {
            code: (prev_map.get((code, day)) or latest_close_before(closes, code, day))
            for code in records
        }
        contexts = build_contexts(records, derived, prev, plates, allowed)
        for code, record in records.items():
            base = derived.get(code)
            threshold = float(record.get("thr") or 0.0)
            item = window_arrays(record)
            scale = causal_scale(histories[code], threshold) if threshold > 0 else None
            if evaluate and code in allowed and base is not None and scale is not None:
                mask = strong_mask(record, item, contexts.get(code, []), threshold, scale)
                confirmations = pick_confirmations(mask)
                observed = np.where(np.isfinite(record["price"]))[0]
                observed_end = int(observed[-1]) if len(observed) else 0
                if confirmations:
                    result = simulate_sequence(base["p"], item, confirmations,
                                               contexts[code], threshold, observed_end)
                    result.update(code=code, name=names.get(code, ""), day=day,
                                  first_time=flow.GRID[result["first"]])
                    if result.get("confirm") is not None:
                        result["confirm_time"] = flow.GRID[result["confirm"]]
                    sequences.append(result)
                    result["strategy_return"] = float(
                        base["p"][int(result["exit"])] / base["p"][int(result["first"])] - 1.0
                    )
                    if result["mode"] != "EXTREME":
                        message_counts[day] += 1
                    if result["status"] == "CONFIRMED":
                        message_counts[day] += 1
                        index = int(result["confirm"])
                        event = make_event(code, day, index, base)
                        event["mode"] = result["mode"]
                        event["target_1_5"] = sustained_target(base["p"], index, 0.015)
                        event["target_3"] = sustained_target(base["p"], index, 0.03)
                        event["target_5"] = sustained_target(base["p"], index, 0.05)
                        exit_index = int(result["exit"])
                        event["trail_return"] = float(base["p"][exit_index] / base["p"][index] - 1.0)
                        confirmed_rows.append(event)
                        if exit_index < len(base["p"]) - 1:
                            message_counts[day] += 1
                elif day == args.today:
                    eligible = [
                        index for index, context in enumerate(contexts.get(code, []))
                        if context and context["eligible"] and record["cb"][index] > 0
                    ]
                    all_buys = np.where(record["cb"] > 0)[0]
                    pool = eligible or [int(index) for index in all_buys]
                    if pool:
                        best = max(pool, key=lambda index: float(item["net"][index] / threshold))
                        context = contexts[code][best]
                        today_diagnostics.append({
                            "code": code, "name": names.get(code, ""),
                            "time": flow.GRID[best], "net_mult": float(item["net"][best] / threshold),
                            "strength": float(item["net"][best] / scale),
                            "buy_ratio": (float(item["buy"][best] / item["sell"][best])
                                          if item["sell"][best] > 0 else float("inf")),
                            "gate": bool(context and context["eligible"]),
                            "context": context,
                        })
            active = (record["cb"] + record["cs"]) > 0
            sample = np.abs(item["net"][active])
            sample = sample[np.isfinite(sample)]
            if len(sample):
                histories[code].append(sample)

    for day in all_days:
        process(day, flow.load_day(conn, day), day in eval_days)

    print("【三级市场/板块资金流确认回放】")
    print(f"评估日={sorted(eval_days)} 热门AI/半导体池={len(universe)} 剔除={dropped}")
    print(f"首次观察={len(sequences)} 状态={dict(Counter(row['status'] for row in sequences))}")
    print_summary("全部确认", summarize(confirmed_rows))
    for mode in ("NORMAL", "WEAK", "EXTREME"):
        print_summary(mode, summarize([row for row in confirmed_rows if row["mode"] == mode]))
    print("\n[从首次观察试仓到失效/拒绝/回撤退出/确认后退出]")
    historical_sequences = [row for row in sequences if row["day"] in eval_days]
    print_strategy("全部序列", strategy_summary(historical_sequences))
    for mode in ("NORMAL", "WEAK", "EXTREME"):
        print_strategy(mode, strategy_summary([
            row for row in historical_sequences if row["mode"] == mode
        ]))
    daily_values = [message_counts[day] for day in sorted(eval_days)]
    print(
        f"微信消息/日：均值={np.mean(daily_values):.1f} 中位={np.median(daily_values):.1f} "
        f"最大={max(daily_values, default=0)} 明细={dict(sorted(message_counts.items()))}"
    )

    today_output = []
    if args.today:
        before = len(sequences)
        process(args.today, today_records(conn, args.today), True)
        today_output = [row for row in sequences[before:] if row["day"] == args.today]
        print(f"\n【{args.today} 盘中回放】")
        if not today_output:
            print("  暂无通过三级门控的热门股资金流观察")
        for row in today_output:
            context = row["context"]
            print(
                f"  {row['first_time']} {row['code']} {row['name']} {row['mode']} "
                f"市场{context['breadth']:.0%} {context['plate']}板块{context['plate_breadth']:.0%} "
                f"相对{context['relative']:+.1f}点 次数={row['sequence']} 状态={row['status']} "
                f"确认={row.get('confirm_time', '-') }"
            )
        print("  最接近条件的资金流：")
        for row in sorted(today_diagnostics, key=lambda item: item["net_mult"], reverse=True)[:8]:
            context = row["context"] or {}
            print(
                f"    {row['time']} {row['code']} {row['name']} "
                f"净额={row['net_mult']:.1f}门槛 力度={row['strength']:.1f}x "
                f"买卖比={row['buy_ratio']:.1f} 门控={'通过' if row['gate'] else '未过'} "
                f"{context.get('mode', '无')} 市场{context.get('breadth', 0):.0%} "
                f"{context.get('plate', '')}板块{context.get('plate_breadth', 0):.0%} "
                f"相对{context.get('relative', 0):+.1f}点"
            )

    output = {
        "days": sorted(eval_days), "universe": universe,
        "statuses": dict(Counter(row["status"] for row in sequences if row["day"] in eval_days)),
        "summary": summarize(confirmed_rows),
        "strategy": strategy_summary([
            row for row in sequences if row["day"] in eval_days
        ]),
        "daily_messages": dict(sorted(message_counts.items())),
        "today": today_output,
    }
    if args.json:
        Path(args.json).write_text(
            json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8",
        )
        print(f"JSON -> {args.json}")


if __name__ == "__main__":
    main()
