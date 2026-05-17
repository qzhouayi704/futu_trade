#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强热度分析 - 数据准备辅助函数

从 enhanced_heat.py 拆分出的数据准备、报价合并、K线加载等辅助逻辑，
控制主路由文件行数在 300 行以内。
"""

import logging
from dataclasses import asdict as _asdict
from typing import Dict, List

from ....services.analysis.heat.heat_quote_service import SnapshotQuote

# pipeline 报价使用 change_percent，而 MarketHeatMonitor 期望 change_pct
# 此映射表在数据入口处统一字段名，避免下游消费方逐个兼容
_FIELD_ALIASES = {
    'change_percent': 'change_pct',
}


def _normalize_quote(quote: Dict) -> Dict:
    """归一化报价字段名，将 pipeline 字段名映射为 monitor 期望的字段名"""
    normalized = dict(quote)
    for old_key, new_key in _FIELD_ALIASES.items():
        if old_key in normalized and new_key not in normalized:
            normalized[new_key] = normalized[old_key]
    return normalized


def _build_quotes_map(container, cached_quotes, all_stock_codes, heat_quote_svc=None):
    """构建合并后的报价字典

    有 heat_quote_svc 时获取全量快照并与 pipeline 缓存合并；
    否则仅使用 pipeline 缓存数据。

    Args:
        container: 服务容器（可选）
        cached_quotes: pipeline 缓存的报价列表
        all_stock_codes: 股票池中所有股票代码集合
        heat_quote_svc: HeatQuoteService 实例（可选）

    Returns:
        {stock_code: quote_dict} 合并后的报价字典
    """
    pipeline_only = {
        q.get('code'): _normalize_quote(q)
        for q in cached_quotes if isinstance(q, dict)
    }

    if heat_quote_svc is None:
        return pipeline_only

    # 获取全量快照并合并
    try:
        snapshot_quotes = heat_quote_svc.get_snapshot_quotes(list(all_stock_codes))
        return merge_quotes(cached_quotes, snapshot_quotes)
    except Exception as e:
        logging.error(f"获取快照报价失败，降级使用 pipeline 数据: {e}")
        return pipeline_only


def get_realtime_data(container=None, heat_quote_svc=None):
    """从 state_manager 获取实时报价和板块数据

    当提供 heat_quote_svc 时，会获取全量快照，
    并与 pipeline 缓存数据合并（pipeline 优先），实现完整报价覆盖。

    Args:
        container: 服务容器（可选），用于获取 HeatQuoteService
        heat_quote_svc: HeatQuoteService 实例（可选）

    Returns:
        (quotes_list, quotes_map, plates_for_monitor, plates_for_filter, all_stock_codes)
    """
    from ....core import get_state_manager

    state = get_state_manager()
    pool_data = state.get_stock_pool()
    cached_quotes = state.get_cached_quotes() or []

    # 从 stocks 列表直接提取所有股票代码
    stocks_list = pool_data.get('stocks', [])
    all_stock_codes = {s.get('code', '') for s in stocks_list if s.get('code')}

    # 构建 plate_name -> [stock, ...] 反向索引
    plate_stocks_map: Dict[str, List[Dict]] = {}
    for stock in stocks_list:
        for pname in stock.get('plate_names', []):
            plate_stocks_map.setdefault(pname, []).append(stock)

    plates_for_monitor = []
    plates_for_filter = []

    for plate in pool_data.get('plates', []):
        p_code = plate.get('code', '')
        p_name = plate.get('name', '')
        stocks = plate_stocks_map.get(p_name, [])

        plates_for_monitor.append({
            'plate_code': p_code, 'plate_name': p_name,
            'stock_count': len(stocks),
            'stocks': [s.get('code', '') for s in stocks],
        })
        plates_for_filter.append({
            'plate_code': p_code, 'plate_name': p_name,
            'stocks': [
                {'stock_code': s.get('code', ''), 'stock_name': s.get('name', ''),
                 'market': s.get('market', '')}
                for s in stocks
            ],
        })

    # 集成 HeatQuoteService：获取全量快照并与 pipeline 缓存合并
    quotes_map = _build_quotes_map(
        container, cached_quotes, all_stock_codes, heat_quote_svc
    ) if heat_quote_svc else {
        q.get('code'): _normalize_quote(q)
        for q in cached_quotes if isinstance(q, dict)
    }

    return cached_quotes, quotes_map, plates_for_monitor, plates_for_filter, all_stock_codes


def merge_quotes(
    pipeline_quotes: List[Dict],
    snapshot_quotes: Dict[str, SnapshotQuote],
) -> Dict[str, Dict]:
    """合并报价管道数据和快照数据

    先以 snapshot 数据为底，再用 pipeline 数据覆盖。
    pipeline 数据优先级更高（因为更实时）。

    Args:
        pipeline_quotes: 从 QuoteCache 获取的报价列表，每个元素是 dict（含 'code' 键）
        snapshot_quotes: 从 HeatQuoteService 获取的快照字典 {stock_code: SnapshotQuote}

    Returns:
        {stock_code: quote_dict} 合并后的报价字典

    Validates: Requirements 3.1, 3.2, 3.3
    """
    merged: Dict[str, Dict] = {}

    # 第一步：以 snapshot 数据为底
    for code, snap in snapshot_quotes.items():
        merged[code] = _asdict(snap)

    # 第二步：用 pipeline 数据覆盖（优先级更高），并归一化字段名
    for quote in pipeline_quotes:
        if not isinstance(quote, dict):
            continue
        code = quote.get('code')
        if code:
            merged[code] = _normalize_quote(quote)

    return merged


def load_kline_data_batch(db_manager, stock_codes, days=30):
    """批量加载 K 线数据，使用 WHERE IN 替代逐条查询"""
    if not stock_codes:
        return {}

    kline_map = {}
    code_list = list(stock_codes)
    batch_size = 500

    for i in range(0, len(code_list), batch_size):
        batch = code_list[i:i + batch_size]
        placeholders = ','.join(['?'] * len(batch))
        try:
            rows = db_manager.execute_query(f'''
                SELECT stock_code, time_key, open_price, close_price,
                       high_price, low_price, volume, turnover
                FROM kline_data
                WHERE stock_code IN ({placeholders})
                AND time_key >= date('now', '-{days} days')
                ORDER BY stock_code, time_key DESC
            ''', batch)

            for row in rows:
                code = row[0]
                kline_map.setdefault(code, []).append({
                    'time_key': row[1], 'open_price': row[2],
                    'close_price': row[3], 'high_price': row[4],
                    'low_price': row[5], 'volume': row[6], 'turnover': row[7]
                })
        except Exception as e:
            logging.debug(f"批量加载K线数据失败 (批次 {i // batch_size + 1}): {e}")

    return kline_map
