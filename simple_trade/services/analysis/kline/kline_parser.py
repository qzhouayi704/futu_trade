#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K线数据解析服务
负责K线数据的验证和检查
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List
from ....database.core.db_manager import DatabaseManager
from ....utils.market_helper import MarketTimeHelper


class KlineParser:
    """K线数据解析服务"""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    def has_recent_kline_data(self, stock_code: str, days: int = 3) -> bool:
        """检查是否有最近的K线数据

        Args:
            stock_code: 股票代码
            days: 检查最近N天

        Returns:
            是否有最近的K线数据
        """
        try:
            recent_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

            result = self.db_manager.execute_query('''
                SELECT COUNT(*) FROM kline_data
                WHERE stock_code = ? AND time_key >= ?
            ''', (stock_code, recent_date))

            count = result[0][0] if result else 0
            return count > 0

        except Exception as e:
            logging.error(f"检查K线数据失败: {e}", exc_info=True)
            return False

    def has_enough_kline_data(self, stock_code: str, required_days: int) -> bool:
        """检查是否已有足够且最新的K线数据

        同时检查：
        1. 数据量是否足够
        2. 最新K线日期是否足够新（3个自然日内）

        Args:
            stock_code: 股票代码
            required_days: 需要的天数

        Returns:
            是否有足够且新鲜的K线数据
        """
        try:
            # 获取股票所属市场
            market = MarketTimeHelper.get_market_from_code(stock_code)

            # 获取该市场的"今天"日期（考虑时区）
            today_str = MarketTimeHelper.get_market_today(market)

            # 查询：排除当天，按日期降序取 required_days 条
            result = self.db_manager.execute_query('''
                SELECT COUNT(*) FROM (
                    SELECT 1 FROM kline_data
                    WHERE stock_code = ? AND time_key < ?
                    ORDER BY time_key DESC
                    LIMIT ?
                )
            ''', (stock_code, today_str, required_days))

            if not result or result[0][0] == 0:
                logging.debug(f"[K线检查] {stock_code}: 无数据，需要下载")
                return False

            count = result[0][0]

            if count < required_days:
                logging.debug(f"[K线检查] {stock_code}: 数量不足 {count}/{required_days}，需要下载")
                return False

            # 【新增】时效性检查：最新K线不能太旧（超过3个自然日就认为过期）
            newest_result = self.db_manager.execute_query('''
                SELECT MAX(time_key) FROM kline_data
                WHERE stock_code = ? AND time_key < ?
            ''', (stock_code, today_str))

            if newest_result and newest_result[0][0]:
                newest_date_str = newest_result[0][0][:10]  # 取 YYYY-MM-DD
                try:
                    newest_date = datetime.strptime(newest_date_str, '%Y-%m-%d')
                    today_date = datetime.strptime(today_str, '%Y-%m-%d')
                    days_gap = (today_date - newest_date).days
                    # 超过3个自然日（考虑周末=2天，所以3天容忍长周末）
                    if days_gap > 3:
                        logging.info(
                            f"[K线检查] {stock_code}: 数据过期，最新={newest_date_str}，"
                            f"今天={today_str}，间隔{days_gap}天，需要更新"
                        )
                        return False
                except ValueError:
                    logging.warning(f"[K线检查] {stock_code}: 日期解析失败 {newest_date_str}")

            logging.debug(f"[K线检查] {stock_code}: 通过，{count}条记录")
            return True

        except Exception as e:
            logging.error(f"[K线检查] {stock_code}: 检查失败: {e}", exc_info=True)
            return False  # 出错时安全起见返回需要下载

    def validate_kline_data(self, kline_data: List[Dict[str, Any]]) -> bool:
        """验证K线数据的有效性

        Args:
            kline_data: K线数据列表

        Returns:
            数据是否有效
        """
        if not kline_data:
            return False

        try:
            for data in kline_data:
                # 检查必需字段
                required_fields = ['time_key', 'open_price', 'close_price', 'high_price', 'low_price', 'volume']
                for field in required_fields:
                    if field not in data:
                        logging.warning(f"K线数据缺少必需字段: {field}")
                        return False

                # 检查价格逻辑
                if data['high_price'] < data['low_price']:
                    logging.warning(f"K线数据异常: 最高价 < 最低价")
                    return False

                if data['high_price'] < data['open_price'] or data['high_price'] < data['close_price']:
                    logging.warning(f"K线数据异常: 最高价小于开盘价或收盘价")
                    return False

                if data['low_price'] > data['open_price'] or data['low_price'] > data['close_price']:
                    logging.warning(f"K线数据异常: 最低价大于开盘价或收盘价")
                    return False

            return True

        except Exception as e:
            logging.error(f"验证K线数据失败: {e}", exc_info=True)
            return False

    def filter_today_incomplete_data(self, stock_code: str, kline_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """过滤掉今天的不完整数据

        当天的K线数据在收盘前是不完整的，不应保存到数据库。
        只保存已收盘的完整历史数据，避免策略判断时使用不完整数据。

        根据股票所属市场的时区来判断"今天"的日期。

        Args:
            stock_code: 股票代码
            kline_data: K线数据列表

        Returns:
            过滤后的K线数据列表
        """
        filtered_data = []
        skipped_count = 0

        # 根据股票代码判断市场，获取该市场的"今天"日期
        market = MarketTimeHelper.get_market_from_code(stock_code)
        today_str = MarketTimeHelper.get_market_today(market)

        try:
            for data in kline_data:
                # 检查时间键，跳过"今天"的不完整数据（使用市场时区）
                time_key = data['time_key']
                if time_key.startswith(today_str):
                    skipped_count += 1
                    continue

                filtered_data.append(data)

            if skipped_count > 0:
                logging.debug(f"{stock_code} ({market}) 跳过{skipped_count}条当天({today_str})未完成数据")

        except Exception as e:
            logging.error(f"过滤K线数据失败: {e}", exc_info=True)
            return kline_data  # 出错时返回原始数据

        return filtered_data
