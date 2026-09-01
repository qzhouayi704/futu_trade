#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""资金流事件序列回测：重复流入、流入后流出、流出后再流入。"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import big_order_flow_eval as flow  # noqa: E402
import capital_window_backtest as window_bt  # noqa: E402
import daily_position_flow_backtest as daily  # noqa: E402


WINDOWS = (10, 15)
CONFIRM_GAP = 5
CALIB_DAYS = 5
MIN_CALIB_DAYS = 3
ROUND_TRIP_COST = 0.0025


def pick_confirmations(mask: np.ndarray, min_gap: int = CONFIRM_GAP) -> List[int]:
    """强流入保持期间，每隔 min_gap 分钟最多计一次独立确认。"""
    result: List[int] = []
    last = -10**9
    for index in np.where(mask)[0]:
        index = int(index)
        if index - last >= min_gap:
            result.append(index)
            last = index
    return result


def first_after(mask: np.ndarray, start: int, limit: Optional[int] = None) -> Optional[int]:
    end = len(mask) if limit is None else min(len(mask), start + limit + 1)
    indices = np.where(mask[start + 1:end])[0]
    return int(start + 1 + indices[0]) if len(indices) else None


def first_target(prices: np.ndarray, start: int, target_return: float) -> Optional[int]:
    target = float(prices[start]) * (1.0 + target_return)
    indices = np.where(prices[start + 1:] >= target)[0]
    return int(start + 1 + indices[0]) if len(indices) else None


def trailing_exit(
    prices: np.ndarray,
    start: int,
    activation_return: float,
    pullback: float,
) -> Optional[int]:
    entry = float(prices[start])
    peak = entry
    active = False
    for index in range(start + 1, len(prices)):
        price = float(prices[index])
        peak = max(peak, price)
        if peak >= entry * (1.0 + activation_return):
            active = True
        if active and price <= peak * (1.0 - pullback):
            return index
    return None


def earliest_or_eod(prices: np.ndarray, *indices: Optional[int]) -> int:
    valid = [int(index) for index in indices if index is not None]
    return min(valid) if valid else len(prices) - 1


def oracle_high(prices: np.ndarray, start: int) -> int:
    future = prices[start + 1:]
    if not len(future):
        return len(prices) - 1
    return int(start + 1 + np.nanargmax(future))


def entry_event(
    model: str,
    code: str,
    day: str,
    index: int,
    base: dict,
    feature: daily.DailyFeature,
    prev_close: Optional[float],
    item: dict,
    threshold: float,
    scale: float,
) -> dict:
    event = window_bt.make_event(
        model, code, day, index, base, feature, prev_close,
        float(item["net"][index]), float(item["buy"][index]),
        float(item["sell"][index]), threshold, scale,
    )
    event["model"] = model
    event["atr_pct"] = feature.atr20 / event["price"] if event["price"] > 0 else None
    return event


def exit_trade(entry: dict, base: dict, exit_index: int, reason: str) -> dict:
    prices = base["p"]
    entry_price = float(entry["price"])
    exit_price = float(prices[exit_index])
    eod_price = float(prices[-1])
    exit_return = exit_price / entry_price - 1.0
    hold_return = eod_price / entry_price - 1.0
    post_exit = eod_price / exit_price - 1.0
    return {
        "code": entry["code"],
        "day": entry["day"],
        "day_change": entry.get("day_change"),
        "extension_atr": entry.get("extension_atr"),
        "structure": entry.get("structure"),
        "atr_pct": entry.get("atr_pct"),
        "inflow_count_30": entry.get("inflow_count_30"),
        "inflow_count_60": entry.get("inflow_count_60"),
        "entry_minute": entry.get("minute"),
        "exit_minute": flow.GRID[exit_index],
        "entry_index": entry["index"],
        "exit_index": int(exit_index),
        "minutes": int(exit_index - entry["index"]),
        "reason": reason,
        "exit_return": float(exit_return),
        "exit_after_cost": float(exit_return - ROUND_TRIP_COST),
        "hold_eod": float(hold_return),
        "saved_vs_hold": float(exit_return - hold_return),
        "post_exit": float(post_exit),
    }


