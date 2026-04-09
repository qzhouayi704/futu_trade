#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K 线批量查询属性测试

使用 hypothesis 验证批量 K 线查询的核心正确性属性：
- Property 8: K 线批量查询等价性

**Validates: Requirements 5.1, 5.2**
"""

import os
import sqlite3
import sys
from datetime import datetime, timedelta

import pytest
from hypothesis import given, settings, strategies as st, assume

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.routers.data.enhanced_heat import _load_kline_data_batch


# ── MockDbManager ────────────────────────────────────────────────


class MockDbManager:
    """包装内存 SQLite 数据库，模拟 db_manager.execute_query 接口"""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def execute_query(self, sql, params=None):
        cursor = self.conn.cursor()
        cursor.execute(sql, params or ())
        return cursor.fetchall()


# ── hypothesis 策略 ──────────────────────────────────────────────

# 股票代码：港股 HK.XXXXX 或美股 US.XXXX 格式
stock_code_st = st.from_regex(r"(HK|US)\.\d{4,5}", fullmatch=True)

# 价格（正浮点数）
price_st = st.floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False)

# 成交量（正整数）
volume_st = st.integers(min_value=1, max_value=10**9)

# 成交额（正浮点数）
turnover_st = st.floats(min_value=0.01, max_value=1e12, allow_nan=False, allow_infinity=False)

# 最近 N 天内的日期字符串
recent_date_st = st.integers(min_value=0, max_value=25).map(
    lambda d: (datetime.now() - timedelta(days=d)).strftime("%Y-%m-%d")
)

# 单条 K 线记录
kline_record_st = st.fixed_dictionaries({
    "time_key": recent_date_st,
    "open_price": price_st,
    "close_price": price_st,
    "high_price": price_st,
    "low_price": price_st,
    "volume": volume_st,
    "turnover": turnover_st,
})

# 单只股票的 K 线数据（1-5 条记录）
stock_kline_st = st.lists(kline_record_st, min_size=1, max_size=5)

# 股票代码到 K 线数据的映射（1-10 只股票）
kline_dataset_st = st.dictionaries(
    keys=stock_code_st,
    values=stock_kline_st,
    min_size=1,
    max_size=10,
)


# ── 辅助函数 ─────────────────────────────────────────────────────


def _create_kline_table(conn: sqlite3.Connection):
    """在内存数据库中创建 kline_data 表"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kline_data (
            stock_code TEXT NOT NULL,
            time_key TEXT NOT NULL,
            open_price REAL,
            close_price REAL,
            high_price REAL,
            low_price REAL,
            volume INTEGER,
            turnover REAL
        )
    """)


def _insert_kline_data(conn: sqlite3.Connection, dataset: dict):
    """将生成的 K 线数据插入内存数据库"""
    for code, records in dataset.items():
        for rec in records:
            conn.execute(
                """INSERT INTO kline_data
                   (stock_code, time_key, open_price, close_price,
                    high_price, low_price, volume, turnover)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (code, rec["time_key"], rec["open_price"], rec["close_price"],
                 rec["high_price"], rec["low_price"], rec["volume"], rec["turnover"]),
            )
    conn.commit()


def _query_single_stock(db_manager: MockDbManager, stock_code: str, days: int = 30):
    """逐条查询单只股票的 K 线数据，用于与批量查询结果对比"""
    rows = db_manager.execute_query(
        f"""SELECT stock_code, time_key, open_price, close_price,
                   high_price, low_price, volume, turnover
            FROM kline_data
            WHERE stock_code = ?
            AND time_key >= date('now', '-{days} days')
            ORDER BY stock_code, time_key DESC""",
        [stock_code],
    )
    result = []
    for row in rows:
        result.append({
            "time_key": row[1], "open_price": row[2],
            "close_price": row[3], "high_price": row[4],
            "low_price": row[5], "volume": row[6], "turnover": row[7],
        })
    return result


# ── Property 8: K 线批量查询等价性 ──────────────────────────────
# Feature: enhanced-heat-optimization, Property 8: K 线批量查询等价性
# **Validates: Requirements 5.1, 5.2**


