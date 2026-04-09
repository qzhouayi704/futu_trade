#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略管理路由辅助函数

提供数据转换和过滤逻辑
"""

from typing import List, Dict, Any, Optional


def transform_signal_to_dict(sig) -> Dict[str, Any]:
    """将信号对象转换为字典格式"""
    return {
        'id': sig.id,
        'stock_id': sig.stock_id,
        'signal_type': sig.signal_type,
        'price': sig.signal_price,
        'reason': sig.condition_text or '',
        'timestamp': sig.created_at or '',
        'stock_code': sig.stock_code or '',
        'stock_name': sig.stock_name or '',
        'strategy_id': sig.strategy_id or '',
        'strategy_name': sig.strategy_name or '未分类'
    }


def filter_signals_by_market(
    signals: List[Dict],
    filter_markets: Optional[List[str]],
    limit: int,
    market_helper
) -> List[Dict]:
    """根据市场过滤信号

    Args:
        signals: 信号列表
        filter_markets: 市场过滤列表，None表示不过滤
        limit: 返回数量限制
        market_helper: MarketTimeHelper实例

    Returns:
        过滤后的信号列表
    """
    if not filter_markets:
        return signals[:limit]

    filtered_signals = []
    for signal in signals:
        stock_code = signal.get('stock_code', '')
        signal_market = market_helper.get_market_from_code(stock_code)

        if signal_market in filter_markets:
            filtered_signals.append(signal)

        # 达到限制数量后停止
        if len(filtered_signals) >= limit:
            break

    return filtered_signals


def aggregate_stock_plates(stock_rows: List[tuple]) -> List[Dict]:
    """聚合股票和板块信息

    Args:
        stock_rows: 数据库查询结果，格式为 (stock_id, code, name, market, plate_id, plate_name)

    Returns:
        聚合后的股票列表
    """
    stock_dict = {}
    for row in stock_rows:
        stock_id = row[0]
        stock_code = row[1]
        stock_name = row[2]
        market = row[3]
        plate_id = row[4]
        plate_name = row[5]

        if stock_code not in stock_dict:
            # 新股票，创建记录
            stock_dict[stock_code] = {
                'id': stock_id,
                'code': stock_code,
                'name': stock_name,
                'market': market,
                'plates': [],  # 板块列表
                'plate_name': ''  # 首个板块名称（用于表格显示）
            }

        # 添加板块信息
        if plate_name and plate_name not in stock_dict[stock_code]['plates']:
            stock_dict[stock_code]['plates'].append(plate_name)
            # 更新显示用的plate_name（取第一个板块）
            if not stock_dict[stock_code]['plate_name']:
                stock_dict[stock_code]['plate_name'] = plate_name

    return list(stock_dict.values())


def transform_plate_data(plate_rows: List[tuple]) -> List[Dict]:
    """转换板块数据格式

    Args:
        plate_rows: 数据库查询结果，格式为 (id, plate_code, plate_name, market, stock_count)

    Returns:
        转换后的板块列表
    """
    plates = []
    for row in plate_rows:
        plates.append({
            'id': row[0],
            'plate_code': row[1],
            'plate_name': row[2],
            'market': row[3],
            'stock_count': row[4]
        })
    return plates
