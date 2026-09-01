#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""10分钟强流入次数 × 分钟市场宽度交叉回测。"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Dict, List, Sequence

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import big_order_flow_eval as flow  # noqa: E402
import capital_flow_sequence_backtest as sequence  # noqa: E402
import capital_window_backtest as window_bt  # noqa: E402
import daily_position_flow_backtest as daily  # noqa: E402


WINDOW = 10
CALIB_DAYS = 5
MIN_CALIB_DAYS = 3
CHECK_CASES = (
    ("HK.06082", "2026-06-25"),
    ("HK.01888", "2026-06-24"),
    ("HK.06082", "2026-07-10"),
)
TRAIL_PULLBACK = 0.015
CONFIRM_TIMEOUTS = (10, 15, 20, 30, 60)


def build_breadth(
    records: Dict[str, dict],
    derived: Dict[str, dict],
    day: str,
    previous_close: Dict[tuple, float],
) -> tuple[np.ndarray, np.ndarray]:
    up = np.zeros(flow.NG, dtype=float)
    count = np.zeros(flow.NG, dtype=int)
    for code in records:
        if not code.startswith("HK."):
            continue
        base = derived.get(code)
        prev = previous_close.get((code, day))
        if base is None or prev is None or prev <= 0:
            continue
        prices = base["p"]
        valid = np.isfinite(prices)
        up[valid] += prices[valid] > prev
        count[valid] += 1
    breadth = np.full(flow.NG, np.nan)
    valid_count = count >= 20
    breadth[valid_count] = up[valid_count] / count[valid_count]
    return breadth, count


def breadth_bin(value: float) -> str:
    if not np.isfinite(value):
        return "无数据"
    if value < 0.45:
        return "弱市<45%"
    if value < 0.55:
        return "震荡45~55%"
    return "强市>=55%"


def count_bin(value: int) -> str:
    if value <= 1:
        return "1次"
    if value == 2:
        return "2次"
    return "3次以上"


def print_group(title: str, rows: Sequence[dict], key) -> dict:
    grouped = defaultdict(list)
    for row in rows:
        grouped[key(row)].append(row)
    print(f"\n[{title}]")
    output = {}
    for label, sample in sorted(grouped.items()):
        result = window_bt.summarize(sample)
        if not result:
            continue
        window_bt.print_summary(label, result)
        output[label] = result
    return output


def continuation_summary(rows: Sequence[dict]) -> dict | None:
    result = window_bt.summarize(rows)
    if not result:
        return None
    valid = [
        row for row in rows
        if all(row.get(f"r{h}") is not None for h in (5, 15, 30))
    ]
    if valid:
        result["positive_5_15_30"] = float(np.mean([
            row["r5"] > 0 and row["r15"] > 0 and row["r30"] > 0
            for row in valid
        ]))
        result["positive_15_30"] = float(np.mean([
            row["r15"] > 0 and row["r30"] > 0 for row in valid
        ]))
    else:
        result["positive_5_15_30"] = None
        result["positive_15_30"] = None
    mae = np.asarray([
        row["mae60"] for row in rows
        if row.get("mae60") is not None and np.isfinite(row["mae60"])
    ], dtype=float)
    result["mae60_median"] = float(np.median(mae)) if len(mae) else None
    result["mae60_le_minus2"] = float((mae <= -0.02).mean()) if len(mae) else None
    gains = np.asarray([
        row["gain_from_first"] for row in rows
        if row.get("gain_from_first") is not None and np.isfinite(row["gain_from_first"])
    ], dtype=float)
    delays = np.asarray([
        row["delay_from_first"] for row in rows
        if row.get("delay_from_first") is not None
    ], dtype=float)
    result["gain_from_first_mean"] = float(gains.mean()) if len(gains) else None
    result["delay_from_first_median"] = float(np.median(delays)) if len(delays) else None
    return result


def print_continuation(label: str, result: dict | None) -> None:
    if not result:
        print(f"  {label:<12} 无样本")
        return
    print(
        f"  {label:<12} N={result['n']:3d} 确认前已涨={daily.pct(result['gain_from_first_mean'])} "
        f"延迟中位={result['delay_from_first_median']:.0f}m "
        f"5m={daily.pct(result['r5_mean'])}/{result['r5_hit'] * 100:.0f}% "
        f"15m={daily.pct(result['r15_mean'])}/{result['r15_hit'] * 100:.0f}% "
        f"30m={daily.pct(result['r30_mean'])}/{result['r30_hit'] * 100:.0f}% "
        f"60m={daily.pct(result['r60_mean'])}/{result['r60_hit'] * 100:.0f}% "
        f"15&30均上涨={result['positive_15_30'] * 100:.0f}% "
        f"MAE60={daily.pct(result['mae60_median'])} 回撤>=2%={result['mae60_le_minus2'] * 100:.0f}%"
    )


