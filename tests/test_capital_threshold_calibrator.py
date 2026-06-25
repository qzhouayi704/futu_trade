#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CapitalThresholdCalibrator + BaselineService.get_capital_tiers 单测 —— 内存 sqlite。

覆盖：标定门槛使"≥门槛 BUY 笔数≈TARGET"、力度基准落库、冷启动代理 + 地板、
get_capital_tiers 标定/冷启动两路。
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import simple_trade.services.baseline.capital_threshold_calibrator as C  # noqa: E402
from simple_trade.services.baseline.capital_threshold_calibrator import (  # noqa: E402
    CapitalThresholdCalibrator, cold_start_threshold,
)
from simple_trade.services.baseline.baseline_service import BaselineService  # noqa: E402


class FakeDB:
    """最小 db_manager：execute_query/execute_update 走单个内存连接。"""

    def __init__(self):
        self.con = sqlite3.connect(":memory:")
        self.con.execute("""CREATE TABLE ticker_data (
            stock_code TEXT, trade_date TEXT, price REAL, turnover REAL,
            direction TEXT, timestamp INTEGER)""")
        self.con.execute("""CREATE TABLE kline_data (
            stock_code TEXT, time_key TEXT, turnover REAL)""")
        self.con.execute("""CREATE TABLE market_baselines (
            id INTEGER PRIMARY KEY AUTOINCREMENT, stock_code TEXT, metric_key TEXT,
            window_days INTEGER, mean REAL, stddev REAL, p25 REAL, p50 REAL, p75 REAL,
            p90 REAL, sample_count INTEGER DEFAULT 0, computed_at TEXT,
            UNIQUE(stock_code, metric_key, window_days))""")
        self.con.commit()

    def execute_query(self, sql, params=()):
        return self.con.execute(sql, params).fetchall()

    def execute_update(self, sql, params=()):
        self.con.execute(sql, params)
        self.con.commit()


def _seed_ticks(db, code, days, n_per_day=60):
    """每日 n_per_day 笔主动买，turnover = (1..n)×1万 → 第 k 大 = (n-k+1)×1万。"""
    base = 1_700_000_000_000
    for di, d in enumerate(days):
        for j in range(1, n_per_day + 1):
            ts = base + di * 86_400_000 + j * 1000
            db.execute_update(
                "INSERT INTO ticker_data VALUES (?,?,?,?,?,?)",
                (code, d, 10.0, j * 10_000.0, "BUY", ts))
        # 少量卖单（力度基准用）
        for j in range(1, 11):
            ts = base + di * 86_400_000 + 30_000 + j * 1000
            db.execute_update(
                "INSERT INTO ticker_data VALUES (?,?,?,?,?,?)",
                (code, d, 10.0, j * 10_000.0, "SELL", ts))


def _setup():
    # 测试用低活跃日门槛 + 固定 TARGET，避免依赖生产默认
    C._MIN_DAY_ROWS = 50
    C.TARGET_COUNT = 20
    C.ABS_FLOOR = 100_000.0
    C.SUPER_MULT = 3.0
    C.MIN_CALIB_DAYS = 3


# ---------- 1. 门槛标定：第 TARGET 大跨日中位 ----------
def test_threshold_calibration():
    _setup()
    db = FakeDB()
    days = ["2026-06-18", "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25"]
    _seed_ticks(db, "HK.00100", days, n_per_day=60)
    cal = CapitalThresholdCalibrator(db)
    assert cal.calibrate("HK.00100") is True
    rows = db.execute_query(
        "SELECT p50, p90, sample_count FROM market_baselines "
        "WHERE stock_code=? AND metric_key='big_order_threshold' AND window_days=20",
        ("HK.00100",))
    assert rows, "未写入 big_order_threshold"
    p50, p90, n = rows[0]
    # 第20大 = (60-20+1)×1万 = 41万；5 日同分布 → 中位 41万
    assert abs(p50 - 410_000) < 1.0
    assert abs(p90 - 410_000 * 3) < 1.0    # 超大单 = 门槛×SUPER_MULT
    assert n == 5
    # 力度基准也落库且 ≥ 门槛(地板)
    srows = db.execute_query(
        "SELECT p50 FROM market_baselines WHERE stock_code=? AND metric_key='window_net_scale'",
        ("HK.00100",))
    assert srows and srows[0][0] >= 410_000


# ---------- 2. 门槛达到目标日频：≥门槛的 BUY 笔数≈TARGET ----------
def test_threshold_hits_target_count():
    _setup()
    db = FakeDB()
    days = ["2026-06-22", "2026-06-23", "2026-06-24"]
    _seed_ticks(db, "HK.00100", days, n_per_day=60)
    cal = CapitalThresholdCalibrator(db)
    cal.calibrate("HK.00100")
    thr = db.execute_query(
        "SELECT p50 FROM market_baselines WHERE stock_code=? AND metric_key='big_order_threshold'",
        ("HK.00100",))[0][0]
    cnt = db.execute_query(
        "SELECT COUNT(*) FROM ticker_data WHERE stock_code=? AND trade_date=? "
        "AND UPPER(direction) IN ('BUY','BULL') AND turnover>=?",
        ("HK.00100", "2026-06-24", thr))[0][0]
    assert cnt == 20      # 恰好 TARGET 笔 ≥ 门槛


# ---------- 3. 冷启动代理 + 地板 ----------
def test_cold_start_proxy_and_floor():
    _setup()
    C.COLD_COEF = 0.0012
    db = FakeDB()
    # MINIMAX：日均成交 27 亿 → 0.0012×2.7e9 = 324万
    for i in range(20):
        db.execute_update("INSERT INTO kline_data VALUES (?,?,?)",
                          ("HK.00100", f"2026-06-{i+1:02d}", 2_700_000_000.0))
    assert abs(cold_start_threshold(db, "HK.00100") - 3_240_000) < 1.0
    # 翼菲：日均 0.4 亿 → 0.0012×4.141e7≈4.97万 < 地板 → 抬到 10万
    for i in range(20):
        db.execute_update("INSERT INTO kline_data VALUES (?,?,?)",
                          ("HK.06871", f"2026-06-{i+1:02d}", 41_410_000.0))
    assert cold_start_threshold(db, "HK.06871") == 100_000.0
    # 无 kline → 地板
    assert cold_start_threshold(db, "HK.99999") == 100_000.0


# ---------- 4. get_capital_tiers：标定/冷启动两路 ----------
def test_get_capital_tiers():
    _setup()
    C.COLD_COEF = 0.0012
    db = FakeDB()
    days = ["2026-06-18", "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25"]
    _seed_ticks(db, "HK.00100", days, n_per_day=60)
    CapitalThresholdCalibrator(db).calibrate("HK.00100")
    bs = BaselineService(db)
    large, sup, scale = bs.get_capital_tiers("HK.00100")
    assert abs(large - 410_000) < 1.0        # 用标定值
    assert abs(sup - 410_000 * 3) < 1.0
    assert scale >= 410_000
    # 未标定股 → 冷启动代理（kline）
    for i in range(20):
        db.execute_update("INSERT INTO kline_data VALUES (?,?,?)",
                          ("HK.00700", f"2026-06-{i+1:02d}", 8_357_770_000.0))
    large2, sup2, scale2 = bs.get_capital_tiers("HK.00700")
    assert abs(large2 - 0.0012 * 8_357_770_000.0) < 1.0   # 腾讯日均83.6亿 → ≈1003万
    assert sup2 == large2 * 3 and scale2 == large2


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
