#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日线位置对资金流买入信号的增益回测。

数据口径：
* 复用 ``big_order_flow_eval`` 的 15 分钟逐笔资金流事件重建。
* 日线特征只使用信号日之前已经完成的 K 线；事件价格来自当时分钟价。
* 每股每天每个事件族只取首次触发，减少盘中重复信号造成的样本聚类。
* 收益同时报告事件均值、按交易日等权均值和按交易日聚类 bootstrap CI。

生产服务器只读运行：
    .venv/bin/python scripts/analysis/daily_position_flow_backtest.py \
        --db 'file:/data/futu_trade_data/trade.db?mode=ro' \
        --json /tmp/daily_position_flow.json
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import sqlite3
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import big_order_flow_eval as flow  # noqa: E402


SEED = 20260713
ROUND_TRIP_COST = 0.0025
FAMILIES = ("DIV_BUY", "IN3_prod", "SUP_IN_1")
CONFIRM_MODES = ("5分钟转强", "突破前5分钟高点", "回踩不破后收复")
SCREENSHOT_CODES = (
    "HK.02513",  # 智谱
    "HK.00465",  # 富通科技
    "HK.01879",  # 曦智科技-P
    "HK.01888",  # 建滔积层板
    "HK.01347",  # 华虹半导体
    "HK.02665",  # 图达通
    "HK.02577",  # 英诺赛科
    "HK.02476",  # 胜宏科技
)


@dataclass(frozen=True)
class DailyBar:
    day: str
    open: float
    high: float
    low: float
    close: float
    turnover: float


@dataclass(frozen=True)
class DailyFeature:
    pos20: float
    pos60: float
    ma5: float
    ma10: float
    ma20: float
    ma20_slope5: float
    atr20: float
    extension_atr: float
    prev_ret: float
    trend: str
    structure: str


def _finite(value) -> Optional[float]:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def load_daily_bars(conn) -> Dict[str, List[DailyBar]]:
    """按股票加载日线；同股同日有重复快照时保留最后一条。"""
    latest: Dict[tuple, DailyBar] = {}
    rows = conn.execute(
        "SELECT stock_code, substr(time_key,1,10), open_price, high_price, "
        "low_price, close_price, turnover FROM kline_data "
        "WHERE time_key >= '2025-12-01' "
        "ORDER BY stock_code, time_key, id"
    )
    for code, day, op, hi, lo, cl, turn in rows:
        values = [_finite(v) for v in (op, hi, lo, cl)]
        if not code or not day or any(v is None or v <= 0 for v in values):
            continue
        latest[(str(code), str(day))] = DailyBar(
            day=str(day), open=values[0], high=values[1], low=values[2],
            close=values[3], turnover=float(turn or 0.0),
        )

    result: Dict[str, List[DailyBar]] = defaultdict(list)
    for (code, _day), bar in latest.items():
        result[code].append(bar)
    for rows_ in result.values():
        rows_.sort(key=lambda item: item.day)
    return dict(result)


def build_next_close(bars: Dict[str, List[DailyBar]]) -> Dict[tuple, float]:
    result = {}
    for code, rows in bars.items():
        for index in range(len(rows) - 1):
            result[(code, rows[index].day)] = rows[index + 1].close
    return result


