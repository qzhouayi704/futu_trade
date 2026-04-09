#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K线数据查询服务
负责所有K线数据的查询和更新操作
"""

import logging
from typing import List, Dict, Any
from ..core.connection_manager import ConnectionManager
from ..core.base_queries import BaseQueries


class KlineQueries(BaseQueries):
    """K线数据查询服务"""

    def __init__(self, conn_manager: ConnectionManager):
        """初始化K线查询服务

        Args:
            conn_manager: 连接管理器实例
        """
        super().__init__(conn_manager)

    def get_stock_kline(self, stock_code: str, days: int = 12) -> List[Dict[str, Any]]:
        """从数据库获取股票的K线数据（排除今天的不完整数据）

        根据股票所属市场的时区来判断"今天"的日期，确保返回的都是已收盘的完整数据。

        Args:
            stock_code: 股票代码
            days: 需要的天数

        Returns:
            K线数据列表，按日期升序排列
        """
        try:
            # 导入市场时间工具和数据模型
            from ...utils.market_helper import MarketTimeHelper
            from ...core.models import KlineData

            # 根据股票代码判断市场，获取该市场的"今天"日期
            market = MarketTimeHelper.get_market_from_code(stock_code)
            today_str = MarketTimeHelper.get_market_today(market)

            # 排除"今天"的数据，只返回已收盘的历史数据
            query = '''
                SELECT time_key, open_price, high_price, low_price, close_price, volume
                FROM kline_data
                WHERE stock_code = ? AND time_key < ?
                ORDER BY time_key DESC
                LIMIT ?
            '''
            rows = self.execute_query(query, (stock_code, today_str, days))

            # 使用 KlineData 数据模型转换，并按日期升序
            kline_objects = [KlineData.from_db_row(row) for row in reversed(rows)]
            kline_data = [kline.to_dict() for kline in kline_objects]

            logging.debug(f"K线查询: {stock_code} ({market}), 排除日期>={today_str}, 返回{len(kline_data)}条")
            return kline_data

        except Exception as e:
            logging.error(f"从数据库获取K线数据失败 {stock_code}: {e}")
            return []

    def get_avg_daily_turnover(self, stock_code: str, days: int = 20) -> float:
        """获取股票最近N个交易日的日均成交额

        Args:
            stock_code: 股票代码
            days: 统计天数（默认20个交易日）

        Returns:
            日均成交额，无数据时返回 0.0
        """
        try:
            from ...utils.market_helper import MarketTimeHelper

            market = MarketTimeHelper.get_market_from_code(stock_code)
            today_str = MarketTimeHelper.get_market_today(market)

            query = '''
                SELECT AVG(turnover) FROM (
                    SELECT turnover FROM kline_data
                    WHERE stock_code = ? AND time_key < ? AND turnover > 0
                    ORDER BY time_key DESC
                    LIMIT ?
                )
            '''
            rows = self.execute_query(query, (stock_code, today_str, days))
            if rows and rows[0][0] is not None:
                return float(rows[0][0])
            return 0.0

        except Exception as e:
            logging.error(f"获取日均成交额失败 {stock_code}: {e}")
            return 0.0

    def get_latest_kline_date(self, stock_code: str) -> str:
        """获取股票最新K线日期

        Args:
            stock_code: 股票代码

        Returns:
            最新日期字符串，无数据时返回空字符串
        """
        try:
            query = '''
                SELECT time_key FROM kline_data
                WHERE stock_code = ?
                ORDER BY time_key DESC LIMIT 1
            '''
            rows = self.execute_query(query, (stock_code,))
            if rows and rows[0][0]:
                return str(rows[0][0]).split()[0]
            return ""
        except Exception as e:
            logging.error(f"获取最新K线日期失败 {stock_code}: {e}")
            return ""

    def get_kline_count(self, stock_code: str, days: int = 30) -> int:
        """获取指定股票在最近N天内的K线记录数

        Args:
            stock_code: 股票代码
            days: 天数范围

        Returns:
            K线记录数
        """
        try:
            from datetime import datetime, timedelta
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

            query = '''
                SELECT COUNT(*) FROM kline_data
                WHERE stock_code = ? AND time_key >= ?
            '''
            result = self.execute_query(query, (stock_code, start_date))
            return result[0][0] if result else 0

        except Exception as e:
            logging.error(f"获取K线数量失败 {stock_code}: {e}")
            return 0

    def get_stocks_with_kline_data(self, min_days: int = 12) -> List[str]:
        """获取有足够K线数据的股票代码列表

        用于K线额度不足时，只筛选已有K线数据的股票进行策略判断

        Args:
            min_days: 最少需要的K线天数（默认12天，对应低吸高抛策略需求）

        Returns:
            有足够K线数据的股票代码列表
        """
        try:
            from datetime import datetime, timedelta

            # 计算查询的起始日期
            start_date = (datetime.now() - timedelta(days=min_days + 30)).strftime('%Y-%m-%d')
            today_str = datetime.now().strftime('%Y-%m-%d')

            # 查询有足够K线数据的股票（按K线数量分组，排除今天的不完整数据）
            # 假设交易日约占70%，所以需要的K线数至少是 min_days * 0.7
            min_required_count = int(min_days * 0.7)

            query = '''
                SELECT stock_code, COUNT(*) as kline_count
                FROM kline_data
                WHERE time_key >= ? AND time_key < ?
                GROUP BY stock_code
                HAVING kline_count >= ?
            '''

            rows = self.execute_query(query, (start_date, today_str, min_required_count))

            stock_codes = [row[0] for row in rows]

            logging.info(f"查询到 {len(stock_codes)} 只股票有足够的K线数据（>= {min_required_count} 条）")

            return stock_codes

        except Exception as e:
            logging.error(f"获取有K线数据的股票列表失败: {e}")
            return []

    def get_stocks_kline_status(self, stock_codes: List[str], min_days: int = 12) -> Dict[str, bool]:
        """批量检查股票是否有足够的K线数据

        Args:
            stock_codes: 股票代码列表
            min_days: 最少需要的K线天数

        Returns:
            股票代码到是否有足够K线数据的映射
        """
        try:
            from datetime import datetime, timedelta

            if not stock_codes:
                return {}

            start_date = (datetime.now() - timedelta(days=min_days + 30)).strftime('%Y-%m-%d')
            today_str = datetime.now().strftime('%Y-%m-%d')
            min_required_count = int(min_days * 0.7)

            # 构建 IN 查询
            placeholders = ','.join(['?' for _ in stock_codes])
            query = f'''
                SELECT stock_code, COUNT(*) as kline_count
                FROM kline_data
                WHERE stock_code IN ({placeholders})
                  AND time_key >= ? AND time_key < ?
                GROUP BY stock_code
            '''

            params = list(stock_codes) + [start_date, today_str]
            rows = self.execute_query(query, tuple(params))

            # 构建结果映射
            kline_counts = {row[0]: row[1] for row in rows}
            result = {code: kline_counts.get(code, 0) >= min_required_count for code in stock_codes}

            return result

        except Exception as e:
            logging.error(f"批量检查K线状态失败: {e}")
            return {code: False for code in stock_codes}
