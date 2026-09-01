#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""比较 1/3/5/10/15 分钟资金流窗口与多周期共振。

口径：
* 大额流入保持生产条件：窗口净流入 >= 3×大单门槛、窗口大买 >= 3×大卖、当前分钟有新大买。
* 力度基准按股票和窗口分别标定，只使用信号日前最多 5 个完整日，至少 3 日才出信号。
* 滚动窗口在午休处重置，贴近生产 900 秒真实时间窗口。
* 每股每天每个模型只取首次触发，收益从触发分钟价格起算。
"""

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
import daily_position_flow_backtest as daily  # noqa: E402


WINDOWS = (1, 3, 5, 10, 15)
CALIB_DAYS = 5
MIN_CALIB_DAYS = 3
ROUND_TRIP_COST = 0.0025
MODEL_ORDER = (
    "W1", "W3", "W5", "W10", "W15",
    "MTF_1加速_5持续_15同向",
    "MTF_1触发_5确认_15背景",
    "MTF_5触发_1加速_15背景",
    "MTF_15触发_5持续_1加速",
)
MODEL_ANCHOR = {
    "W1": 1,
    "W3": 3,
    "W5": 5,
    "W10": 10,
    "W15": 15,
    "MTF_1加速_5持续_15同向": 1,
    "MTF_1触发_5确认_15背景": 1,
    "MTF_5触发_1加速_15背景": 5,
    "MTF_15触发_5持续_1加速": 15,
}


def rolling_sum(values: np.ndarray, window: int) -> np.ndarray:
    """按真实交易时段滚动，13:00 不继承上午窗口。"""
    result = np.zeros(len(values), dtype=float)
    for start, end in ((0, flow.LUNCH_OPEN), (flow.LUNCH_OPEN, len(values))):
        segment = np.asarray(values[start:end], dtype=float)
        cumulative = np.cumsum(segment)
        rolled = cumulative.copy()
        if len(segment) > window:
            rolled[window:] = cumulative[window:] - cumulative[:-window]
        result[start:end] = rolled
    return result


def prior_mean(values: np.ndarray, lookback: int = 4) -> np.ndarray:
    """当前分钟之前最多 lookback 分钟的均值，午休处重置。"""
    result = np.zeros(len(values), dtype=float)
    for start, end in ((0, flow.LUNCH_OPEN), (flow.LUNCH_OPEN, len(values))):
        for index in range(start, end):
            left = max(start, index - lookback)
            if index > left:
                result[index] = float(np.mean(values[left:index]))
    return result


def window_arrays(record: dict) -> Dict[int, dict]:
    result = {}
    for window in WINDOWS:
        buy = rolling_sum(record["bb"], window)
        sell = rolling_sum(record["bs"], window)
        result[window] = {
            "buy": buy,
            "sell": sell,
            "net": buy - sell,
        }
    return result


def causal_scale(history: deque, threshold: float) -> Optional[float]:
    if len(history) < MIN_CALIB_DAYS:
        return None
    values = np.concatenate(list(history)) if history else np.asarray([], dtype=float)
    values = values[np.isfinite(values)]
    if not len(values):
        return None
    return max(float(threshold), float(np.median(values)))


def future_extreme(prices: np.ndarray, index: int, horizon: Optional[int], fn) -> Optional[float]:
    end = len(prices) if horizon is None else min(len(prices), index + horizon + 1)
    values = prices[index + 1:end]
    values = values[np.isfinite(values)]
    return float(fn(values)) if len(values) else None


def make_event(
    model: str,
    code: str,
    day: str,
    index: int,
    base: dict,
    feature: daily.DailyFeature,
    prev_close: Optional[float],
    net: float,
    buy: float,
    sell: float,
    threshold: float,
    scale: float,
) -> dict:
    prices = base["p"]
    price = float(prices[index])
    result = {
        "model": model,
        "code": code,
        "day": day,
        "index": int(index),
        "minute": flow.GRID[index],
        "price": price,
        "day_change": price / prev_close - 1.0 if prev_close else None,
        "pos20": feature.pos20,
        "extension_atr": feature.extension_atr,
        "structure": feature.structure,
        "amount_mult": net / threshold if threshold > 0 else None,
        "strength_mult": net / scale if scale > 0 else None,
        "buy_ratio": buy / sell if sell > 0 else None,
    }
    for horizon in (5, 15, 30, 60):
        value = base["ret"][horizon][index]
        result[f"r{horizon}"] = float(value) if np.isfinite(value) else None
    eod = base["ret"]["eod"][index]
    result["eod"] = float(eod) if np.isfinite(eod) else None

    high60 = future_extreme(prices, index, 60, np.max)
    low60 = future_extreme(prices, index, 60, np.min)
    high_eod = future_extreme(prices, index, None, np.max)
    result["mfe60"] = high60 / price - 1.0 if high60 is not None else None
    result["mae60"] = low60 / price - 1.0 if low60 is not None else None
    result["mfe_eod"] = high_eod / price - 1.0 if high_eod is not None else None
    return result


def values(rows: Sequence[dict], key: str) -> np.ndarray:
    return np.asarray([
        float(row[key]) for row in rows
        if row.get(key) is not None and np.isfinite(row[key])
    ], dtype=float)


def summarize(rows: Sequence[dict]) -> Optional[dict]:
    base = daily.stats(rows)
    if not base:
        return None
    for horizon in (5, 15, 30, 60):
        sample = values(rows, f"r{horizon}")
        base[f"r{horizon}_mean"] = float(sample.mean()) if len(sample) else None
        base[f"r{horizon}_hit"] = float((sample > 0).mean()) if len(sample) else None
    indices = values(rows, "index")
    base["median_index"] = float(np.median(indices)) if len(indices) else None
    return base


def print_summary(label: str, result: Optional[dict]) -> None:
    if not result:
        print(f"  {label:<28} 无样本")
        return
    print(
        f"  {label:<28} N={result['n']:4d} 股={result['stocks']:2d} 天={result['days']:2d} "
        f"5m={daily.pct(result['r5_mean'])} 15m={daily.pct(result['r15_mean'])} "
        f"30m={daily.pct(result['r30_mean'])} 60m={daily.pct(result['r60_mean'])} "
        f"EOD={daily.pct(result['eod_mean'])} 成本后={daily.pct(result['eod_after_cost'])} "
        f"日均={daily.pct(result['day_mean'])} "
        f"CI=[{daily.pct(result['day_ci95'][0])},{daily.pct(result['day_ci95'][1])}] "
        f"MFE60={daily.pct(result['mfe60_median'])} >=5%={result['mfe_eod_ge5'] * 100:4.1f}%"
    )


def subset(rows: Sequence[dict], mode: str) -> List[dict]:
    if mode == "all":
        return list(rows)
    if mode == "hot_momentum":
        return [
            row for row in rows
            if row.get("day_change") is not None and row["day_change"] >= 0.03
            and row["extension_atr"] < 1.0
        ]
    raise ValueError(mode)


def build_universe(conn, args, days: Sequence[str]):
    if args.universe == "all":
        return None, []
    rows = daily.load_hot_ai_semiconductor_universe(
        conn, days[0], days[-1], max(1, args.universe_limit),
    )
    return {row["code"] for row in rows}, rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=flow.DEFAULT_DB)
    parser.add_argument("--universe", choices=("all", "hot-ai-semiconductor"),
                        default="hot-ai-semiconductor")
    parser.add_argument("--universe-limit", type=int, default=30)
    parser.add_argument("--json", default="")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db, uri=True)
    conn.execute("PRAGMA query_only=ON")
    days, dropped = flow.full_days(conn)
    allowed, universe_rows = build_universe(conn, args, days)
    bars = daily.load_daily_bars(conn)
    next_close = daily.build_next_close(bars)
    previous_close = {
        (code, rows[index].day): rows[index - 1].close
        for code, rows in bars.items()
        for index in range(1, len(rows))
    }

    scale_history = defaultdict(lambda: deque(maxlen=CALIB_DAYS))
    events: Dict[str, List[dict]] = defaultdict(list)
    skipped_daily = 0
    for day in days:
        records = flow.load_day(conn, day)
        for code, record in records.items():
            if allowed is not None and code not in allowed:
                continue
            base = flow.derive(record, code, day, next_close)
            threshold = float(record.get("thr") or 0.0)
            if base is None or threshold <= 0:
                continue
            windows = window_arrays(record)
            active = (record["cb"] + record["cs"]) > 0
            scales = {
                window: causal_scale(scale_history[(code, window)], threshold)
                for window in WINDOWS
            }
            strict = {}
            for window in WINDOWS:
                item = windows[window]
                scale = scales[window]
                strict[window] = (
                    (item["net"] >= 3.0 * threshold)
                    & (item["buy"] >= 3.0 * item["sell"])
                    & (record["cb"] > 0)
                    & ((item["net"] >= scale) if scale is not None else False)
                    & np.isfinite(base["p"])
                )

            masks = {f"W{window}": strict[window] for window in WINDOWS}
            one_net = windows[1]["net"]
            prior4 = prior_mean(record["bb"] - record["bs"])
            scale1 = scales[1]
            scale5 = scales[5]
            one_acceleration = (
                (one_net >= scale1 if scale1 is not None else False)
                & (one_net >= 2.0 * np.maximum(prior4, 0.0))
                & (record["cb"] > 0)
            )
            five_persistent = (
                (windows[5]["net"] >= scale5 if scale5 is not None else False)
                & (windows[5]["buy"] >= 2.0 * windows[5]["sell"])
            )
            fifteen_aligned = (
                (windows[15]["net"] > 0)
                & (windows[15]["buy"] >= windows[15]["sell"])
            )
            masks["MTF_1加速_5持续_15同向"] = (
                one_acceleration & five_persistent & fifteen_aligned & np.isfinite(base["p"])
            )
            masks["MTF_1触发_5确认_15背景"] = (
                strict[1] & (windows[5]["net"] > 0) & (windows[15]["net"] > 0)
            )
            masks["MTF_5触发_1加速_15背景"] = (
                strict[5] & (windows[1]["net"] > 0) & (windows[15]["net"] > 0)
            )
            masks["MTF_15触发_5持续_1加速"] = (
                strict[15] & (windows[5]["net"] > 0) & (windows[1]["net"] > 0)
            )

            for model in MODEL_ORDER:
                indices = np.where(masks[model])[0]
                if not len(indices):
                    continue
                index = int(indices[0])
                price = float(base["p"][index])
                feature = daily.daily_feature(code, day, price, bars)
                if feature is None:
                    skipped_daily += 1
                    continue
                anchor = MODEL_ANCHOR[model]
                item = windows[anchor]
                events[model].append(make_event(
                    model, code, day, index, base, feature,
                    previous_close.get((code, day)),
                    float(item["net"][index]), float(item["buy"][index]),
                    float(item["sell"][index]), threshold, float(scales[anchor]),
                ))

            for window in WINDOWS:
                sample = np.abs(windows[window]["net"][active])
                sample = sample[np.isfinite(sample)]
                if len(sample):
                    scale_history[(code, window)].append(sample)

    evaluation_days = days[MIN_CALIB_DAYS:]
    split = max(1, len(evaluation_days) - 5)
    train_days = set(evaluation_days[:split])
    test_days = set(evaluation_days[split:])
    print("【资金流窗口重回测】")
    print(f"完整日: {len(days)} ({days[0]}~{days[-1]})，因果标定后评估日: {len(evaluation_days)}")
    print(f"剔除日: {dropped}")
    print(f"股票池: {args.universe} {len(universe_rows) if universe_rows else '全部'}")
    print("口径: 3×大单门槛 + 买额>=3×卖额 + 各窗口前5日力度基准；每股每日首次；成本0.25%")
    print(f"日线不足跳过: {skipped_daily}")

    output = {
        "days": days,
        "evaluation_days": evaluation_days,
        "dropped": dropped,
        "universe": universe_rows,
        "models": {},
        "timing_vs_w15": {},
    }
    for mode, title in (("all", "全部热门池"), ("hot_momentum", "热门动量：涨>=3%且延伸<1ATR")):
        print(f"\n{'=' * 100}\n{title}")
        for model in MODEL_ORDER:
            rows = subset(events[model], mode)
            result = summarize(rows)
            print_summary(model, result)
            train = summarize([row for row in rows if row["day"] in train_days])
            test = summarize([row for row in rows if row["day"] in test_days])
            output["models"].setdefault(model, {})[mode] = {
                "overall": result,
                "train": train,
                "test": test,
            }

    w15_map = {(row["day"], row["code"]): row for row in events["W15"]}
    print(f"\n{'=' * 100}\n与W15共同触发时的领先分钟")
    for model in MODEL_ORDER:
        if model == "W15":
            continue
        deltas = [
            row["index"] - w15_map[(row["day"], row["code"])]["index"]
            for row in events[model]
            if (row["day"], row["code"]) in w15_map
        ]
        timing = {
            "overlap": len(deltas),
            "median_delta_min": float(np.median(deltas)) if deltas else None,
        }
        output["timing_vs_w15"][model] = timing
        if deltas:
            print(f"  {model:<28} 重合={len(deltas):3d} 相对W15中位={np.median(deltas):+.1f}分钟")

    if args.json:
        Path(args.json).write_text(
            json.dumps(output, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"\nJSON -> {args.json}")


if __name__ == "__main__":
    main()