def sequence_summary(rows: Sequence[dict]) -> Optional[dict]:
    result = window_bt.summarize(rows)
    if not result:
        return None
    return result


def exit_summary(rows: Sequence[dict]) -> Optional[dict]:
    if not rows:
        return None
    result = {"n": len(rows), "stocks": len({row["code"] for row in rows}),
              "days": len({row["day"] for row in rows})}
    for key in ("exit_return", "exit_after_cost", "hold_eod", "saved_vs_hold", "post_exit"):
        values = np.asarray([row[key] for row in rows], dtype=float)
        result[f"{key}_mean"] = float(values.mean())
        result[f"{key}_median"] = float(np.median(values))
        result[f"{key}_hit"] = float((values > 0).mean())
    minutes = np.asarray([row["minutes"] for row in rows], dtype=float)
    result["minutes_median"] = float(np.median(minutes))
    by_day = defaultdict(list)
    for row in rows:
        by_day[row["day"]].append(float(row["exit_after_cost"]))
    day_means = np.asarray([np.mean(sample) for sample in by_day.values()], dtype=float)
    result["day_mean"] = float(day_means.mean())
    result["positive_days"] = float((day_means > 0).mean())
    if len(day_means) >= 2:
        rng = np.random.default_rng(20260713 + len(rows))
        boots = [
            float(rng.choice(day_means, size=len(day_means), replace=True).mean())
            for _ in range(1000)
        ]
        result["day_ci95"] = [float(np.percentile(boots, 2.5)),
                              float(np.percentile(boots, 97.5))]
    else:
        result["day_ci95"] = [None, None]
    return result


def print_entry(label: str, result: Optional[dict]) -> None:
    if not result:
        print(f"  {label:<26} 无样本")
        return
    print(
        f"  {label:<26} N={result['n']:3d} 股={result['stocks']:2d} 天={result['days']:2d} "
        f"15m={daily.pct(result['r15_mean'])} 30m={daily.pct(result['r30_mean'])} "
        f"60m={daily.pct(result['r60_mean'])} EOD={daily.pct(result['eod_mean'])} "
        f"成本后={daily.pct(result['eod_after_cost'])} 日均={daily.pct(result['day_mean'])} "
        f"MFE60={daily.pct(result['mfe60_median'])} >=5%={result['mfe_eod_ge5'] * 100:4.1f}%"
    )


def print_exit(label: str, result: Optional[dict]) -> None:
    if not result:
        print(f"  {label:<26} 无样本")
        return
    print(
        f"  {label:<26} N={result['n']:3d} 股={result['stocks']:2d} 天={result['days']:2d} "
        f"触发中位={result['minutes_median']:.0f}m "
        f"退出收益={daily.pct(result['exit_return_mean'])} 成本后={daily.pct(result['exit_after_cost_mean'])} "
        f"日均={daily.pct(result['day_mean'])} 正日={result['positive_days'] * 100:.0f}% "
        f"若持有EOD={daily.pct(result['hold_eod_mean'])} "
        f"退出改善={daily.pct(result['saved_vs_hold_mean'])} "
        f"退出后股价={daily.pct(result['post_exit_mean'])}"
    )


def momentum(rows: Sequence[dict]) -> List[dict]:
    return [
        row for row in rows
        if row.get("day_change") is not None and row["day_change"] >= 0.03
        and row["extension_atr"] < 1.0
    ]


def momentum_exits(rows: Sequence[dict]) -> List[dict]:
    return [
        row for row in rows
        if row.get("day_change") is not None and row["day_change"] >= 0.03
        and row.get("extension_atr") is not None and row["extension_atr"] < 1.0
    ]