def load_hot_ai_semiconductor_universe(
    conn: sqlite3.Connection,
    start_day: str,
    end_day: str,
    limit: int,
) -> List[dict]:
    """按回测期逐笔分钟成交额选取港股 AI/半导体热门标的。"""
    rows = conn.execute(
        "WITH target AS ("
        "  SELECT DISTINCT s.code, s.name FROM stocks s "
        "  JOIN stock_plates sp ON sp.stock_id=s.id "
        "  JOIN plates p ON p.id=sp.plate_id "
        "  WHERE p.market='HK' AND ("
        "    p.category IN ('AI','芯片') OR "
        "    p.plate_name IN ('人工智能','半导体','半导体设备与材料','AI次新股')"
        "  )"
        "), liquidity AS ("
        "  SELECT stock_code, COUNT(DISTINCT trade_date) AS data_days, "
        "         SUM(COALESCE(buy_amt,0)+COALESCE(sell_amt,0)) AS amount "
        "  FROM ticker_minute WHERE trade_date BETWEEN ? AND ? GROUP BY stock_code"
        ") "
        "SELECT t.code, t.name, l.data_days, l.amount "
        "FROM target t JOIN liquidity l ON l.stock_code=t.code "
        "ORDER BY l.amount DESC LIMIT ?",
        (start_day, end_day, limit),
    ).fetchall()
    selected = {
        str(code): {
            "code": str(code),
            "name": str(name or ""),
            "data_days": int(data_days or 0),
            "amount": float(amount or 0.0),
            "source": "板块成交额Top",
        }
        for code, name, data_days, amount in rows
    }

    placeholders = ",".join("?" for _ in SCREENSHOT_CODES)
    forced_rows = conn.execute(
        f"SELECT s.code, s.name, COUNT(DISTINCT tm.trade_date), "
        f"SUM(COALESCE(tm.buy_amt,0)+COALESCE(tm.sell_amt,0)) "
        f"FROM stocks s JOIN ticker_minute tm ON tm.stock_code=s.code "
        f"WHERE s.code IN ({placeholders}) AND tm.trade_date BETWEEN ? AND ? "
        f"GROUP BY s.code, s.name",
        (*SCREENSHOT_CODES, start_day, end_day),
    ).fetchall()
    for code, name, data_days, amount in forced_rows:
        code = str(code)
        item = selected.setdefault(code, {
            "code": code,
            "name": str(name or ""),
            "data_days": int(data_days or 0),
            "amount": float(amount or 0.0),
            "source": "截图强制纳入",
        })
        if item["source"] != "截图强制纳入":
            item["source"] += "+截图"
    return sorted(selected.values(), key=lambda item: item["amount"], reverse=True)


def daily_feature(
    code: str,
    day: str,
    event_price: float,
    bars: Dict[str, List[DailyBar]],
) -> Optional[DailyFeature]:
    rows = bars.get(code)
    if not rows:
        return None
    days = [item.day for item in rows]
    end = bisect.bisect_left(days, day)
    hist = rows[:end]
    if len(hist) < 25:
        return None

    last20 = hist[-20:]
    closes = np.asarray([item.close for item in hist], dtype=float)
    hi20 = max(item.high for item in last20)
    lo20 = min(item.low for item in last20)
    pos20 = ((event_price - lo20) / (hi20 - lo20)) if hi20 > lo20 else 0.5

    if len(hist) >= 60:
        last60 = hist[-60:]
        hi60 = max(item.high for item in last60)
        lo60 = min(item.low for item in last60)
        pos60 = ((event_price - lo60) / (hi60 - lo60)) if hi60 > lo60 else 0.5
    else:
        pos60 = float("nan")

    ma5 = float(closes[-5:].mean())
    ma10 = float(closes[-10:].mean())
    ma20 = float(closes[-20:].mean())
    ma20_prev5 = float(closes[-25:-5].mean())
    slope5 = ma20 / ma20_prev5 - 1.0 if ma20_prev5 > 0 else 0.0

    true_ranges = []
    start = max(1, len(hist) - 20)
    for index in range(start, len(hist)):
        item = hist[index]
        prev_close = hist[index - 1].close
        true_ranges.append(max(
            item.high - item.low,
            abs(item.high - prev_close),
            abs(item.low - prev_close),
        ))
    atr20 = float(np.mean(true_ranges)) if true_ranges else 0.0
    extension = (event_price - ma20) / atr20 if atr20 > 0 else 0.0
    prev_ret = hist[-1].close / hist[-2].close - 1.0 if len(hist) >= 2 else 0.0

    if ma5 > ma10 > ma20 and slope5 > 0:
        trend = "多头上升"
    elif ma5 < ma10 < ma20 and slope5 < 0:
        trend = "空头下跌"
    elif ma5 > ma10 and slope5 <= 0:
        trend = "低位改善"
    elif ma5 < ma10 and slope5 >= 0:
        trend = "高位转弱"
    else:
        trend = "混合整理"

    if pos20 <= 0.20 and trend == "空头下跌":
        structure = "低位下跌中继"
    elif pos20 <= 0.45 and trend in ("低位改善", "多头上升", "混合整理"):
        structure = "低位企稳"
    elif 0.45 < pos20 < 0.85 and trend == "多头上升":
        structure = "中位上升"
    elif pos20 >= 0.90 and extension >= 2.0:
        structure = "高位过度延伸"
    elif pos20 >= 0.80 and trend == "多头上升":
        structure = "高位趋势突破"
    elif pos20 >= 0.80 and trend != "多头上升":
        structure = "高位转弱"
    else:
        structure = "中位整理"

    return DailyFeature(
        pos20=float(pos20), pos60=float(pos60), ma5=ma5, ma10=ma10,
        ma20=ma20, ma20_slope5=float(slope5), atr20=atr20,
        extension_atr=float(extension), prev_ret=float(prev_ret),
        trend=trend, structure=structure,
    )


