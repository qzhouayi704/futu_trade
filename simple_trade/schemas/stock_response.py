#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票响应数据构建器

将内部数据结构转换为 API 响应格式
"""

from typing import Dict, Any, Optional

from ..utils.converters import get_last_price


def build_stock_response(
    stock: Dict[str, Any],
    quote: Dict[str, Any],
    condition: Optional[Dict[str, Any]] = None,
    is_position: bool = False,
    capital_flow_data: Optional[Dict[str, Any]] = None,
    price_position_result=None,
) -> Dict[str, Any]:
    """构建股票响应数据

    Args:
        stock: 股票基础数据
        quote: 报价数据
        condition: 交易条件
        is_position: 是否持仓
        capital_flow_data: 资金流向数据
        price_position_result: PricePositionResult 价格位置分析结果（可选）

    Returns:
        股票响应数据字典
    """
    if capital_flow_data is not None:
        capital_flow_summary = {
            'main_net_inflow': capital_flow_data['main_net_inflow'],
            'big_order_buy_ratio': capital_flow_data['big_order_buy_ratio'],
            'capital_score': capital_flow_data['capital_score'],
        }
        score = capital_flow_data['capital_score']
        capital_signal = "bullish" if score >= 60 else ("bearish" if score <= 40 else "neutral")
    else:
        capital_flow_summary = None
        capital_signal = "neutral"

    last_price = get_last_price(quote)

    result = {
        'id': stock.get('id'),
        'code': stock['code'],
        'name': stock.get('name', ''),
        'market': stock.get('market', ''),
        'heat_score': stock.get('heat_score', 0),
        'cur_price': last_price,
        'last_price': last_price,
        'change_rate': quote.get('change_percent') or quote.get('change_rate', 0),
        'volume': quote.get('volume', 0),
        'turnover': quote.get('turnover', 0),
        'turnover_rate': quote.get('turnover_rate', 0),
        'amplitude': quote.get('amplitude', 0),
        'high_price': quote.get('high_price', 0),
        'low_price': quote.get('low_price', 0),
        'open_price': quote.get('open_price', 0),
        'prev_close_price': quote.get('prev_close_price') or quote.get('prev_close', 0),
        'is_position': is_position,
        'has_condition': condition is not None,
        'condition': condition,
        'capital_flow_summary': capital_flow_summary,
        'capital_signal': capital_signal,
    }

    # 双时间框架信号（价格位置分析）
    if price_position_result is not None:
        pp = price_position_result
        result.update({
            'price_position': pp.position,
            'price_level': pp.level,
            'daily_signal': pp.daily_signal,
            'daily_label': pp.daily_label,
            'intraday_signal': pp.intraday_signal,
            'intraday_label': pp.intraday_label,
            'entry_signal': pp.entry_signal,
            'entry_label': pp.entry_label,
            'warnings': pp.warnings,
        })

    return result

