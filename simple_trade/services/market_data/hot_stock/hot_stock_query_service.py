#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
热门股票查询服务

职责：
- 持仓股票查询
- 热度计算
- 股票过滤和排序
"""

import logging
from typing import Dict, Any, List, Tuple, Optional, Set

from ....utils.converters import get_last_price
from ....database.core.db_manager import DatabaseManager


class HotStockQueryService:
    """热门股票查询与过滤服务"""

    def __init__(self, db_manager: DatabaseManager):
        self._db = db_manager

    def get_position_codes(self, futu_trade_service=None) -> Set[str]:
        """获取持仓股票代码集合

        优先从数据库查询 POSITION_MONITOR 板块，
        若无记录则尝试从交易服务获取实时持仓。
        """
        position_codes: Set[str] = set()
        try:
            rows = self._db.execute_query('''
                SELECT DISTINCT s.code FROM stocks s
                INNER JOIN stock_plates sp ON s.id = sp.stock_id
                INNER JOIN plates p ON sp.plate_id = p.id
                WHERE p.plate_code = 'POSITION_MONITOR'
            ''')
            position_codes = {row[0] for row in rows} if rows else set()

            if not position_codes and futu_trade_service is not None:
                try:
                    pos_result = futu_trade_service.get_positions()
                    if pos_result.get('success') and pos_result.get('positions'):
                        for pos in pos_result['positions']:
                            if pos.get('qty', 0) > 0:
                                position_codes.add(pos.get('stock_code', ''))
                except Exception:
                    pass
        except Exception as e:
            logging.warning(f"获取持仓股票列表失败: {e}")
        return position_codes

    @staticmethod
    def calculate_stock_heat(
        quote: Dict[str, Any],
        stock_code: str,
        cached_heat_scores: Dict[str, Dict[str, Any]],
        filter_config: Dict[str, Any],
    ) -> float:
        """计算热度分数：优先用后台已算好的热度，否则用报价实时计算"""
        if stock_code in cached_heat_scores:
            return cached_heat_scores[stock_code]['heat_score']

        turnover_rate = quote.get('turnover_rate', 0) or 0
        turnover = quote.get('turnover', 0) or 0

        turnover_rate_weight = filter_config.get('turnover_rate_weight', 0.4)
        turnover_weight = filter_config.get('turnover_weight', 0.6)
        turnover_rate_max = filter_config.get('turnover_rate_max_threshold', 5.0)
        turnover_max = filter_config.get('turnover_max_threshold', 50000000)

        rate_score = min(turnover_rate / turnover_rate_max, 1.0) * 100 if turnover_rate_max > 0 else 0
        turnover_score = min(turnover / turnover_max, 1.0) * 100 if turnover_max > 0 else 0

        return rate_score * turnover_rate_weight + turnover_score * turnover_weight

    def filter_and_sort_stocks(
        self,
        stocks_data: List[Dict[str, Any]],
        quotes_map: Dict[str, Dict[str, Any]],
        cached_heat_scores: Dict[str, Dict[str, Any]],
        filter_config: Dict[str, Any],
        min_stock_price: Dict[str, float],
        market_filter: Optional[str] = None,
        search_filter: Optional[str] = None,
        limit: int = 100,
        position_codes: Optional[Set[str]] = None,
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """过滤和排序股票

        Returns:
            (过滤后的股票列表, 过滤摘要)
        """
        filter_enabled = filter_config.get('enabled', True)
        min_volume = filter_config.get('min_volume', 100000)
        _position_codes = position_codes or set()

        filtered_stocks = []
        filter_summary: List[str] = []

        for stock in stocks_data:
            stock_code = stock['code']
            stock_market = stock.get('market', '')
            stock_name = stock.get('name', '')
            is_position = stock_code in _position_codes

            if market_filter and stock_market != market_filter:
                continue
            if search_filter and search_filter not in stock_code.lower() and search_filter not in stock_name.lower():
                continue

            quote = quotes_map.get(stock_code)
            if not quote:
                continue

            # 持仓股票跳过成交量和价格筛选
            if not is_position:
                volume = quote.get('volume', 0) or 0
                if filter_enabled and volume < min_volume:
                    if '成交量过低' not in filter_summary:
                        filter_summary.append('成交量过低')
                    continue

                cur_price = get_last_price(quote)
                min_price = min_stock_price.get(stock_market, 0)
                if filter_enabled and cur_price < min_price:
                    if '价格过低' not in filter_summary:
                        filter_summary.append('价格过低')
                    continue

            heat_score = self.calculate_stock_heat(quote, stock_code, cached_heat_scores, filter_config)
            stock['heat_score'] = heat_score
            filtered_stocks.append(stock)

        filtered_stocks.sort(key=lambda x: x.get('heat_score', 0), reverse=True)
        return filtered_stocks[:limit], filter_summary
