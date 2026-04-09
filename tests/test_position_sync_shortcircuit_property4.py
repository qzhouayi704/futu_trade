#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
属性测试：Property 4 - 持仓同步短路正确性

**Validates: Requirements 3.2, 3.3**

*For any* 持仓列表，当同步结果的添加数和移除数都为 0 时，
`refresh_global_stock_pool_from_db` 不被调用；
当添加数或移除数大于 0 时，`refresh_global_stock_pool_from_db` 被调用恰好一次。

Tag: Feature: alert-log-optimization, Property 4: 持仓同步短路正确性
"""

import sys
import os
import logging
from unittest.mock import MagicMock, patch

from hypothesis import given, settings, assume, strategies as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.services.trading.execution.position_manager import PositionManager

# 抑制测试中的日志输出
logging.disable(logging.CRITICAL)


# ── hypothesis 策略 ──────────────────────────────────────────────

# 港股股票代码生成器
hk_stock_code = st.from_regex(r"HK\.\d{5}", fullmatch=True)

# 股票名称
stock_name = st.text(min_size=1, max_size=6, alphabet="腾讯美团小米比亚迪阿里百度京东网易快手")

# 合理的持仓数量（正整数表示有持仓）
positive_qty = st.integers(min_value=100, max_value=100000)

# 合理的股票价格（>= 1.0 避免低价股过滤）
stock_price = st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False)


def _make_position(code: str, name: str, qty: int, price: float) -> dict:
    """构建持仓字典"""
    return {
        'stock_code': code,
        'stock_name': name,
        'qty': qty,
        'nominal_price': price,
    }


# 生成持仓列表（1~5 只股票）
position_list = st.lists(
    st.tuples(hk_stock_code, stock_name, positive_qty, stock_price),
    min_size=1,
    max_size=5,
    unique_by=lambda t: t[0],  # 股票代码唯一
)


def _build_db_manager(existing_codes: set):
    """
    构建 mock db_manager，模拟数据库行为。

    Args:
        existing_codes: 板块中已存在的股票代码集合
    """
    db = MagicMock()

    # 为每个已存在的股票分配一个 stock_id
    code_to_id = {code: idx + 100 for idx, code in enumerate(existing_codes)}
    next_id = [200]  # 用列表包装以便在闭包中修改

    def mock_execute_query(sql, params=None):
        sql_lower = sql.strip().lower()

        # 查询板块是否存在 -> 总是返回存在（ID=1）
        if 'select id from plates where plate_code' in sql_lower:
            return [(1,)]

        # 查询板块中现有股票
        if 'select s.id, s.code from stocks' in sql_lower:
            return [(code_to_id[c], c) for c in existing_codes]

        # 查询股票是否已存在（用于添加新股票时）
        if 'select id from stocks where code' in sql_lower:
            code = params[0] if params else None
            if code in code_to_id:
                return [(code_to_id[code],)]
            else:
                # 模拟新插入后的查询
                new_id = next_id[0]
                next_id[0] += 1
                code_to_id[code] = new_id
                return [(new_id,)]

        return []

    db.execute_query = MagicMock(side_effect=mock_execute_query)
    db.execute_update = MagicMock(return_value=None)

    return db


# ── 属性测试 ──────────────────────────────────────────────────────

@given(positions=position_list)
@settings(max_examples=200)
def test_property4_no_change_skips_refresh(positions):
    """Property 4（无变化场景）：添加数和移除数都为 0 时，refresh 不被调用

    **Validates: Requirements 3.2**

    当持仓列表中的股票与板块中已有股票完全一致时，
    added_count == 0 且 removed_count == 0，
    refresh_global_stock_pool_from_db 不应被调用。
    """
    pos_list = [_make_position(code, name, qty, price)
                for code, name, qty, price in positions]

    # 已存在的股票 = 持仓中的股票 -> 无变化
    existing_codes = {code for code, _, _, _ in positions}

    db = _build_db_manager(existing_codes)

    pm = PositionManager(db_manager=db)

    with patch(
        'simple_trade.services.trading.execution.position_manager.refresh_global_stock_pool_from_db'
    ) as mock_refresh:
        result = pm.sync_positions_to_stock_pool(pos_list)

    assert result['added_count'] == 0, (
        f"已存在股票与持仓一致，添加数应为 0，实际: {result['added_count']}"
    )
    assert result['removed_count'] == 0, (
        f"已存在股票与持仓一致，移除数应为 0，实际: {result['removed_count']}"
    )
    mock_refresh.assert_not_called()


@given(
    new_positions=position_list,
    extra_existing=st.lists(hk_stock_code, min_size=0, max_size=3, unique=True),
)
@settings(max_examples=200)
def test_property4_has_additions_calls_refresh(new_positions, extra_existing):
    """Property 4（有添加场景）：添加数 > 0 时，refresh 被调用恰好一次

    **Validates: Requirements 3.3**

    当持仓列表中有新股票不在板块中时，added_count > 0，
    refresh_global_stock_pool_from_db 应被调用恰好一次。
    """
    pos_list = [_make_position(code, name, qty, price)
                for code, name, qty, price in new_positions]

    new_codes = {code for code, _, _, _ in new_positions}

    # 已存在的股票 = 空集 + extra_existing（不包含新持仓的代码）
    existing_codes = {c for c in extra_existing if c not in new_codes}

    # 确保至少有一只新股票不在已存在集合中
    assume(not new_codes.issubset(existing_codes))

    db = _build_db_manager(existing_codes)
    pm = PositionManager(db_manager=db)

    with patch(
        'simple_trade.services.trading.execution.position_manager.refresh_global_stock_pool_from_db'
    ) as mock_refresh:
        result = pm.sync_positions_to_stock_pool(pos_list)

    # 有新增或有移除时，refresh 应被调用
    total_changes = result['added_count'] + result['removed_count']
    assert total_changes > 0, (
        f"应有变化，但 added={result['added_count']}, removed={result['removed_count']}"
    )
    mock_refresh.assert_called_once()


@given(
    positions=position_list,
    extra_existing=st.lists(hk_stock_code, min_size=1, max_size=3, unique=True),
)
@settings(max_examples=200)
def test_property4_has_removals_calls_refresh(positions, extra_existing):
    """Property 4（有移除场景）：移除数 > 0 时，refresh 被调用恰好一次

    **Validates: Requirements 3.3**

    当板块中有股票不在当前持仓中时，removed_count > 0，
    refresh_global_stock_pool_from_db 应被调用恰好一次。
    """
    pos_list = [_make_position(code, name, qty, price)
                for code, name, qty, price in positions]

    pos_codes = {code for code, _, _, _ in positions}

    # 已存在的股票 = 持仓中的股票 + 额外的（模拟已清仓的股票）
    stale_codes = {c for c in extra_existing if c not in pos_codes}
    assume(len(stale_codes) > 0)  # 确保有需要移除的股票

    existing_codes = pos_codes | stale_codes

    db = _build_db_manager(existing_codes)
    pm = PositionManager(db_manager=db)

    with patch(
        'simple_trade.services.trading.execution.position_manager.refresh_global_stock_pool_from_db'
    ) as mock_refresh:
        result = pm.sync_positions_to_stock_pool(pos_list)

    assert result['removed_count'] > 0, (
        f"应有移除，但 removed_count={result['removed_count']}"
    )
    mock_refresh.assert_called_once()


@given(
    positions=position_list,
    extra_new=position_list,
    extra_existing=st.lists(hk_stock_code, min_size=1, max_size=3, unique=True),
)
@settings(max_examples=200)
def test_property4_mixed_changes_calls_refresh_once(positions, extra_new, extra_existing):
    """Property 4（混合变化场景）：同时有添加和移除时，refresh 仍只调用一次

    **Validates: Requirements 3.2, 3.3**

    当同时存在新增和移除时，refresh_global_stock_pool_from_db 被调用恰好一次。
    """
    # 合并两组持仓，去重
    all_positions = {code: (code, name, qty, price)
                     for code, name, qty, price in positions}
    for code, name, qty, price in extra_new:
        if code not in all_positions:
            all_positions[code] = (code, name, qty, price)

    pos_list = [_make_position(code, name, qty, price)
                for code, name, qty, price in all_positions.values()]

    pos_codes = set(all_positions.keys())

    # 已存在的股票：只包含部分持仓 + 额外的已清仓股票
    # 取持仓的前半部分作为已存在
    half = len(pos_codes) // 2
    partial_existing = set(list(pos_codes)[:half])
    stale_codes = {c for c in extra_existing if c not in pos_codes}

    assume(len(stale_codes) > 0)  # 确保有移除
    assume(len(pos_codes - partial_existing) > 0)  # 确保有新增

    existing_codes = partial_existing | stale_codes

    db = _build_db_manager(existing_codes)
    pm = PositionManager(db_manager=db)

    with patch(
        'simple_trade.services.trading.execution.position_manager.refresh_global_stock_pool_from_db'
    ) as mock_refresh:
        result = pm.sync_positions_to_stock_pool(pos_list)

    assert result['added_count'] > 0, (
        f"应有新增，但 added_count={result['added_count']}"
    )
    assert result['removed_count'] > 0, (
        f"应有移除，但 removed_count={result['removed_count']}"
    )
    mock_refresh.assert_called_once()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
