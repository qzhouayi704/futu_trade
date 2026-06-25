#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按股标定「大单门槛」+「力度基准」（CapitalThresholdCalibrator）

回答"多少金额才算大单"——必须**按每只股自适应**：MINIMAX(日均成交27亿)单笔
50-100万是噪声(每日上百笔)，而翼菲(日均0.4亿)单笔最大才84万。固定门槛行不通
(同一100万：MINIMAX 136笔/日=噪声、翼菲 0笔/日=全瞎)。

标定口径(用户已拍板·中档)：
- **大单门槛** = 让"单笔主动买 ≥ 门槛"≈ TARGET_COUNT(默认20) 次/日 的那个成交额。
  实现：取该股近 CALIB_DAYS 个活跃日，每日取**第 TARGET_COUNT 大的主动买单额**，跨日中位；
  地板 ABS_FLOOR。实测得 MINIMAX≈300万 / 腾讯≈850万 / 翼菲≈15万，与生产数据吻合。
- **力度基准 window_net_scale** = 该股 15min 滚动窗口大单净流入绝对值的中位(跨日)。
  供 detector 算"力度 = 当前窗口净流入 ÷ 该尺度 = 这波是平时的 X 倍"。

写入 `market_baselines`(复用现表)，metric_key：
- `big_order_threshold`：p50=大单门槛、p90=超大单门槛(=门槛×SUPER_MULT)、sample_count=可用日数。
- `window_net_scale`：p50=力度基准。

