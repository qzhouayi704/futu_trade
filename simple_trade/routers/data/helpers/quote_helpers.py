#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
共享报价获取工具

从 ai_analysis.py 和 capital_and_orders.py 提取的公共函数，
避免重复实现相同的缓存 → fallback 逻辑。
"""

import logging

logger = logging.getLogger(__name__)


def get_stock_quote(container, stock_code: str) -> dict:
    """从缓存或实时查询获取单只股票行情

    优先从 state_manager 的缓存报价中查找，
    未命中则 fallback 到 realtime_query API。

    Returns:
        报价字典，失败返回空 dict
    """
    quote = {}

    # 优先从缓存获取
    try:
        from ...core import get_state_manager
        state = get_state_manager()
        if state:
            quotes = state.get_cached_quotes() or []
            for q in quotes:
                code = q.get('code', '') or q.get('stock_code', '')
                if code == stock_code:
                    quote = q
                    break
    except Exception:
        pass

    # 缓存没有，尝试实时查询
    if not quote:
        realtime = getattr(container, 'realtime_query', None) or \
                   getattr(getattr(container, 'data', None), 'realtime_query', None)
        if realtime:
            try:
                result = realtime.get_realtime_quotes([stock_code])
                if result.get('success') and result.get('quotes'):
                    quote = result['quotes'][0]
            except Exception as e:
                logger.warning(f"实时查询 {stock_code} 行情失败: {e}")

    # 确保 change_rate 字段存在
    if quote and 'change_rate' not in quote:
        quote['change_rate'] = (
            quote.get('change_percent', 0)
            or quote.get('change_pct', 0)
            or 0
        )

    return quote