class TestProperty8KlineBatchEquivalence:
    """Property 8: 对于任意股票代码集合，批量 K 线查询返回的字典中
    每个 key 都是有效的 stock_code，且每个 value 是该股票的 K 线记录列表；
    批量查询结果应与逐条查询结果在数据内容上等价。"""

    @given(dataset=kline_dataset_st)
    @settings(max_examples=100)
    def test_batch_keys_are_valid_stock_codes(self, dataset):
        """批量查询返回的每个 key 都应是输入的 stock_code"""
        conn = sqlite3.connect(":memory:")
        _create_kline_table(conn)
        _insert_kline_data(conn, dataset)
        db = MockDbManager(conn)

        stock_codes = set(dataset.keys())
        result = _load_kline_data_batch(db, stock_codes)

        # 返回的 key 必须是输入 stock_codes 的子集
        assert set(result.keys()).issubset(stock_codes), (
            f"返回了不在输入中的 key: {set(result.keys()) - stock_codes}"
        )
        conn.close()

    @given(dataset=kline_dataset_st)
    @settings(max_examples=100)
    def test_batch_values_are_nonempty_lists(self, dataset):
        """批量查询返回的每个 value 都应是非空的 K 线记录列表"""
        conn = sqlite3.connect(":memory:")
        _create_kline_table(conn)
        _insert_kline_data(conn, dataset)
        db = MockDbManager(conn)

        stock_codes = set(dataset.keys())
        result = _load_kline_data_batch(db, stock_codes)

        for code, records in result.items():
            assert isinstance(records, list), f"{code} 的值不是列表"
            assert len(records) > 0, f"{code} 的 K 线记录列表为空"
        conn.close()

    @given(dataset=kline_dataset_st)
    @settings(max_examples=100)
    def test_batch_equals_individual_queries(self, dataset):
        """批量查询结果应与逐条查询结果在数据内容上等价"""
        conn = sqlite3.connect(":memory:")
        _create_kline_table(conn)
        _insert_kline_data(conn, dataset)
        db = MockDbManager(conn)

        stock_codes = set(dataset.keys())
        batch_result = _load_kline_data_batch(db, stock_codes)

        # 逐条查询每只股票
        for code in stock_codes:
            single_result = _query_single_stock(db, code)
            batch_records = batch_result.get(code, [])

            # 记录数量应一致
            assert len(batch_records) == len(single_result), (
                f"{code}: 批量查询 {len(batch_records)} 条 vs 逐条查询 {len(single_result)} 条"
            )

            # 逐条对比数据内容
            for i, (batch_rec, single_rec) in enumerate(zip(batch_records, single_result)):
                assert batch_rec == single_rec, (
                    f"{code} 第 {i} 条记录不一致:\n"
                    f"  批量: {batch_rec}\n  逐条: {single_rec}"
                )
        conn.close()

    def test_empty_input_returns_empty_dict(self):
        """空输入应返回空字典"""
        conn = sqlite3.connect(":memory:")
        _create_kline_table(conn)
        db = MockDbManager(conn)

        result = _load_kline_data_batch(db, set())
        assert result == {}

        result2 = _load_kline_data_batch(db, [])
        assert result2 == {}
        conn.close()

    @given(dataset=kline_dataset_st)
    @settings(max_examples=100)
    def test_kline_record_fields_complete(self, dataset):
        """每条 K 线记录应包含完整的 7 个字段"""
        conn = sqlite3.connect(":memory:")
        _create_kline_table(conn)
        _insert_kline_data(conn, dataset)
        db = MockDbManager(conn)

        expected_fields = {
            "time_key", "open_price", "close_price",
            "high_price", "low_price", "volume", "turnover",
        }

        stock_codes = set(dataset.keys())
        result = _load_kline_data_batch(db, stock_codes)

        for code, records in result.items():
            for rec in records:
                assert set(rec.keys()) == expected_fields, (
                    f"{code} 记录字段不完整: {set(rec.keys())}"
                )
        conn.close()

    @given(
        dataset=st.dictionaries(
            keys=stock_code_st,
            values=stock_kline_st,
            min_size=3,
            max_size=3,
        ),
        query_subset=st.integers(min_value=1, max_value=3),
    )
    @settings(max_examples=100)
    def test_query_subset_returns_only_requested(self, dataset, query_subset):
        """查询股票代码子集时，只返回请求的股票数据"""
        conn = sqlite3.connect(":memory:")
        _create_kline_table(conn)
        _insert_kline_data(conn, dataset)
        db = MockDbManager(conn)

        all_codes = list(dataset.keys())
        subset = set(all_codes[:query_subset])
        result = _load_kline_data_batch(db, subset)

        # 返回的 key 只能是请求的子集
        assert set(result.keys()).issubset(subset), (
            f"返回了未请求的股票: {set(result.keys()) - subset}"
        )
        conn.close()
