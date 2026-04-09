#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
活跃度筛选 Phase 2 验证测试 — 订阅保持与合并行为

验证需求 2.4、2.5、3.6、3.7：
- Property 3: 未过期活跃股票不参与重新筛选 (2.5)
- Property 4: 最终活跃集合为 cached_active + batch_active 合并 (3.7)
- Property 5: 未过期活跃股票的订阅保持 (2.4, 3.6)

设计分析结论：现有代码已满足这些需求，无需额外代码修改。
本测试文件验证这一结论的正确性。
"""

import os
import sys
import tempfile
import logging
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.database.core.connection_manager import ConnectionManager
from simple_trade.database.queries.stock_activity_queries import StockActivityQueries
from simple_trade.services.realtime.activity_calculator import ActivityCalculator

logging.basicConfig(level=logging.WARNING)


class FakeDbManager:
    """用于测试的最小化 db_manager"""

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

fresh_minutes_st = st.integers(min_value=0, max_value=9)
expired_minutes_st = st.integers(min_value=11, max_value=60)
positive_score_st = st.floats(min_value=0.1, max_value=1.0, allow_nan=False)
num_stocks_st = st.integers(min_value=1, max_value=4)


@st.composite
def mixed_cache_scenario(draw):
    """生成混合缓存场景：部分未过期活跃、部分过期、部分无缓存"""
    types = ["fresh_active", "expired", "no_cache"]
    extra_count = draw(num_stocks_st)
    extra_types = draw(st.lists(
        st.sampled_from(types), min_size=extra_count, max_size=extra_count
    ))
    all_types = types + extra_types

    stocks = []
    cache_records = []

    for i, cache_type in enumerate(all_types):
        code = f"HK.MIX_{i:04d}"
        stocks.append({'code': code, 'name': f'混合测试{i}', 'market': 'HK'})

        if cache_type == "fresh_active":
            cache_records.append({
                'code': code, 'cache_type': cache_type,
                'is_active': 1, 'activity_score': draw(positive_score_st),
                'minutes_ago': draw(fresh_minutes_st),
            })
        elif cache_type == "expired":
            cache_records.append({
                'code': code, 'cache_type': cache_type,
                'is_active': 1, 'activity_score': draw(positive_score_st),
                'minutes_ago': draw(expired_minutes_st),
            })
        else:
            cache_records.append({'code': code, 'cache_type': cache_type})

    return stocks, cache_records


# ── Property 3: 未过期活跃股票不参与重新筛选 (需求 2.5) ─────────


class TestProperty3FreshActiveNotRefiltered:
    """未过期活跃 → cached_active；过期/无缓存 → uncached"""

    @given(scenario=mixed_cache_scenario())
    @settings(max_examples=50)
    def test_fresh_active_in_cached_expired_in_uncached(self, scenario):
        stocks, cache_records = scenario

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            db_manager = FakeDbManager(db_path)
            calculator = ActivityCalculator(config=None, db_manager=db_manager)

            from datetime import datetime, timedelta
            today = datetime.now().strftime('%Y-%m-%d')

            with db_manager.conn_manager.get_connection() as conn:
                for record in cache_records:
                    if record['cache_type'] == 'no_cache':
                        continue
                    past_time = datetime.now() - timedelta(minutes=record['minutes_ago'])
                    conn.execute(
                        'INSERT OR REPLACE INTO daily_active_stocks '
                        '(check_date, stock_code, market, is_active, activity_score, '
                        'turnover_rate, turnover_amount, created_at) '
                        'VALUES (?, ?, ?, ?, ?, 0, 0, ?)',
                        (today, record['code'], 'HK',
                         record['is_active'], record['activity_score'],
                         past_time.strftime('%Y-%m-%d %H:%M:%S')),
                    )
                conn.commit()

            cached_active, uncached = calculator.check_activity_cache(stocks)
            cached_codes = {s['code'] for s in cached_active}
            uncached_codes = {s['code'] for s in uncached}

            for record in cache_records:
                code = record['code']
                if record['cache_type'] == 'fresh_active':
                    assert code in cached_codes, (
                        f"需求2.5违规: 未过期活跃 {code} 未在 cached_active"
                    )
                    assert code not in uncached_codes, (
                        f"需求2.5违规: 未过期活跃 {code} 不应在 uncached"
                    )
                else:
                    assert code in uncached_codes, (
                        f"需求2.5违规: {record['cache_type']} {code} 应在 uncached"
                    )
                    assert code not in cached_codes, (
                        f"需求2.5违规: {record['cache_type']} {code} 不应在 cached_active"
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


# ── Property 4: 最终活跃集合为合并结果 (需求 3.7) ────────────────


class TestProperty4MergedActiveSet:
    """_do_activity_filter 返回 priority + cached_active + batch_active 并集"""

    @given(
        n_priority=st.integers(min_value=0, max_value=3),
        n_cached=st.integers(min_value=0, max_value=3),
        n_batch_active=st.integers(min_value=0, max_value=3),
        n_batch_inactive=st.integers(min_value=0, max_value=3),
    )
    @settings(max_examples=50)
    def test_active_stocks_is_union_of_all_sources(
        self, n_priority, n_cached, n_batch_active, n_batch_inactive
    ):
        from simple_trade.services.market_data.activity_filter import ActivityFilterService

        priority_stocks = [
            {'code': f'HK.PRI_{i}', 'name': f'优先{i}', 'market': 'HK',
             'is_priority': True, 'activity_score': 1.0}
            for i in range(n_priority)
        ]
        cached_stocks = [
            {'code': f'HK.CAC_{i}', 'name': f'缓存{i}', 'market': 'HK',
             'from_cache': True, 'activity_score': 0.5}
            for i in range(n_cached)
        ]
        batch_active = [
            {'code': f'HK.BAT_{i}', 'name': f'新筛选{i}', 'market': 'HK',
             'activity_score': 0.6}
            for i in range(n_batch_active)
        ]
        batch_inactive = [f'HK.INA_{i}' for i in range(n_batch_inactive)]

        all_pending = (
            [{'code': s['code'], 'name': s['name'], 'market': 'HK'} for s in cached_stocks]
            + [{'code': f'HK.BAT_{i}', 'name': f'新筛选{i}', 'market': 'HK'}
               for i in range(n_batch_active)]
            + [{'code': f'HK.INA_{i}', 'name': f'不活跃{i}', 'market': 'HK'}
               for i in range(n_batch_inactive)]
        )
        all_stocks = (
            [{'code': s['code'], 'name': s['name'], 'market': 'HK'} for s in priority_stocks]
            + all_pending
        )
        priority_codes = [s['code'] for s in priority_stocks]

        mock_config = MagicMock()
        mock_config.realtime_activity_filter = {
            'min_turnover_rate': 1.0, 'min_turnover_amount': 5000000,
        }
        mock_config.min_stock_price = {}

        service = ActivityFilterService(
            subscription_manager=MagicMock(), quote_service=MagicMock(),
            config=mock_config, db_manager=None, container=None,
        )

        service.calculator.handle_priority_stocks = MagicMock(
            return_value=(all_pending, priority_stocks)
        )
        service.calculator.check_activity_cache = MagicMock(
            return_value=(cached_stocks, [
                s for s in all_pending
                if s['code'] not in {c['code'] for c in cached_stocks}
            ])
        )
        service.calculator.get_min_volume = MagicMock(return_value=500000)
        service.calculator.get_min_price_config = MagicMock(return_value={})

        service.optimizer = MagicMock()
        service.optimizer.process_batches = MagicMock(
            return_value={'active': batch_active, 'inactive': batch_inactive, 'failed': []}
        )

        active_stocks, stats = service._do_activity_filter(
            all_stocks, {'min_turnover_rate': 1.0, 'min_turnover_amount': 5000000},
            priority_codes,
        )

        active_codes = {s['code'] for s in active_stocks}
        expected_codes = (
            {s['code'] for s in priority_stocks}
            | {s['code'] for s in cached_stocks}
            | {s['code'] for s in batch_active}
        )

        assert active_codes == expected_codes, (
            f"需求3.7违规: active_stocks 应为三者并集。"
            f"\n  缺失: {expected_codes - active_codes}"
            f"\n  多余: {active_codes - expected_codes}"
        )


# ── Property 5: 未过期活跃股票的订阅保持 (需求 2.4, 3.6) ────────


class TestProperty5SubscriptionContinuity:
    """subscribe() 是增量式的，不会取消已有订阅"""

    def test_subscribe_is_incremental_no_unsubscribe(self):
        """两轮订阅中，第一轮已订阅的股票不被取消"""
        from simple_trade.api.subscription_core import SubscriptionCore

        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_client.client = MagicMock()

        core = SubscriptionCore(futu_client=mock_client)

        # 模拟第一轮已订阅
        core._subscribed_stocks = {'HK.00700', 'HK.09988', 'HK.03690'}

        # Mock optimizer 使新股票订阅成功
        core._optimizer = MagicMock()

        def fake_process(new_stocks, result):
            result['successful_stocks'] = new_stocks
        core._optimizer.process_batches = MagicMock(side_effect=fake_process)

        # 第二轮：订阅 00700, 09988, 01810（前两个已订阅）
        result = core.subscribe(['HK.00700', 'HK.09988', 'HK.01810'])

        # 已订阅的在 already_subscribed 中
        assert 'HK.00700' in result['already_subscribed']
        assert 'HK.09988' in result['already_subscribed']

        # 只有新股票传给 optimizer
        core._optimizer.process_batches.assert_called_once()
        actual_new = core._optimizer.process_batches.call_args[0][0]
        assert actual_new == ['HK.01810']

        # unsubscribe 从未被调用
        assert not mock_client.client.unsubscribe.called, (
            "需求2.4/3.6违规: subscribe() 不应调用 unsubscribe"
        )

        # 原有订阅仍在
        assert 'HK.00700' in core._subscribed_stocks
        assert 'HK.09988' in core._subscribed_stocks
        assert 'HK.03690' in core._subscribed_stocks

    @given(
        first_round=st.lists(
            st.sampled_from([f'HK.S{i:04d}' for i in range(20)]),
            min_size=3, max_size=10, unique=True
        ),
        second_round=st.lists(
            st.sampled_from([f'HK.S{i:04d}' for i in range(20)]),
            min_size=3, max_size=10, unique=True
        ),
    )
    @settings(max_examples=50)
    def test_two_rounds_preserves_first_round(self, first_round, second_round):
        """属性测试：任意两轮订阅，第一轮集合只增不减"""
        from simple_trade.api.subscription_core import SubscriptionCore

        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_client.client = MagicMock()

        core = SubscriptionCore(futu_client=mock_client)
        core._subscribed_stocks = set(first_round)

        core._optimizer = MagicMock()

        def fake_process(new_stocks, result):
            result['successful_stocks'] = new_stocks
        core._optimizer.process_batches = MagicMock(side_effect=fake_process)

        core.subscribe(second_round)

        # 第一轮所有股票仍在
        assert set(first_round).issubset(core._subscribed_stocks), (
            f"需求2.4/3.6违规: 丢失 {set(first_round) - core._subscribed_stocks}"
        )

        # unsubscribe 从未被调用
        mock_client.client.unsubscribe.assert_not_called()