def _future_extreme(prices: np.ndarray, index: int, horizon: Optional[int], fn) -> float:
    end = len(prices) if horizon is None else min(len(prices), index + horizon + 1)
    future = prices[index + 1:end]
    future = future[np.isfinite(future)]
    if not len(future):
        return float("nan")
    return float(fn(future))


def make_event(
    family: str,
    code: str,
    day: str,
    index: int,
    derived: dict,
    feature: DailyFeature,
    prev_close: Optional[float],
) -> dict:
    prices = derived["p"]
    price = float(prices[index])
    result = {
        "family": family,
        "code": code,
        "day": day,
        "index": int(index),
        "minute": flow.GRID[index],
        "price": price,
        "day_change": (price / prev_close - 1.0) if prev_close else None,
        **asdict(feature),
    }
    for horizon in (5, 15, 30, 60):
        value = derived["ret"][horizon][index]
        result[f"r{horizon}"] = float(value) if np.isfinite(value) else None
    for name in ("eod", "next"):
        value = derived["ret"][name][index]
        result[name] = float(value) if np.isfinite(value) else None

    for horizon in (30, 60):
        high = _future_extreme(prices, index, horizon, np.max)
        low = _future_extreme(prices, index, horizon, np.min)
        result[f"mfe{horizon}"] = high / price - 1.0 if np.isfinite(high) else None
        result[f"mae{horizon}"] = low / price - 1.0 if np.isfinite(low) else None
    high = _future_extreme(prices, index, None, np.max)
    low = _future_extreme(prices, index, None, np.min)
    result["mfe_eod"] = high / price - 1.0 if np.isfinite(high) else None
    result["mae_eod"] = low / price - 1.0 if np.isfinite(low) else None
    result["early"] = index <= flow.TOD_SPLIT1
    result["runner_candidate"] = bool(result["early"] and feature.prev_ret >= 0.03)
    return result


def confirmation_index(derived: dict, index: int, mode: str) -> Optional[int]:
    """在事件后15个交易分钟内寻找无未来函数的价格确认点。"""
    prices = derived["p"]
    end = min(len(prices) - 1, index + 15)
    if end <= index:
        return None
    event_price = float(prices[index])

    if mode == "5分钟转强":
        target = index + 5
        if target <= end and prices[target] > event_price and derived["Wbig"][target] > 0:
            return target
        return None

    if mode == "突破前5分钟高点":
        start = max(0, index - 5)
        history = prices[start:index + 1]
        history = history[np.isfinite(history)]
        if not len(history):
            return None
        trigger = float(np.max(history))
        for target in range(index + 1, end + 1):
            if prices[target] > trigger and derived["Wbig"][target] > 0:
                return target
        return None

    if mode == "回踩不破后收复":
        # 最多容忍事件价下方0.5%，至少观察3分钟；随后收回事价且资金窗口仍为正。
        floor = event_price * 0.995
        for target in range(index + 3, end + 1):
            path = prices[index + 1:target + 1]
            path = path[np.isfinite(path)]
            if not len(path) or float(np.min(path)) < floor:
                return None
            if prices[target] >= event_price and derived["Wbig"][target] > 0:
                return target
        return None
    raise ValueError(f"未知确认模式: {mode}")


