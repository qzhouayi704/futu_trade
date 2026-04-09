#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
活跃度缓存保持属性测试

Property 2: Preservation - 未过期缓存行为不变

目标：验证对于所有 created_at 在 10 分钟以内的缓存记录，
check_activity_cache 的分类结果（活跃/不活跃/检查失败）与修复前一致。

在未修复代码上运行，预期 PASS（确认基线行为）。

**Validates: Requirements 3.1, 3.2, 3.4, 3.5**
"""

import os
import sys
import tempfile
import logging

import pytest
from hypothesis import given, settings, strategies as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.database.core.connection_manager import ConnectionManager
from simple_trade.database.queries.stock_activity_queries import StockActivityQueries
from simple_trade.services.realtime.activity_calculator import ActivityCalculator

logging.basicConfig(level=logging.WARNING)


# ── 辅助：创建内存数据库并初始化表结构 ──────────────────────────

class FakeDbManager:
    """用于测试的最小化 db_manager，仅提供 stock_activity_queries"""

    def __init__(self, db_path: str):
        self.conn_manager = ConnectionManager(db_path)
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

# 未过期时间：0-9 分钟前（确保在 10 分钟阈值以内）
fresh_minutes_st = st.integers(min_value=0, max_value=9)

# 股票数量：1-5 只
num_stocks_st = st.integers(min_value=1, max_value=5)

# activity_score：活跃时 0.1-1.0
positive_score_st = st.floats(min_value=0.1, max_value=1.0, allow_nan=False)


# ── 缓存记录类型枚举 ────────────────────────────────────────────
# 每只股票可能的缓存状态：
#   "active"       → is_active=1, activity_score > 0
#   "inactive"     → is_active=0, activity_score = 0
#   "check_failed" → is_active=0, activity_score = -1
#   "no_cache"     → 无缓存记录

cache_type_st = st.sampled_from(["active", "inactive", "check_failed", "no_cache"])


@st.composite
def preservation_scenario(draw):
    """生成一组保持测试场景

    每只股票随机分配一种缓存状态，有缓存的记录 created_at 在 10 分钟以内。
    """
    n = draw(num_stocks_st)
    stocks = []
    cache_records = []

    for i in range(n):
        code = f"HK.PRES_{i:04d}"
        cache_type = draw(cache_type_st)

        stocks.append({'code': code, 'name': f'保持测试股票{i}', 'market': 'HK'})

        if cache_type == "no_cache":
            # 无缓存记录，不插入数据库
            cache_records.append({
                'code': code,
                'cache_type': cache_type,
            })
        else:
            minutes_ago = draw(fresh_minutes_st)
            if cache_type == "active":
                score = draw(positive_score_st)
                is_active = 1
            elif cache_type == "inactive":
                score = 0.0
                is_active = 0
            else:  # check_failed
                score = -1.0
                is_active = 0

            cache_records.append({
                'code': code,
                'cache_type': cache_type,
                'is_active': is_active,
                'activity_score': score,
                'minutes_ago': minutes_ago,
            })

    return stocks, cache_records


# ── Property 2: 保持不变 - 未过期缓存行为不变 ────────────────────
# **Validates: Requirements 3.1, 3.2, 3.4, 3.5**


class TestProperty2PreservationFreshCache:
    """Property 2: 对于任意未过期缓存记录（created_at 在 10 分钟以内），
    check_activity_cache 的分类结果与修复前一致：
    - is_active=1 → 出现在 cached_active 列表
    - is_active=0 → 被跳过（不在 cached_active 也不在 uncached）
    - activity_score=-1 → 出现在 uncached 列表
    - 无缓存记录 → 出现在 uncached 列表

    在未修复代码上运行，预期 PASS（确认基线行为）。
    """

    @given(scenario=preservation_scenario())
    @settings(max_examples=100)
    def test_fresh_cache_classification_preserved(self, scenario):
        """未过期缓存的分类结果应与修复前行为一致"""
        stocks, cache_records = scenario

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            db_manager = FakeDbManager(db_path)
            calculator = ActivityCalculator(config=None, db_manager=db_manager)

            from datetime import datetime, timedelta
            today = datetime.now().strftime('%Y-%m-%d')

            # 插入未过期缓存记录
            with db_manager.conn_manager.get_connection() as conn:
                for record in cache_records:
                    if record['cache_type'] == 'no_cache':
                        continue
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
                        record['is_active'],
                        record['activity_score'],
                        past_time_str,
                    ))
                conn.commit()

            # 调用 check_activity_cache
            cached_active, uncached = calculator.check_activity_cache(stocks)

            cached_active_codes = {s['code'] for s in cached_active}
            uncached_codes = {s['code'] for s in uncached}

            # 验证每只股票的分类结果与修复前行为一致
            for record in cache_records:
                code = record['code']
                cache_type = record['cache_type']

                if cache_type == "active":
                    # 活跃缓存 → 应在 cached_active
                    assert code in cached_active_codes, (
                        f"保持违规: 活跃缓存股票 {code} "
                        f"(created_at {record['minutes_ago']} 分钟前) "
                        f"未出现在 cached_active 中"
                    )
                    assert code not in uncached_codes, (
                        f"保持违规: 活跃缓存股票 {code} "
                        f"不应出现在 uncached 中"
                    )

                elif cache_type == "inactive":
                    # 不活跃缓存 → 被跳过（不在任何列表）
                    assert code not in cached_active_codes, (
                        f"保持违规: 不活跃缓存股票 {code} "
                        f"不应出现在 cached_active 中"
                    )
                    assert code not in uncached_codes, (
                        f"保持违规: 不活跃缓存股票 {code} "
                        f"不应出现在 uncached 中（应被跳过）"
                    )

                elif cache_type == "check_failed":
                    # 检查失败 → 应在 uncached
                    assert code in uncached_codes, (
                        f"保持违规: 检查失败股票 {code} "
                        f"(activity_score=-1) 未出现在 uncached 中"
                    )
                    assert code not in cached_active_codes, (
                        f"保持违规: 检查失败股票 {code} "
                        f"不应出现在 cached_active 中"
                    )

                elif cache_type == "no_cache":
                    # 无缓存 → 应在 uncached
                    assert code in uncached_codes, (
                        f"保持违规: 无缓存股票 {code} "
                        f"未出现在 uncached 中"
                    )
                    assert code not in cached_active_codes, (
                        f"保持违规: 无缓存股票 {code} "
                        f"不应出现在 cached_active 中"
                    )

        finally:
            try:
                db_manager.conn_manager.close_all_connections()
            except Exception:
                pass
            try:
                os.unlink(db_path)
            except Exception:
                pass

    @given(scenario=preservation_scenario())
    @settings(max_examples=50)
    def test_cached_active_stocks_have_cache_metadata(self, scenario):
        """缓存命中的活跃股票应携带 from_cache=True 和 activity_score 元数据"""
        stocks, cache_records = scenario

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            db_manager = FakeDbManager(db_path)
            calculator = ActivityCalculator(config=None, db_manager=db_manager)

            from datetime import datetime, timedelta
            today = datetime.now().strftime('%Y-%m-%d')

            # 构建 code → record 映射
            record_map = {}
            with db_manager.conn_manager.get_connection() as conn:
                for record in cache_records:
                    record_map[record['code']] = record
                    if record['cache_type'] == 'no_cache':
                        continue
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
                        record['is_active'],
                        record['activity_score'],
                        past_time_str,
                    ))
                conn.commit()

            cached_active, uncached = calculator.check_activity_cache(stocks)

            # 验证 cached_active 中的股票携带正确的元数据
            for stock in cached_active:
                code = stock['code']
                record = record_map[code]
                assert stock.get('from_cache') is True, (
                    f"保持违规: 缓存活跃股票 {code} 缺少 from_cache=True"
                )
                assert stock.get('activity_score') == record['activity_score'], (
                    f"保持违规: 缓存活跃股票 {code} 的 activity_score "
                    f"应为 {record['activity_score']}，实际为 {stock.get('activity_score')}"
                )

        finally:
            try:
                db_manager.conn_manager.close_all_connections()
            except Exception:
                pass
            try:
                os.unlink(db_path)
            except Exception:
                pass

    def test_no_db_manager_returns_all_uncached(self):
        """无 db_manager 时，所有股票应归入 uncached（异常降级）

        **Validates: Requirements 3.5**
        """
        calculator = ActivityCalculator(config=None, db_manager=None)
        stocks = [
            {'code': 'HK.TEST_0001', 'name': '测试1', 'market': 'HK'},
            {'code': 'HK.TEST_0002', 'name': '测试2', 'market': 'HK'},
        ]
        cached_active, uncached = calculator.check_activity_cache(stocks)
        assert cached_active == []
        assert uncached == stocks
