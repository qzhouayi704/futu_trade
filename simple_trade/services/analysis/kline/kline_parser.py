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
        2. 最新K线日期是否是最近的交易日（不包括当天）

        【修复】更严格的日期判断：
        - 如果最新K线日期不等于预期的最近交易日，就需要更新
        - 考虑港股和美股可能有不同的交易日历

        Args:
            stock_code: 股票代码
            required_days: 需要的天数

        Returns:
            是否有足够的K线数据
        """
        try:
            # 获取股票所属市场
            market = MarketTimeHelper.get_market_from_code(stock_code)

            # 获取该市场的"今天"日期（考虑时区）
            today_str = MarketTimeHelper.get_market_today(market)

            # 计算需要的最早日期
            start_date = (datetime.now() - timedelta(days=required_days)).strftime('%Y-%m-%d')

            # 查询该日期范围内的K线记录数和最新日期（排除当天）
            result = self.db_manager.execute_query('''
                SELECT COUNT(*), MAX(time_key) FROM kline_data
                WHERE stock_code = ? AND time_key >= ? AND time_key < ?
            ''', (stock_code, start_date, today_str))

            if not result or result[0][0] == 0:
                logging.debug(f"[K线检查] {stock_code}: 无数据，需要下载")
                return False

            count = result[0][0]
            latest_date_str = result[0][1]

            # 假设交易日约占70%（去除周末和节假日）
            expected_trading_days = int(required_days * 0.7)
            min_required_count = int(expected_trading_days * 0.8)

            # 检查数量是否足够
            if count < min_required_count:
                logging.debug(f"[K线检查] {stock_code}: 数量不足 {count}/{min_required_count}，需要下载")
                return False

            # 检查最新K线日期是否是最近的交易日
            if latest_date_str:
                try:
                    latest_date = datetime.strptime(latest_date_str.split()[0], '%Y-%m-%d').date()
                    today = datetime.strptime(today_str, '%Y-%m-%d').date()

                    # 计算预期的最近交易日（不包括当天）
                    # 使用更严格的逻辑：直接回溯找到最近的工作日
                    expected_last_trading_day = today - timedelta(days=1)

                    # 跳过周末
                    while expected_last_trading_day.weekday() >= 5:  # 5=周六, 6=周日
                        expected_last_trading_day = expected_last_trading_day - timedelta(days=1)

                    # 【关键修复】更严格的日期判断
                    # 如果最新K线日期比预期的最近交易日早（哪怕只差1天），就需要更新
                    days_diff = (expected_last_trading_day - latest_date).days

                    if days_diff >= 1:
                        # 数据不是最新的，需要下载
                        logging.debug(f"[K线检查] {stock_code}: 数据过旧，最新={latest_date}, 预期={expected_last_trading_day}, 差{days_diff}天，需要下载")
                        return False

                    # 数据足够且日期最新
                    logging.debug(f"[K线检查] {stock_code}: 通过，{count}条记录, 最新={latest_date}")
                    return True

                except Exception as date_err:
                    logging.debug(f"[K线检查] {stock_code}: 解析日期失败: {date_err}，需要下载")
                    return False  # 日期解析失败时，安全起见下载新数据

            # 没有日期信息，安全起见返回需要下载
            logging.debug(f"[K线检查] {stock_code}: 无日期信息，需要下载")
            return False

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