def pos_bin(value: float) -> str:
    if not np.isfinite(value):
        return "无数据"
    if value < 0.10:
        return "<10%"
    if value < 0.30:
        return "10-30%"
    if value < 0.50:
        return "30-50%"
    if value < 0.70:
        return "50-70%"
    if value < 0.90:
        return "70-90%"
    return ">=90%"


def extension_bin(value: float) -> str:
    if value < -1.0:
        return "<-1ATR"
    if value < 0.0:
        return "-1~0ATR"
    if value < 1.0:
        return "0~1ATR"
    if value < 2.0:
        return "1~2ATR"
    return ">=2ATR"


def day_change_bin(value: Optional[float]) -> str:
    if value is None or not np.isfinite(value):
        return "无数据"
    if value < -0.03:
        return "<-3%"
    if value < 0.0:
        return "-3~0%"
    if value < 0.03:
        return "0~3%"
    if value < 0.06:
        return "3~6%"
    return ">=6%"


def _array(rows: Sequence[dict], key: str) -> np.ndarray:
    values = [row.get(key) for row in rows]
    return np.asarray([float(value) for value in values if value is not None and np.isfinite(value)], dtype=float)


def stats(rows: Sequence[dict]) -> Optional[dict]:
    eod = _array(rows, "eod")
    if not len(eod):
        return None
    by_day: Dict[str, List[float]] = defaultdict(list)
    for row in rows:
        value = row.get("eod")
        if value is not None and np.isfinite(value):
            by_day[row["day"]].append(float(value))
    day_means = np.asarray([np.mean(values) for values in by_day.values()], dtype=float)
    rng = np.random.default_rng(SEED + len(rows) + len(by_day))
    boots = []
    if len(day_means) >= 2:
        for _ in range(1000):
            boots.append(float(rng.choice(day_means, size=len(day_means), replace=True).mean()))
    ci = (float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))) if boots else (float("nan"), float("nan"))

    mfe60 = _array(rows, "mfe60")
    mfe_eod = _array(rows, "mfe_eod")
    mae60 = _array(rows, "mae60")
    next_ret = _array(rows, "next")
    return {
        "n": len(eod),
        "stocks": len({row["code"] for row in rows}),
        "days": len(by_day),
        "eod_mean": float(eod.mean()),
        "eod_median": float(np.median(eod)),
        "eod_hit": float((eod > 0).mean()),
        "eod_after_cost": float(eod.mean() - ROUND_TRIP_COST),
        "day_mean": float(day_means.mean()),
        "positive_days": float((day_means > 0).mean()),
        "day_ci95": ci,
        "next_mean": float(next_ret.mean()) if len(next_ret) else None,
        "mfe60_median": float(np.median(mfe60)) if len(mfe60) else None,
        "mae60_median": float(np.median(mae60)) if len(mae60) else None,
        "mfe_eod_ge3": float((mfe_eod >= 0.03).mean()) if len(mfe_eod) else None,
        "mfe_eod_ge5": float((mfe_eod >= 0.05).mean()) if len(mfe_eod) else None,
    }


def pct(value: Optional[float], digits: int = 2) -> str:
    if value is None or not np.isfinite(value):
        return "--"
    return f"{value * 100:+.{digits}f}%"