def add_peak_trailing_exit(event: dict, base: dict, index: int) -> None:
    """从确认价开始更新峰值，回撤1.5%退出；未触发则收盘退出。"""
    prices = base["p"]
    entry_price = float(event["price"])
    peak = entry_price
    exit_index = len(prices) - 1
    triggered = False
    for cursor in range(index + 1, len(prices)):
        price = float(prices[cursor])
        if not np.isfinite(price):
            continue
        peak = max(peak, price)
        if price <= peak * (1.0 - TRAIL_PULLBACK):
            exit_index = cursor
            triggered = True
            break
    exit_price = float(prices[exit_index])
    event["trail15_return"] = exit_price / entry_price - 1.0
    event["trail15_triggered"] = triggered
    event["trail15_exit_time"] = flow.GRID[exit_index]
    event["trail15_peak_return"] = peak / entry_price - 1.0
    event["trail15_improvement"] = event["trail15_return"] - event["eod"]


def add_confirm_then_trailing_exits(
    event: dict,
    base: dict,
    confirmations: Sequence[int],
) -> None:
    """首次入场后等第二次确认；确认后才启用1.5%峰值回撤。"""
    prices = base["p"]
    first = int(event["index"])
    entry_price = float(event["price"])
    second = int(confirmations[1]) if len(confirmations) >= 2 else None
    for timeout in CONFIRM_TIMEOUTS:
        confirmed = second is not None and second - first <= timeout
        if not confirmed:
            exit_index = min(first + timeout, len(prices) - 1)
            exit_price = float(prices[exit_index])
            event[f"confirm{timeout}_trail15_return"] = exit_price / entry_price - 1.0
            event[f"confirm{timeout}_trail15_confirmed"] = False
            event[f"confirm{timeout}_trail15_exit_time"] = flow.GRID[exit_index]
            continue

        peak = float(prices[second])
        exit_index = len(prices) - 1
        for cursor in range(second + 1, len(prices)):
            price = float(prices[cursor])
            if not np.isfinite(price):
                continue
            peak = max(peak, price)
            if price <= peak * (1.0 - TRAIL_PULLBACK):
                exit_index = cursor
                break
        exit_price = float(prices[exit_index])
        event[f"confirm{timeout}_trail15_return"] = exit_price / entry_price - 1.0
        event[f"confirm{timeout}_trail15_confirmed"] = True
        event[f"confirm{timeout}_trail15_exit_time"] = flow.GRID[exit_index]


def trailing_summary(rows: Sequence[dict]) -> dict | None:
    valid = [row for row in rows if row.get("trail15_return") is not None]
    if not valid:
        return None
    stats_rows = [{**row, "eod": row["trail15_return"]} for row in valid]
    result = daily.stats(stats_rows)
    if not result:
        return None
    result["triggered"] = float(np.mean([row["trail15_triggered"] for row in valid]))
    result["improvement"] = float(np.mean([row["trail15_improvement"] for row in valid]))
    result["peak_mean"] = float(np.mean([row["trail15_peak_return"] for row in valid]))
    oracle = np.asarray([
        (1.0 + float(row["mfe_eod"])) * (1.0 - TRAIL_PULLBACK) - 1.0
        for row in valid
        if row.get("mfe_eod") is not None and np.isfinite(row["mfe_eod"])
    ], dtype=float)
    result["oracle_high_minus_15"] = float(oracle.mean()) if len(oracle) else None
    result["oracle_high_minus_15_after_cost"] = (
        float(oracle.mean() - daily.ROUND_TRIP_COST) if len(oracle) else None
    )
    return result


def print_trailing(label: str, rows: Sequence[dict]) -> dict | None:
    result = trailing_summary(rows)
    if not result:
        print(f"  {label:<18} 无样本")
        return None
    print(
        f"  {label:<18} N={result['n']:3d} 毛收益={daily.pct(result['eod_mean'])} "
        f"中位={daily.pct(result['eod_median'])} 成本后={daily.pct(result['eod_after_cost'])} "
        f"胜率={result['eod_hit'] * 100:.0f}% 日均={daily.pct(result['day_mean'])} "
        f"触发率={result['triggered'] * 100:.0f}% 峰值={daily.pct(result['peak_mean'])} "
        f"较收盘改善={daily.pct(result['improvement'])} "
        f"事后最高-1.5%={daily.pct(result['oracle_high_minus_15_after_cost'])}"
    )
    return result