def latest_atr_pct(rows: Sequence[daily.DailyBar], cutoff_day: str) -> Optional[float]:
    history = [row for row in rows if row.day <= cutoff_day]
    if len(history) < 21:
        return None
    ranges = []
    for index in range(len(history) - 20, len(history)):
        row = history[index]
        previous_close = history[index - 1].close
        ranges.append(max(
            row.high - row.low,
            abs(row.high - previous_close),
            abs(row.low - previous_close),
        ))
    return float(np.mean(ranges) / history[-1].close) if history[-1].close > 0 else None


def daily_top_quartile(rows: Sequence[dict]) -> List[dict]:
    by_day = defaultdict(list)
    for row in rows:
        value = row.get("atr_pct")
        if value is not None and np.isfinite(value):
            by_day[row["day"]].append(float(value))
    thresholds = {
        day: float(np.percentile(values, 75)) for day, values in by_day.items() if values
    }
    return [
        row for row in rows
        if row.get("atr_pct") is not None and row["day"] in thresholds
        and row["atr_pct"] >= thresholds[row["day"]]
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=flow.DEFAULT_DB)
    parser.add_argument("--universe-limit", type=int, default=30)
    parser.add_argument("--volatile-count", type=int, default=8)
    parser.add_argument("--json", default="")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db, uri=True)
    conn.execute("PRAGMA query_only=ON")
    days, dropped = flow.full_days(conn)
    universe_rows = daily.load_hot_ai_semiconductor_universe(
        conn, days[0], days[-1], max(1, args.universe_limit),
    )
    allowed = {row["code"] for row in universe_rows}
    bars = daily.load_daily_bars(conn)
    next_close = daily.build_next_close(bars)
    previous_close = {
        (code, rows[index].day): rows[index - 1].close
        for code, rows in bars.items()
        for index in range(1, len(rows))
    }

    histories = defaultdict(lambda: deque(maxlen=CALIB_DAYS))
    groups: Dict[int, Dict[str, List[dict]]] = {
        window: defaultdict(list) for window in WINDOWS
    }
    exits: Dict[int, Dict[str, List[dict]]] = {
        window: defaultdict(list) for window in WINDOWS
    }
    exit_rules: Dict[str, List[dict]] = defaultdict(list)

    for day in days:
        records = flow.load_day(conn, day)
        for code, record in records.items():
            if code not in allowed:
                continue
            base = flow.derive(record, code, day, next_close)
            threshold = float(record.get("thr") or 0.0)
            if base is None or threshold <= 0:
                continue
            arrays = window_bt.window_arrays(record)
            active = (record["cb"] + record["cs"]) > 0

            for win in WINDOWS:
                item = arrays[win]
                scale = window_bt.causal_scale(histories[(code, win)], threshold)
                if scale is None:
                    continue
                valid_price = np.isfinite(base["p"])
                inflow_mask = (
                    (item["net"] >= 3.0 * threshold)
                    & (item["net"] >= scale)
                    & (item["buy"] >= 3.0 * item["sell"])
                    & (record["cb"] > 0)
                    & valid_price
                )
                confirmations = pick_confirmations(inflow_mask)
                if not confirmations:
                    continue

                first = confirmations[0]
                first_feature = daily.daily_feature(code, day, float(base["p"][first]), bars)
                if first_feature is None:
                    continue
                first_event = entry_event(
                    "首次强流入", code, day, first, base, first_feature,
                    previous_close.get((code, day)), item, threshold, scale,
                )
                groups[win]["首次强流入"].append(first_event)

                later30 = [index for index in confirmations[1:] if index - first <= 30]
                later60 = [index for index in confirmations[1:] if index - first <= 60]
                first_event["inflow_count_30"] = 1 + len(later30)
                first_event["inflow_count_60"] = 1 + len(later60)
                second_event = None
                if not later30:
                    groups[win]["30分钟内无二次流入"].append(first_event)
                if later30:
                    second = later30[0]
                    feature = daily.daily_feature(code, day, float(base["p"][second]), bars)
                    if feature is not None:
                        second_event = entry_event(
                            "30分钟内二次流入", code, day, second, base, feature,
                            previous_close.get((code, day)), item, threshold, scale,
                        )
                        second_event["confirm_delay"] = second - first
                        groups[win]["30分钟内二次流入"].append(second_event)
                if len(later60) >= 2:
                    third = later60[1]
                    feature = daily.daily_feature(code, day, float(base["p"][third]), bars)
                    if feature is not None:
                        third_event = entry_event(
                            "60分钟内三次流入", code, day, third, base, feature,
                            previous_close.get((code, day)), item, threshold, scale,
                        )
                        third_event["confirm_delay"] = third - first
                        groups[win]["60分钟内三次流入"].append(third_event)

                soft_mask = (item["net"] <= 0) & valid_price
                hard_mask = (
                    (item["net"] <= -threshold)
                    & (record["cs"] > 0)
                    & valid_price
                )
                strong_out_mask = (
                    (item["net"] <= -3.0 * threshold)
                    & (item["sell"] >= 3.0 * item["buy"])
                    & (record["cs"] > 0)
                    & valid_price
                )
                soft = first_after(soft_mask, first, 60)
                hard = first_after(hard_mask, first, 60)
                hard_any = first_after(hard_mask, first)
                strong_out = first_after(strong_out_mask, first, 60)
                strategy_exit_index = hard_any if hard_any is not None else len(base["p"]) - 1
                exits[win]["首次流入·硬流出否则EOD"].append(
                    exit_trade(
                        first_event, base, strategy_exit_index,
                        "hard" if hard_any is not None else "eod",
                    )
                )
                if win == 10:
                    prices = base["p"]
                    take3 = first_target(prices, first, 0.03)
                    take5 = first_target(prices, first, 0.05)
                    trail10 = trailing_exit(prices, first, 0.03, 0.01)
                    trail15 = trailing_exit(prices, first, 0.03, 0.015)
                    trail20 = trailing_exit(prices, first, 0.03, 0.02)
                    rule_indices = {
                        "收盘退出": len(prices) - 1,
                        "硬流出否则收盘": earliest_or_eod(prices, hard_any),
                        "+3%止盈否则收盘": earliest_or_eod(prices, take3),
                        "+5%止盈否则收盘": earliest_or_eod(prices, take5),
                        "+3%启动·峰值回撤1%": earliest_or_eod(prices, trail10),
                        "+3%启动·峰值回撤1.5%": earliest_or_eod(prices, trail15),
                        "+3%启动·峰值回撤2%": earliest_or_eod(prices, trail20),
                        "硬流出或+3%止盈": earliest_or_eod(prices, hard_any, take3),
                        "硬流出或+5%止盈": earliest_or_eod(prices, hard_any, take5),
                        "硬流出或回撤1.5%": earliest_or_eod(prices, hard_any, trail15),
                        "事后最高点(不可交易)": oracle_high(prices, first),
                    }
                    for rule_name, exit_index in rule_indices.items():
                        exit_rules[rule_name].append(
                            exit_trade(first_event, base, exit_index, rule_name)
                        )
                if soft is not None:
                    groups[win]["60分钟内净额翻负"].append(first_event)
                    exits[win]["净额翻负退出"].append(exit_trade(first_event, base, soft, "soft"))
                if hard is not None:
                    groups[win]["60分钟内硬流出"].append(first_event)
                    exits[win]["硬流出退出"].append(exit_trade(first_event, base, hard, "hard"))
                    rein = next((index for index in confirmations if index > hard and index - hard <= 60), None)
                    if rein is not None:
                        feature = daily.daily_feature(code, day, float(base["p"][rein]), bars)
                        if feature is not None:
                            rein_event = entry_event(
                                "流出后60分钟内再流入", code, day, rein, base, feature,
                                previous_close.get((code, day)), item, threshold, scale,
                            )
                            rein_event["reentry_delay"] = rein - hard
                            groups[win]["流出后60分钟内再流入"].append(rein_event)
                if strong_out is not None:
                    exits[win]["强流出退出"].append(
                        exit_trade(first_event, base, strong_out, "strong_out")
                    )
                if hard is None:
                    groups[win]["60分钟内无硬流出"].append(first_event)
                if second_event is not None:
                    hard_after_second = first_after(hard_mask, second_event["index"], 30)
                    hard_after_second_any = first_after(hard_mask, second_event["index"])
                    strategy_exit_index = (
                        hard_after_second_any
                        if hard_after_second_any is not None else len(base["p"]) - 1
                    )
                    exits[win]["二次流入·硬流出否则EOD"].append(
                        exit_trade(
                            second_event, base, strategy_exit_index,
                            "second_hard" if hard_after_second_any is not None else "eod",
                        )
                    )
                    if hard_after_second is not None:
                        groups[win]["二次流入后30分钟硬流出"].append(second_event)
                        exits[win]["二次流入后硬流出退出"].append(
                            exit_trade(second_event, base, hard_after_second, "second_hard")
                        )
                    else:
                        groups[win]["二次流入后30分钟无硬流出"].append(second_event)

            for win in WINDOWS:
                sample = np.abs(arrays[win]["net"][active])
                sample = sample[np.isfinite(sample)]
                if len(sample):
                    histories[(code, win)].append(sample)

    print("【资金流事件序列回测】")
    print(f"完整日={len(days)}，因果标定后评估日={len(days) - MIN_CALIB_DAYS}，热门池={len(universe_rows)}")
    print(f"剔除日={dropped}")
    print("强流入确认间隔>=5分钟；软翻转=窗口净额<=0；硬流出=净流出>=1×大单门槛")

    entry_order = (
        "首次强流入", "30分钟内无二次流入", "30分钟内二次流入", "60分钟内三次流入",
        "60分钟内无硬流出", "60分钟内净额翻负", "60分钟内硬流出",
        "二次流入后30分钟无硬流出", "二次流入后30分钟硬流出", "流出后60分钟内再流入",
    )
    exit_order = (
        "首次流入·硬流出否则EOD", "二次流入·硬流出否则EOD",
        "净额翻负退出", "硬流出退出", "强流出退出", "二次流入后硬流出退出",
    )
    evaluation_days = days[MIN_CALIB_DAYS:]
    split = max(1, len(evaluation_days) - 5)
    train_days = set(evaluation_days[:split])
    test_days = set(evaluation_days[split:])
    output = {"days": days, "universe": universe_rows, "windows": {}}
    for win in WINDOWS:
        print(f"\n{'=' * 100}\n{win}分钟窗口·全部热门池")
        win_out = {"all": {}, "momentum": {}, "exits": {}}
        for name in entry_order:
            result = sequence_summary(groups[win][name])
            print_entry(name, result)
            win_out["all"][name] = result
        print(f"\n{win}分钟窗口·热门动量（日涨>=3%且延伸<1ATR）")
        for name in entry_order:
            result = sequence_summary(momentum(groups[win][name]))
            print_entry(name, result)
            win_out["momentum"][name] = result
        print(f"\n{win}分钟窗口·流出退出")
        for name in exit_order:
            result = exit_summary(exits[win][name])
            print_exit(name, result)
            win_out["exits"][name] = result
        print(f"\n{win}分钟窗口·热门动量流出退出")
        win_out["momentum_exits"] = {}
        for name in exit_order:
            result = exit_summary(momentum_exits(exits[win][name]))
            print_exit(name, result)
            win_out["momentum_exits"][name] = result
        print(f"\n{win}分钟窗口·因果策略前后时段")
        win_out["exit_time_split"] = {}
        for name in ("首次流入·硬流出否则EOD", "二次流入·硬流出否则EOD"):
            all_rows = exits[win][name]
            hot_rows = momentum_exits(all_rows)
            split_result = {
                "all_train": exit_summary([row for row in all_rows if row["day"] in train_days]),
                "all_test": exit_summary([row for row in all_rows if row["day"] in test_days]),
                "momentum_train": exit_summary([row for row in hot_rows if row["day"] in train_days]),
                "momentum_test": exit_summary([row for row in hot_rows if row["day"] in test_days]),
            }
            win_out["exit_time_split"][name] = split_result
            print_exit(f"{name}·前{split}日", split_result["all_train"])
            print_exit(f"{name}·后{len(evaluation_days) - split}日", split_result["all_test"])
        output["windows"][str(win)] = win_out

    name_by_code = {row["code"]: row["name"] for row in universe_rows}
    volatility = []
    for code in allowed:
        atr_pct = latest_atr_pct(bars.get(code, []), days[-1])
        if atr_pct is not None:
            volatility.append({"code": code, "name": name_by_code.get(code, ""),
                               "atr_pct": atr_pct})
    volatility.sort(key=lambda row: row["atr_pct"], reverse=True)
    selected = volatility[:max(1, args.volatile_count)]
    strategy_rows = exits[10]["首次流入·硬流出否则EOD"]
    print(f"\n{'=' * 100}\n近期20日ATR波动率最高的热门股·10分钟状态机")
    stock_review = []
    for stock in selected:
        rows = [row for row in strategy_rows if row["code"] == stock["code"]]
        result = exit_summary(rows)
        print(
            f"  {stock['code']} {stock['name']:<12} ATR={stock['atr_pct'] * 100:5.2f}% "
            f"N={len(rows):2d} 成本后={daily.pct(result['exit_after_cost_mean'] if result else None)} "
            f"若持有={daily.pct(result['hold_eod_mean'] if result else None)} "
            f"退出改善={daily.pct(result['saved_vs_hold_mean'] if result else None)}"
        )
        cases = [
            {
                "day": row["day"],
                "entry_minute": row["entry_minute"],
                "day_change": row["day_change"],
                "atr_pct": row["atr_pct"],
                "inflow_count_30": row["inflow_count_30"],
                "inflow_count_60": row["inflow_count_60"],
                "exit_reason": row["reason"],
                "exit_minute": row["exit_minute"],
                "exit_after_cost": row["exit_after_cost"],
                "hold_eod": row["hold_eod"],
                "saved_vs_hold": row["saved_vs_hold"],
            }
            for row in sorted(rows, key=lambda item: item["day"])
        ]
        stock_review.append({**stock, "strategy": result, "cases": cases})

    dynamic_high_vol = daily_top_quartile(strategy_rows)
    dynamic_result = exit_summary(dynamic_high_vol)
    print("\n每日信号股ATR前25%（动态、避免按最终涨幅选股）")
    print_exit("10分钟首次流入状态机", dynamic_result)
    output["volatile_review"] = {
        "selected_current": stock_review,
        "dynamic_top_quartile": dynamic_result,
    }

    print(f"\n{'=' * 100}\n10分钟首次强流入·止盈与跟踪退出")
    output["exit_rule_review"] = {}
    for rule_name, rows in exit_rules.items():
        all_result = exit_summary(rows)
        momentum_result = exit_summary(momentum_exits(rows))
        high_vol_result = exit_summary(daily_top_quartile(rows))
        output["exit_rule_review"][rule_name] = {
            "all": all_result,
            "momentum": momentum_result,
            "dynamic_high_vol": high_vol_result,
        }
        print_exit(f"{rule_name}·全部", all_result)
        print_exit(f"{rule_name}·高波动", high_vol_result)

    if args.json:
        Path(args.json).write_text(
            json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8",
        )
        print(f"\nJSON -> {args.json}")


if __name__ == "__main__":
    main()