def print_stat(label: str, value: Optional[dict]) -> None:
    if not value:
        return
    print(
        f"  {label:<18} N={value['n']:4d} 股={value['stocks']:3d} 天={value['days']:2d} "
        f"EOD={pct(value['eod_mean'])} 中位={pct(value['eod_median'])} "
        f"命中={value['eod_hit'] * 100:4.1f}% 成本后={pct(value['eod_after_cost'])} "
        f"逐日={pct(value['day_mean'])}[{pct(value['day_ci95'][0])},{pct(value['day_ci95'][1])}] "
        f"正日={value['positive_days'] * 100:4.1f}% MFE60={pct(value['mfe60_median'])} "
        f"到收盘>=3%={value['mfe_eod_ge3'] * 100:4.1f}% >=5%={value['mfe_eod_ge5'] * 100:4.1f}%"
    )


def group_report(
    title: str,
    rows: Sequence[dict],
    key: Callable[[dict], str],
    order: Optional[Iterable[str]] = None,
    min_n: int = 15,
) -> dict:
    print(f"\n[{title}]")
    grouped: Dict[str, List[dict]] = defaultdict(list)
    for row in rows:
        grouped[key(row)].append(row)
    labels = list(order or sorted(grouped))
    result = {}
    for label in labels:
        sample = grouped.get(label, [])
        if len(sample) < min_n:
            continue
        value = stats(sample)
        print_stat(label, value)
        result[label] = value
    return result


def candidate_report(rows: Sequence[dict]) -> dict:
    selectors = (
        ("20日低位<=30%", lambda row: row["pos20"] <= 0.30),
        ("20日低位<=50%", lambda row: row["pos20"] <= 0.50),
        ("低位企稳", lambda row: row["structure"] == "低位企稳"),
        ("低位下跌中继", lambda row: row["structure"] == "低位下跌中继"),
        ("中位上升", lambda row: row["structure"] == "中位上升"),
        ("高位趋势突破", lambda row: row["structure"] == "高位趋势突破"),
        ("高位过度延伸", lambda row: row["structure"] == "高位过度延伸"),
        ("延伸<1ATR", lambda row: row["extension_atr"] < 1.0),
        ("距MA20在-1~1ATR", lambda row: -1.0 <= row["extension_atr"] < 1.0),
        ("20日<=50%+延伸<1ATR", lambda row: row["pos20"] <= 0.50 and row["extension_atr"] < 1.0),
        ("当日涨幅<3%", lambda row: row.get("day_change") is not None and row["day_change"] < 0.03),
        ("20日<=50%+当日-3~3%", lambda row: row["pos20"] <= 0.50
         and row.get("day_change") is not None and -0.03 <= row["day_change"] < 0.03),
        ("当日涨幅>=3%", lambda row: row.get("day_change") is not None
         and row["day_change"] >= 0.03),
        ("当日>=3%+延伸<1ATR", lambda row: row.get("day_change") is not None
         and row["day_change"] >= 0.03 and row["extension_atr"] < 1.0),
        ("当日>=3%+20日<90%", lambda row: row.get("day_change") is not None
         and row["day_change"] >= 0.03 and row["pos20"] < 0.90),
        ("早盘+昨日涨>=3%", lambda row: bool(row["runner_candidate"])),
        ("早盘+昨日强+非过热", lambda row: bool(row["runner_candidate"]) and row["extension_atr"] < 2.0),
    )
    result = {}
    for label, selector in selectors:
        sample = [row for row in rows if selector(row)]
        if len(sample) < 15:
            continue
        value = stats(sample)
        print_stat(label, value)
        result[label] = value
    return result


