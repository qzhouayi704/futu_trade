#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
板块概览服务

负责获取和计算板块概览数据：
- 板块股票数量统计
- 板块市场热度计算
- 板块平均涨跌幅
"""

import logging
from typing import Dict, Any, List
from ....database.core.db_manager import DatabaseManager
from ....utils.converters import get_last_price


class PlateOverviewService:
    """
    板块概览服务

    功能：
    1. 获取目标板块列表（只包含启用的板块）
    2. 统计每个板块的股票数量和热门股数量
    3. 计算板块市场热度（上涨股票占比）
    4. 计算板块平均涨跌幅
    """

    def __init__(self, db_manager: DatabaseManager):
        """
        初始化板块概览服务

        Args:
            db_manager: 数据库管理器
        """
        self.db_manager = db_manager
        self.logger = logging.getLogger(__name__)

    def get_plate_overview(self, active_markets: List[str] = None) -> List[Dict[str, Any]]:
        """获取板块概览（含股票数量、热门股数量和市场热度）"""
        plates = []

        try:
            if not active_markets:
                query = '''
                    SELECT p.id, p.plate_code, p.plate_name, p.market, p.category,
                           COUNT(DISTINCT sp.stock_id) as total_stocks,
                           COUNT(DISTINCT CASE WHEN s.heat_score > 0 THEN s.id END) as hot_stocks
                    FROM plates p
                    LEFT JOIN stock_plates sp ON p.id = sp.plate_id
                    LEFT JOIN stocks s ON sp.stock_id = s.id
                    WHERE p.is_target = 1 AND COALESCE(p.is_enabled, 1) = 1
                    GROUP BY p.id, p.plate_code, p.plate_name, p.market, p.category
                    ORDER BY p.priority DESC, p.plate_name
                '''
                results = self.db_manager.execute_query(query)
            else:
                market_placeholders = ','.join(['?' for _ in active_markets])
                query = f'''
                    SELECT p.id, p.plate_code, p.plate_name, p.market, p.category,
                           COUNT(DISTINCT sp.stock_id) as total_stocks,
                           COUNT(DISTINCT CASE WHEN s.heat_score > 0 THEN s.id END) as hot_stocks
                    FROM plates p
                    LEFT JOIN stock_plates sp ON p.id = sp.plate_id
                    LEFT JOIN stocks s ON sp.stock_id = s.id
                    WHERE p.is_target = 1 AND COALESCE(p.is_enabled, 1) = 1
                      AND p.market IN ({market_placeholders})
                    GROUP BY p.id, p.plate_code, p.plate_name, p.market, p.category
                    ORDER BY p.priority DESC, p.plate_name
                '''
                results = self.db_manager.execute_query(query, tuple(active_markets))

            for row in results:
                plates.append({
                    'id': row[0], 'plate_code': row[1], 'plate_name': row[2],
                    'market': row[3], 'category': row[4] or '',
                    'total_stocks': row[5] or 0, 'hot_stocks': row[6] or 0,
                    'heat_value': 0, 'avg_change': 0
                })

            self.logger.debug(f"获取到 {len(plates)} 个板块（市场: {active_markets}）")

        except Exception as e:
            self.logger.error(f"获取板块概览失败: {e}")

        return plates

    def get_plate_stocks_map(self, plate_ids: List[int]) -> Dict[int, List[str]]:
        """
        获取板块-股票映射

        Args:
            plate_ids: 板块ID列表

        Returns:
            Dict[板块ID, 股票代码列表]
        """
        plate_stocks: Dict[int, List[str]] = {}

        try:
            if not plate_ids:
                return plate_stocks

            placeholders = ','.join(['?' for _ in plate_ids])
            query = f'''
                SELECT sp.plate_id, s.code
                FROM stock_plates sp
                INNER JOIN stocks s ON sp.stock_id = s.id
                WHERE sp.plate_id IN ({placeholders})
            '''
            results = self.db_manager.execute_query(query, tuple(plate_ids))

            for row in results:
                plate_id, stock_code = row[0], row[1]
                if plate_id not in plate_stocks:
                    plate_stocks[plate_id] = []
                plate_stocks[plate_id].append(stock_code)

            self.logger.debug(
                f"获取到 {len(plate_stocks)} 个板块的股票映射，"
                f"共 {sum(len(codes) for codes in plate_stocks.values())} 只股票"
            )

        except Exception as e:
            self.logger.error(f"获取板块股票映射失败: {e}")

        return plate_stocks

    def calculate_plate_heat(
        self,
        plates: List[Dict[str, Any]],
        quotes_map: Dict[str, Dict[str, Any]]
    ) -> None:
        """
        计算板块市场热度

        热度计算逻辑：
        1. 获取每个板块的股票代码
        2. 从报价数据中获取涨跌幅
        3. 计算上涨股票占比作为热度值
        4. 计算平均涨跌幅

        Args:
            plates: 板块列表，会直接修改其中的 heat_value 和 avg_change 字段
            quotes_map: 股票代码 -> 报价数据的映射
        """
        try:
            # 获取所有板块的股票代码映射
            plate_ids = [p['id'] for p in plates]
            if not plate_ids:
                self.logger.warning("没有板块需要计算热度")
                return

            self.logger.debug(f"开始计算 {len(plate_ids)} 个板块的市场热度")

            # 查询每个板块的股票代码
            plate_stocks = self.get_plate_stocks_map(plate_ids)

            if not plate_stocks:
                self.logger.warning("没有找到板块关联的股票代码")
                return

            if not quotes_map:
                self.logger.debug("未提供报价数据，热度值将保持为0")
                return

            # 计算每个板块的热度
            calculated_count = 0
            for plate in plates:
                plate_id = plate['id']
                plate_name = plate.get('plate_name', 'Unknown')
                stock_codes = plate_stocks.get(plate_id, [])

                if not stock_codes:
                    continue

                up_count = 0
                total_change = 0.0
                valid_count = 0

                for code in stock_codes:
                    quote = quotes_map.get(code)
                    if quote and 'change_percent' in quote:
                        change = quote['change_percent']
                        total_change += change
                        valid_count += 1
                        if change > 0:
                            up_count += 1

                # 计算热度值（上涨股票占比）
                if valid_count > 0:
                    plate['heat_value'] = round(up_count / valid_count * 100, 1)
                    plate['avg_change'] = round(total_change / valid_count, 2)
                    calculated_count += 1
                    self.logger.debug(
                        f"板块 {plate_name}: 热度={plate['heat_value']}%, "
                        f"平均涨跌={plate['avg_change']}%, "
                        f"有效股票={valid_count}/{len(stock_codes)}"
                    )

            self.logger.debug(f"板块热度计算完成，成功计算 {calculated_count}/{len(plates)} 个板块")

        except Exception as e:
            self.logger.error(f"计算板块热度失败: {e}", exc_info=True)

    def get_realtime_quotes_from_cache(self, stock_codes: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        从状态管理器的缓存获取实时报价

        Args:
            stock_codes: 股票代码列表

        Returns:
            Dict[股票代码, 报价数据]
        """
        quotes_map = {}

        try:
            # 从状态管理器获取已订阅股票的缓存报价
            from ....core.state import get_state_manager
            state = get_state_manager()
            cached_quotes = state.get_cached_quotes() or []

            if not cached_quotes:
                self.logger.debug("报价缓存为空，可能监控未启动")
                return quotes_map

            # 构建代码集合用于快速查找
            stock_codes_set = set(stock_codes)

            for quote in cached_quotes:
                if not isinstance(quote, dict):
                    continue

                code = quote.get('code', '')
                if code not in stock_codes_set:
                    continue

                last_price = get_last_price(quote)
                prev_close = float(quote.get('prev_close_price', 0) or 0)

                # 计算涨跌幅
                change_percent = 0.0
                if 'change_percent' in quote or 'change_rate' in quote:
                    change_percent = float(
                        quote.get('change_percent') or quote.get('change_rate', 0) or 0
                    )
                elif prev_close > 0 and last_price > 0:
                    change_percent = ((last_price - prev_close) / prev_close) * 100

                quotes_map[code] = {
                    'last_price': last_price,
                    'prev_close': prev_close,
                    'change_percent': round(change_percent, 2)
                }

            self.logger.debug(f"从缓存获取 {len(quotes_map)}/{len(stock_codes)} 只股票的报价")

        except Exception as e:
            self.logger.error(f"获取实时报价失败: {e}", exc_info=True)

        return quotes_map