只读 ticker_data/kline_data，只写 market_baselines。盘后批 + 启动各跑一次(见 baseline_updater)。
冷启动(无 ticker 历史)由 `cold_start_threshold` 用 kline 日均成交额代理。
"""

from __future__ import annotations

import logging
import os
import statistics
from collections import deque
from typing import List, Optional, Tuple

logger = logging.getLogger("baseline")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# ── 标定参数（全部可经环境变量覆盖）────────────────────────────
TARGET_COUNT = _env_int("CAPITAL_BIG_ORDER_TARGET_PER_DAY", 20)   # 目标日频 ~20 次/日(中档)
ABS_FLOOR = _env_float("CAPITAL_BIG_ORDER_FLOOR", 100_000.0)       # 大单门槛绝对地板(治小票)
SUPER_MULT = _env_float("CAPITAL_SUPER_MULT", 3.0)                 # 超大单 = 大单门槛 × 此值
COLD_COEF = _env_float("CAPITAL_COLD_COEF", 0.0012)               # 冷启动代理: 系数 × 日均成交额
CALIB_DAYS = _env_int("CAPITAL_CALIB_DAYS", 5)                     # 标定用近 N 个活跃日
MIN_CALIB_DAYS = _env_int("CAPITAL_MIN_CALIB_DAYS", 3)            # 至少 N 日才信任标定值
WINDOW_SEC = _env_int("CAPITAL_TICK_WINDOW_SEC", 900)             # 力度窗口(与累加器同口径) 15min
_MIN_DAY_ROWS = _env_int("CAPITAL_CALIB_MIN_DAY_ROWS", 200)        # 活跃日最少逐笔行数

_BUY_SQL = "UPPER(direction) IN ('BUY','BULL')"


def _percentile(sorted_vals: List[float], q: float) -> float:
    """线性插值分位（q∈[0,1]），sorted_vals 已升序。"""
    if not sorted_vals:
        return 0.0
    n = len(sorted_vals)
    idx = q * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def cold_start_threshold(db, code: str) -> float:
    """冷启动门槛代理：COLD_COEF × 近20日日均成交额，地板 ABS_FLOOR。

    无 ticker 历史时用日线(kline_data.turnover)估算。MINIMAX 27亿×0.0012≈324万≈实测；
    翼菲 0.4亿×0.0012≈4.8万 被 ABS_FLOOR 抬到 10万。
    """
    try:
        if db:
            rows = db.execute_query(
                "SELECT turnover FROM kline_data WHERE stock_code=? AND turnover>0 "
                "ORDER BY time_key DESC LIMIT 20", (code,))
            vals = [float(r[0]) for r in (rows or []) if r and r[0]]
            if vals:
                avg = sum(vals) / len(vals)
                return max(ABS_FLOOR, COLD_COEF * avg)
    except Exception as e:
        logger.debug(f"冷启动门槛代理失败 {code}: {e}")
    return ABS_FLOOR


class CapitalThresholdCalibrator:
    """按股标定大单门槛 + 力度基准，写入 market_baselines。只读 ticker/kline。"""

    def __init__(self, db_manager):
        self._db = db_manager

    def calibrate(self, stock_code: str, window_days: int = 20) -> bool:
        """标定一只股票并落库。Returns 是否成功写入大单门槛。"""
        if not self._db:
            return False
        days = self._recent_active_days(stock_code, CALIB_DAYS)
        if not days:
            return False
        thr_res = self._calibrate_threshold(stock_code, days)
        if not thr_res:
            return False
        threshold, n_days = thr_res
        scale = self._calibrate_window_scale(stock_code, days, threshold) or threshold
        ok = self._save(stock_code, "big_order_threshold", window_days,
                        threshold, threshold * SUPER_MULT, n_days)
        self._save(stock_code, "window_net_scale", window_days, scale, scale, n_days)
        return ok

    # ── 内部 ────────────────────────────────────────────
    def _recent_active_days(self, code: str, k: int) -> List[str]:
        try:
            rows = self._db.execute_query(
                "SELECT trade_date FROM ticker_data WHERE stock_code=? "
                "GROUP BY trade_date HAVING COUNT(*) >= ? "
                "ORDER BY trade_date DESC LIMIT ?", (code, _MIN_DAY_ROWS, k))
            return [r[0] for r in (rows or []) if r and r[0]]
        except Exception as e:
            logger.debug(f"取活跃日失败 {code}: {e}")
            return []

    def _calibrate_threshold(self, code: str, days: List[str]) -> Optional[Tuple[float, int]]:
        """每日取第 TARGET_COUNT 大的主动买单额，跨日中位，地板 ABS_FLOOR。

        只取每日 TopK(LIMIT TARGET_COUNT+2)，不拉全量逐笔——轻量。
        """
        daily: List[float] = []
        for d in days:
            try:
                rows = self._db.execute_query(
                    f"SELECT turnover FROM ticker_data WHERE stock_code=? AND trade_date=? "
                    f"AND {_BUY_SQL} AND turnover>0 ORDER BY turnover DESC LIMIT ?",
                    (code, d, TARGET_COUNT + 2))
                if rows and len(rows) >= TARGET_COUNT:
                    daily.append(float(rows[TARGET_COUNT - 1][0]))  # 第 TARGET_COUNT 大
            except Exception as e:
                logger.debug(f"标定门槛取数失败 {code}/{d}: {e}")
        if not daily:
            return None
        return max(statistics.median(daily), ABS_FLOOR), len(daily)

    def _calibrate_window_scale(self, code: str, days: List[str],
                                threshold: float) -> Optional[float]:
        """力度基准 = 15min 滚动窗口大单净流入绝对值的中位(跨日)。

        按分钟聚合大单(turnover≥门槛)净额(~240行/日)再做 15min 滚动，避免拉全量逐笔。
        """
        win_min = max(1, WINDOW_SEC // 60)
        swings: List[float] = []
        for d in days:
            try:
                rows = self._db.execute_query(
                    "SELECT CAST(timestamp/60000 AS INTEGER) AS m, "
                    "SUM(CASE WHEN UPPER(direction) IN ('BUY','BULL') THEN turnover "
                    "WHEN UPPER(direction) IN ('SELL','BEAR') THEN -turnover ELSE 0 END) "
                    "FROM ticker_data WHERE stock_code=? AND trade_date=? AND turnover>=? "
                    "GROUP BY m ORDER BY m", (code, d, threshold))
            except Exception as e:
                logger.debug(f"标定力度基准取数失败 {code}/{d}: {e}")
                continue
            dq: deque = deque()
            running = 0.0
            for r in (rows or []):
                if r is None or r[0] is None:
                    continue
                m, net = int(r[0]), float(r[1] or 0)
                dq.append((m, net))
                running += net
                while dq and dq[0][0] <= m - win_min:
                    running -= dq.popleft()[1]
                swings.append(abs(running))
        if not swings:
            return None
        swings.sort()
        return max(_percentile(swings, 0.5), threshold)

    def _save(self, code: str, metric_key: str, window_days: int,
              p50: float, p90: float, n: int) -> bool:
        try:
            from datetime import datetime
            self._db.execute_update("""
                INSERT OR REPLACE INTO market_baselines
                (stock_code, metric_key, window_days, mean, stddev,
                 p25, p50, p75, p90, sample_count, computed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (code, metric_key, window_days, p50, 0.0,
                  p50, p50, p50, p90, n, datetime.now().isoformat()))
            return True
        except Exception as e:
            logger.warning(f"保存资金基准失败 {code}/{metric_key}: {e}")
            return False