def time_split_report(label: str, rows: Sequence[dict], days: Sequence[str]) -> dict:
    """以前10天/后5天做简单时序外推检查，防止全样本均值掩盖失效。"""
    split = max(1, len(days) - 5)
    train_days = set(days[:split])
    test_days = set(days[split:])
    train = [row for row in rows if row["day"] in train_days]
    test = [row for row in rows if row["day"] in test_days]
    train_stats = stats(train)
    test_stats = stats(test)
    print(f"\n[{label}]")
    print_stat(f"前{split}天", train_stats)
    print_stat(f"后{len(days) - split}天", test_stats)
    return {"train": train_stats, "test": test_stats}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=flow.DEFAULT_DB)
    parser.add_argument("--json", default="")
    parser.add_argument(
        "--universe", choices=("all", "hot-ai-semiconductor"), default="all",
        help="回测股票池；热门池按区间逐笔成交额排序，避免事后按涨幅选股",
    )
    parser.add_argument("--universe-limit", type=int, default=30)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db, uri=True)
    conn.execute("PRAGMA query_only=ON")
    days, dropped = flow.full_days(conn)
    universe = None
    universe_rows: List[dict] = []
    if args.universe == "hot-ai-semiconductor":
        universe_rows = load_hot_ai_semiconductor_universe(
            conn, days[0], days[-1], max(1, args.universe_limit),
        )
        universe = {row["code"] for row in universe_rows}
    bars = load_daily_bars(conn)
    next_close = build_next_close(bars)
    previous_close = {
        (code, rows[index].day): rows[index - 1].close
        for code, rows in bars.items()
        for index in range(1, len(rows))
    }

    events: Dict[str, List[dict]] = defaultdict(list)
    confirmed: Dict[str, List[dict]] = defaultdict(list)
    skipped_no_daily = 0
    for day in days:
        records = flow.load_day(conn, day)
        for code, record in records.items():
            if universe is not None and code not in universe:
                continue
            derived = flow.derive(record, code, day, next_close)
            if derived is None:
                continue
            fams = flow.families(derived)
            for family in FAMILIES:
                if family not in fams:
                    continue
                indices = flow.pick_events(fams[family][1])
                if not indices:
                    continue
                index = indices[0]
                price = float(derived["p"][index])
                feature = daily_feature(code, day, price, bars)
                if feature is None:
                    skipped_no_daily += 1
                    continue
                events[family].append(make_event(
                    family, code, day, index, derived, feature,
                    previous_close.get((code, day)),
                ))
                for mode in CONFIRM_MODES:
                    confirm_index = confirmation_index(derived, index, mode)
                    if confirm_index is None:
                        continue
                    confirm_price = float(derived["p"][confirm_index])
                    confirm_feature = daily_feature(code, day, confirm_price, bars)
                    if confirm_feature is None:
                        continue
                    item = make_event(
                        f"{family}@{mode}", code, day, confirm_index,
                        derived, confirm_feature, previous_close.get((code, day)),
                    )
                    item["origin_index"] = index
                    item["confirm_delay"] = confirm_index - index
                    confirmed[f"{family}@{mode}"].append(item)

    print("【日线位置 × 资金流买点回测】")
    print(f"完整分钟交易日: {len(days)} ({days[0]} ~ {days[-1]})")
    print(f"剔除日: {dropped}")
    print(f"日线股票: {len(bars)}，缺少足够日线的事件: {skipped_no_daily}")
    print(f"口径: 每股每天每族首次触发；往返成本假设 {ROUND_TRIP_COST * 100:.2f}%")
    if universe_rows:
        print(f"热门AI/半导体股票池: {len(universe_rows)} 只")
        for row in universe_rows:
            print(
                f"  {row['code']} {row['name']} 明细日={row['data_days']:2d} "
                f"成交额={row['amount'] / 1e8:8.2f}亿 来源={row['source']}"
            )

    output = {
        "days": days,
        "dropped": dropped,
        "universe": universe_rows,
        "families": {},
    }
    pos_order = ("<10%", "10-30%", "30-50%", "50-70%", "70-90%", ">=90%", "无数据")
    ext_order = ("<-1ATR", "-1~0ATR", "0~1ATR", "1~2ATR", ">=2ATR")
    day_change_order = ("<-3%", "-3~0%", "0~3%", "3~6%", ">=6%", "无数据")
    trend_order = ("空头下跌", "低位改善", "混合整理", "多头上升", "高位转弱")
    structure_order = (
        "低位下跌中继", "低位企稳", "中位整理", "中位上升",
        "高位趋势突破", "高位转弱", "高位过度延伸",
    )

    for family in FAMILIES:
        rows = events[family]
        print(f"\n{'=' * 80}\n{family} 样本 {len(rows)}")
        family_result = {"overall": stats(rows)}
        print_stat("全部", family_result["overall"])
        family_result["pos20"] = group_report(
            "20日区间位置", rows, lambda row: pos_bin(row["pos20"]), pos_order)
        family_result["pos60"] = group_report(
            "60日区间位置", rows, lambda row: pos_bin(row["pos60"]), pos_order)
        family_result["extension"] = group_report(
            "距离MA20的ATR延伸", rows,
            lambda row: extension_bin(row["extension_atr"]), ext_order)
        family_result["day_change"] = group_report(
            "信号触发时当日涨幅", rows,
            lambda row: day_change_bin(row.get("day_change")), day_change_order)
        family_result["trend"] = group_report(
            "日线均线趋势", rows, lambda row: row["trend"], trend_order)
        family_result["structure"] = group_report(
            "综合日线结构", rows, lambda row: row["structure"], structure_order)
        print("\n[候选组合]")
        family_result["candidates"] = candidate_report(rows)
        output["families"][family] = family_result

    print(f"\n{'#' * 80}\n价格确认后才入场（收益从确认价起算）")
    output["confirmed"] = {}
    for family in FAMILIES:
        print(f"\n{'=' * 80}\n{family} 价格确认")
        for mode in CONFIRM_MODES:
            key = f"{family}@{mode}"
            rows = confirmed[key]
            base_count = len(events[family])
            ratio = len(rows) / base_count if base_count else 0.0
            print(f"\n[{mode}] 确认 {len(rows)}/{base_count} ({ratio * 100:.1f}%)")
            value = stats(rows)
            print_stat("全部确认", value)
            candidate = candidate_report(rows)
            output["confirmed"][key] = {
                "confirm_rate": ratio,
                "overall": value,
                "candidates": candidate,
            }

    print(f"\n{'#' * 80}\n时序稳定性：前10天 vs 后5天")
    split_cases = {
        "DIV_BUY全部": events["DIV_BUY"],
        "DIV_BUY·20日<10%": [row for row in events["DIV_BUY"] if row["pos20"] < 0.10],
        "DIV_BUY·当日跌超3%": [row for row in events["DIV_BUY"]
                              if row.get("day_change") is not None and row["day_change"] < -0.03],
        "IN3全部": events["IN3_prod"],
        "IN3·低位企稳": [row for row in events["IN3_prod"] if row["structure"] == "低位企稳"],
        "IN3·当日涨>=3%": [
            row for row in events["IN3_prod"]
            if row.get("day_change") is not None and row["day_change"] >= 0.03
        ],
        "IN3·当日涨>=3%·延伸<1ATR": [
            row for row in events["IN3_prod"]
            if row.get("day_change") is not None and row["day_change"] >= 0.03
            and row["extension_atr"] < 1.0
        ],
        "IN3·延伸1ATR以上": [row for row in events["IN3_prod"] if row["extension_atr"] >= 1.0],
        "IN3·5分钟转强·低位企稳": [
            row for row in confirmed["IN3_prod@5分钟转强"]
            if row["structure"] == "低位企稳"
        ],
        "SUP_IN·高位过度延伸": [
            row for row in events["SUP_IN_1"] if row["structure"] == "高位过度延伸"
        ],
    }
    output["time_split"] = {}
    for label, rows in split_cases.items():
        output["time_split"][label] = time_split_report(label, rows, days)

    if args.json:
        Path(args.json).write_text(
            json.dumps(output, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"\nJSON -> {args.json}")


if __name__ == "__main__":
    main()
