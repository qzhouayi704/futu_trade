#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
活跃度缓存过期 Bug 条件探索测试

Property 1: Fault Condition - 过期缓存仍被视为有效

目标：生成反例证明 bug 存在 —— 当缓存记录的 created_at 超过 10 分钟时，
check_activity_cache 仍将其视为有效缓存，而非将对应股票归入 uncached 列表。

**Validates: Requirements 1.1, 2.1**
"""

import os
import sys
import sqlite3
import tempfile
import logging

import pytest
from hypothesis import given, settings, strategies as st, assume

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.database.core.connection_manager import ConnectionManager
from simple_trade.database.queries.stock_activity_queries import StockActivityQueries
from simple_trade.services.realtime.activity_calculator import ActivityCalculator

logging.basicConfig(level=logging.DEBUG)


# ── 辅助：创建内存数据库并初始化表结构 ──────────────────────────

class FakeDbManager:
    """用于测试的最小化 db_manager，仅提供 stock_activity_queries"""

    def __init__(self, db_path: str):
        self.conn_manager = ConnectionManager(db_path)
        # 初始化表结构
        with self.conn_manager.get_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS daily_active_stocks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    check_date TEXT NOT NULL,
                    stock_code TEXT NOT NULL,
                    market TEXT NOT NULL,
                    is_active INTEGER NOT NULL,
                    activity_score REAL DEFAULT 0,
                    turnover_rate REAL DEFAULT 0,
                    turnover_amount REAL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(check_date, stock_code)
                )
            ''')
            conn.commit()
        self.stock_activity_queries = StockActivityQueries(self.conn_manager)


# ── hypothesis 策略 ──────────────────────────────────────────────

# 过期时间：11-60 分钟前（确保超过 10 分钟阈值）
expired_minutes_st = st.integers(min_value=11, max_value=60)

# is_active 状态：0 或 1（混合测试）
is_active_st = st.booleans()

# activity_score：活跃时 0.1-1.0，不活跃时 0
activity_score_st = st.floats(min_value=0.1, max_value=1.0, allow_nan=False)

# 股票数量：1-5 只（保持测试简洁高效）
num_stocks_st = st.integers(min_value=1, max_value=5)


@st.composite
def expired_cache_scenario(draw):
    """生成一组过期缓存记录的测试场景

    每只股票的 created_at 都超过 10 分钟，is_active 随机混合。
    """
    n = draw(num_stocks_st)
    stocks = []
    cache_records = []

    for i in range(n):
        code = f"HK.TEST_{i:04d}"
        is_active = draw(is_active_st)
        minutes_ago = draw(expired_minutes_st)
        score = draw(activity_score_st) if is_active else 0.0

        stocks.append({'code': code, 'name': f'测试股票{i}', 'market': 'HK'})
        cache_records.append({
            'code': code,
            'is_active': is_active,
            'activity_score': score,
            'minutes_ago': minutes_ago,
        })

    return stocks, cache_records


# ── Property 1: 故障条件 - 过期缓存应触发重新筛选 ────────────────
# **Validates: Requirements 1.1, 2.1**


class TestProperty1FaultConditionExpiredCache:
    """Property 1: 对于任意过期缓存记录（created_at 超过 10 分钟），
    check_activity_cache 应将对应股票归入 uncached 列表，
    而非使用过期的缓存结果。

    在未修复代码上运行，预期 FAIL（确认 bug 存在）。
    """

    @given(scenario=expired_cache_scenario())
    @settings(max_examples=50)
    def test_expired_cache_stocks_should_be_uncached(self, scenario):
        """过期缓存的股票应出现在 uncached 列表中，不应出现在 cached_active 中"""
        stocks, cache_records = scenario

        # 创建临时数据库
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            db_manager = FakeDbManager(db_path)
            calculator = ActivityCalculator(config=None, db_manager=db_manager)

            from datetime import datetime, timedelta
            today = datetime.now().strftime('%Y-%m-%d')

            # 插入过期缓存记录：手动设置 created_at 为 N 分钟前
            with db_manager.conn_manager.get_connection() as conn:
                for record in cache_records:
                    past_time = datetime.now() - timedelta(minutes=record['minutes_ago'])
                    past_time_str = past_time.strftime('%Y-%m-%d %H:%M:%S')
                    conn.execute('''
                        INSERT OR REPLACE INTO daily_active_stocks
                        (check_date, stock_code, market, is_active, activity_score,
                         turnover_rate, turnover_amount, created_at)
                        VALUES (?, ?, 'HK', ?, ?, 0, 0, ?)
                    ''', (
                        today,
                        record['code'],
                        1 if record['is_active'] else 0,
                        record['activity_score'],
                        past_time_str,
                    ))
                conn.commit()

            # 调用 check_activity_cache
            cached_active, uncached = calculator.check_activity_cache(stocks)

            # 收集结果中的股票代码
            cached_active_codes = {s['code'] for s in cached_active}
            uncached_codes = {s['code'] for s in uncached}

            # 断言：所有过期缓存的股票都应在 uncached 中
            for record in cache_records:
                code = record['code']
                assert code not in cached_active_codes, (
                    f"Bug 确认: 过期缓存股票 {code} "
                    f"(created_at 为 {record['minutes_ago']} 分钟前, "
                    f"is_active={record['is_active']}) "
                    f"仍被视为有效缓存出现在 cached_active 中"
                )
                assert code in uncached_codes, (
                    f"Bug 确认: 过期缓存股票 {code} "
                    f"(created_at 为 {record['minutes_ago']} 分钟前) "
                    f"未出现在 uncached 列表中"
                )

        finally:
            # 清理临时数据库
            try:
                db_manager.conn_manager.close_all_connections()
            except Exception:
                pass
            try:
                os.unlink(db_path)
            except Exception:
                pass