def print_confirm_then_trailing(rows: Sequence[dict], timeout: int) -> dict | None:
    value_key = f"confirm{timeout}_trail15_return"
    confirmed_key = f"confirm{timeout}_trail15_confirmed"
    valid = [row for row in rows if row.get(value_key) is not None]
    if not valid:
        return None
    result = daily.stats([{**row, "eod": row[value_key]} for row in valid])
    if not result:
        return None
    result["confirmed"] = float(np.mean([row[confirmed_key] for row in valid]))
    print(
        f"  等待{timeout:>2}m二次确认       N={result['n']:3d} "
        f"确认率={result['confirmed'] * 100:.0f}% 毛收益={daily.pct(result['eod_mean'])} "
        f"中位={daily.pct(result['eod_median'])} 成本后={daily.pct(result['eod_after_cost'])} "
        f"胜率={result['eod_hit'] * 100:.0f}% 日均={daily.pct(result['day_mean'])} "
        f"CI=[{daily.pct(result['day_ci95'][0])},{daily.pct(result['day_ci95'][1])}]"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=flow.DEFAULT_DB)
    parser.add_argument("--universe-limit", type=int, default=30)
    parser.add_argument("--json", default="")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db, uri=True)
    conn.execute("PRAGMA query_only=ON")
    days, dropped = flow.full_days(conn)
    universe_rows = daily.load_hot_ai_semiconductor_universe(
        conn, days[0], days[-1], max(1, args.universe_limit),
    )
    allowed = {row["code"] for row in universe_rows}
    names = {row["code"]: row["name"] for row in universe_rows}
    bars = daily.load_daily_bars(conn)
    next_close = daily.build_next_close(bars)
    previous_close = {
        (code, rows[index].day): rows[index - 1].close
        for code, rows in bars.items()
        for index in range(1, len(rows))
    }
    histories = defaultdict(lambda: deque(maxlen=CALIB_DAYS))
    first_rows: List[dict] = []
    second_rows: List[dict] = []
    third_rows: List[dict] = []
    cases = []

    for day in days:
        records = flow.load_day(conn, day)
        derived = {
            code: flow.derive(record, code, day, next_close)
            for code, record in records.items()
        }
        breadth, breadth_count = build_breadth(records, derived, day, previous_close)

        for code, record in records.items():
            if code not in allowed:
                continue
            base = derived.get(code)
            threshold = float(record.get("thr") or 0.0)
            if base is None or threshold <= 0:
                continue
            item = window_bt.window_arrays(record)[WINDOW]
            active = (record["cb"] + record["cs"]) > 0
            scale = window_bt.causal_scale(histories[code], threshold)
            if scale is not None:
                mask = (
                    (item["net"] >= 3.0 * threshold)
                    & (item["net"] >= scale)
                    & (item["buy"] >= 3.0 * item["sell"])
                    & (record["cb"] > 0)
                    & np.isfinite(base["p"])
                )
                confirmations = sequence.pick_confirmations(mask)
                if confirmations:
                    first = confirmations[0]
                    within60 = [index for index in confirmations if index - first <= 60]
                    feature = daily.daily_feature(code, day, float(base["p"][first]), bars)
                    if feature is not None:
                        event = sequence.entry_event(
                            "首次强流入", code, day, first, base, feature,
                            previous_close.get((code, day)), item, threshold, scale,
                        )
                        add_peak_trailing_exit(event, base, first)
                        add_confirm_then_trailing_exits(event, base, within60)
                        event["breadth"] = float(breadth[first])
                        event["breadth_count"] = int(breadth_count[first])
                        event["inflow_count_60"] = len(within60)
                        event["confirmation_times"] = [flow.GRID[index] for index in within60]
                        event["confirmation_breadths"] = [
                            float(breadth[index]) if np.isfinite(breadth[index]) else None
                            for index in within60
                        ]
                        first_rows.append(event)

                        for position, target in ((1, second_rows), (2, third_rows)):
                            if len(within60) <= position:
                                continue
                            index = within60[position]
                            next_feature = daily.daily_feature(
                                code, day, float(base["p"][index]), bars,
                            )
                            if next_feature is None:
                                continue
                            confirmation = sequence.entry_event(
                                f"第{position + 1}次强流入", code, day, index,
                                base, next_feature, previous_close.get((code, day)),
                                item, threshold, scale,
                            )
                            add_peak_trailing_exit(confirmation, base, index)
                            confirmation["breadth"] = float(breadth[index])
                            confirmation["breadth_count"] = int(breadth_count[index])
                            confirmation["sequence_no"] = position + 1
                            confirmation["gain_from_first"] = (
                                confirmation["price"] / event["price"] - 1.0
                            )
                            confirmation["delay_from_first"] = index - first
                            target.append(confirmation)

                        if (code, day) in CHECK_CASES:
                            cases.append({
                                "code": code,
                                "name": names.get(code, ""),
                                "day": day,
                                "first_time": flow.GRID[first],
                                "day_change": event.get("day_change"),
                                "breadth": event["breadth"],
                                "breadth_count": event["breadth_count"],
                                "confirmation_times": event["confirmation_times"],
                                "confirmation_breadths": event["confirmation_breadths"],
                                "eod": event.get("eod"),
                                "mfe60": event.get("mfe60"),
                                "mfe_eod": event.get("mfe_eod"),
                                "trail15_return": event.get("trail15_return"),
                                "trail15_exit_time": event.get("trail15_exit_time"),
                                "trail15_peak_return": event.get("trail15_peak_return"),
                            })

            sample = np.abs(item["net"][active])
            sample = sample[np.isfinite(sample)]
            if len(sample):
                histories[code].append(sample)

    print("【10分钟流入次数 × 市场宽度】")
    print(f"完整日={len(days)}，因果评估日={len(days) - MIN_CALIB_DAYS}，热门池={len(universe_rows)}")
    print(f"剔除日={dropped}")
    output = {"days": days, "cases": cases, "groups": {}}
    output["groups"]["count"] = print_group(
        "从第一次流入持有：60分钟内最终确认次数（诊断）",
        first_rows, lambda row: count_bin(row["inflow_count_60"]),
    )
    output["groups"]["breadth"] = print_group(
        "第一次流入时的市场宽度", first_rows,
        lambda row: breadth_bin(row["breadth"]),
    )
    output["groups"]["count_breadth"] = print_group(
        "确认次数 × 第一次流入市场宽度", first_rows,
        lambda row: f"{count_bin(row['inflow_count_60'])}·{breadth_bin(row['breadth'])}",
    )
    output["groups"]["second_breadth"] = print_group(
        "第二次流入真正出现后（可执行持有确认）", second_rows,
        lambda row: breadth_bin(row["breadth"]),
    )
    output["groups"]["third_breadth"] = print_group(
        "第三次流入真正出现后（可执行持有确认）", third_rows,
        lambda row: breadth_bin(row["breadth"]),
    )

    print("\n[第二/第三次流入出现时的可执行延续性]")
    second_result = continuation_summary(second_rows)
    third_result = continuation_summary(third_rows)
    print_continuation("第二次确认", second_result)
    print_continuation("第三次确认", third_result)
    output["continuation"] = {
        "second": second_result,
        "third": third_result,
    }

    print("\n[从确认价起跟踪日内峰值：回撤1.5%卖出，否则收盘卖出]")
    trailing = {}
    for label, sample in (
        ("首次确认·全部", first_rows),
        ("首次确认·最终1次", [row for row in first_rows if row["inflow_count_60"] == 1]),
        ("首次确认·最终2次", [row for row in first_rows if row["inflow_count_60"] == 2]),
        ("首次确认·最终3次+", [row for row in first_rows if row["inflow_count_60"] >= 3]),
        ("第二次确认时入场", second_rows),
        ("第三次确认时入场", third_rows),
    ):
        trailing[label] = print_trailing(label, sample)
    output["peak_trailing_15"] = trailing

    print("\n[可执行状态机：首次试仓，限时等第二次确认，确认后启动峰值回撤1.5%]")
    confirm_then_trailing = {}
    for timeout in CONFIRM_TIMEOUTS:
        confirm_then_trailing[str(timeout)] = print_confirm_then_trailing(first_rows, timeout)
    output["confirm_then_peak_trailing_15"] = confirm_then_trailing

    print("\n[代表事件]")
    for case in cases:
        flows = ", ".join(
            f"{time}({value * 100:.0f}%)"
            for time, value in zip(case["confirmation_times"], case["confirmation_breadths"])
            if value is not None
        )
        print(
            f"  {case['day']} {case['code']} {case['name']} 首次={case['first_time']} "
            f"宽度={case['breadth'] * 100:.1f}%/{case['breadth_count']}股 "
            f"流入={flows} EOD={daily.pct(case['eod'])} MFE60={daily.pct(case['mfe60'])} "
            f"回撤1.5%={daily.pct(case['trail15_return'])}@{case['trail15_exit_time']} "
            f"退出前峰值={daily.pct(case['trail15_peak_return'])}"
        )

    if args.json:
        Path(args.json).write_text(
            json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8",
        )
        print(f"\nJSON -> {args.json}")


if __name__ == "__main__":
    main()
