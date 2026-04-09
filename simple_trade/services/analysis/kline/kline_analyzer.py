#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K线数据分析器

负责分析历史K线数据，计算：
- 平均换手率
- 平均成交量
- 活跃交易天数
- 历史热度分数
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from ....database.core.db_manager import DatabaseManager


class KlineAnalyzer:
    """
    K线数据分析器

    功能：
    1. 从数据库读取历史K线数据
    2. 计算平均换手率、平均成交量
    3. 统计活跃交易天数
    4. 计算历史热度分数（基于过去90天数据）
    """

    # 默认配置
    DEFAULT_ANALYSIS_DAYS = 90  # 分析过去90天
    MIN_KLINE_COUNT = 10  # 最少K线数量

    # 热度评分权重
    WEIGHT_TURNOVER_RATE = 0.4  # 换手率权重
    WEIGHT_TURNOVER_AMOUNT = 0.3  # 成交额权重
    WEIGHT_ACTIVE_DAYS = 0.3  # 活跃天数权重

    # 评分阈值
    TURNOVER_RATE_THRESHOLD = 5.0  # 换手率阈值（%）
    TURNOVER_AMOUNT_THRESHOLD = 50000000  # 成交额阈值（5000万）

    def __init__(self, db_manager: DatabaseManager):
        """
        初始化K线分析器

        Args:
            db_manager: 数据库管理器
        """
        self.db_manager = db_manager
        self.logger = logging.getLogger(__name__)

    def analyze_stock_heat(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """
        分析单只股票的历史热度

        基于数据库中已有的K线数据进行分析

        Args:
            stock_code: 股票代码

        Returns:
            Optional[Dict]: 热度数据，包含：
                - heat_score: 热度分数（0-100）
                - avg_turnover_rate: 平均换手率（%）
                - avg_volume: 平均成交量
                - active_days: 活跃天数
            如果数据不足则返回None
        """
        try:
            # 计算分析的时间范围
            end_date = datetime.now()
            start_date = end_date - timedelta(days=self.DEFAULT_ANALYSIS_DAYS)
            start_date_str = start_date.strftime('%Y-%m-%d')

            # 从数据库获取K线数据
            query = '''
                SELECT time_key, volume, turnover, turnover_rate
                FROM kline_data
                WHERE stock_code = ? AND time_key >= ?
                ORDER BY time_key DESC
            '''
            results = self.db_manager.execute_query(query, (stock_code, start_date_str))

            if not results or len(results) < self.MIN_KLINE_COUNT:
                # K线数据不足，无法分析
                return {
                    'heat_score': 0,
                    'avg_turnover_rate': 0,
                    'avg_volume': 0,
                    'active_days': len(results) if results else 0
                }

            # 计算指标
            total_volume = 0
            total_turnover = 0
            total_turnover_rate = 0
            active_days = 0

            for row in results:
                volume = float(row[1]) if row[1] else 0
                turnover = float(row[2]) if row[2] else 0
                turnover_rate = float(row[3]) if row[3] else 0

                total_volume += volume
                total_turnover += turnover
                total_turnover_rate += turnover_rate

                # 有成交量就算活跃
                if volume > 0:
                    active_days += 1

            days_count = len(results)
            avg_volume = total_volume / days_count if days_count > 0 else 0
            avg_turnover = total_turnover / days_count if days_count > 0 else 0
            avg_turnover_rate = total_turnover_rate / days_count if days_count > 0 else 0

            # 计算热度分数
            heat_score = self._calculate_historical_heat_score(
                avg_turnover_rate,
                avg_turnover,
                active_days,
                days_count
            )

            return {
                'heat_score': round(heat_score * 100, 2),  # 转换为0-100分制
                'avg_turnover_rate': round(avg_turnover_rate, 4),
                'avg_volume': round(avg_volume, 2),
                'active_days': active_days
            }

        except Exception as e:
            self.logger.warning(f"分析股票 {stock_code} 热度失败: {e}")
            return None

    def _calculate_historical_heat_score(
        self,
        avg_turnover_rate: float,
        avg_turnover: float,
        active_days: int,
        total_days: int
    ) -> float:
        """
        计算历史热度分数

        热度分 = (换手率评分 × 0.4) + (成交额评分 × 0.3) + (活跃天数评分 × 0.3)

        Args:
            avg_turnover_rate: 平均换手率（%）
            avg_turnover: 平均成交额
            active_days: 活跃天数
            total_days: 总天数

        Returns:
            float: 热度分数（0-1）
        """
        # 换手率评分：平均换手率 / 5%，上限1.0
        turnover_score = min(
            avg_turnover_rate / self.TURNOVER_RATE_THRESHOLD,
            1.0
        )

        # 成交额评分：日均成交额 / 5000万，上限1.0
        turnover_amount_score = min(
            avg_turnover / self.TURNOVER_AMOUNT_THRESHOLD,
            1.0
        )

        # 活跃天数评分：活跃天数 / 分析天数
        active_days_score = active_days / total_days if total_days > 0 else 0

        heat_score = (
            turnover_score * self.WEIGHT_TURNOVER_RATE +
            turnover_amount_score * self.WEIGHT_TURNOVER_AMOUNT +
            active_days_score * self.WEIGHT_ACTIVE_DAYS
        )

        return heat_score

    def calculate_avg_turnover(self, stock_code: str, days: int = 90) -> float:
        """
        计算平均换手率

        Args:
            stock_code: 股票代码
            days: 分析天数

        Returns:
            float: 平均换手率（%）
        """
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            start_date_str = start_date.strftime('%Y-%m-%d')

            query = '''
                SELECT AVG(turnover_rate)
                FROM kline_data
                WHERE stock_code = ? AND time_key >= ? AND turnover_rate > 0
            '''
            result = self.db_manager.execute_query(query, (stock_code, start_date_str))

            if result and result[0][0]:
                return round(float(result[0][0]), 4)
            return 0.0

        except Exception as e:
            self.logger.warning(f"计算股票 {stock_code} 平均换手率失败: {e}")
            return 0.0

    def calculate_avg_volume(self, stock_code: str, days: int = 90) -> float:
        """
        计算平均成交量

        Args:
            stock_code: 股票代码
            days: 分析天数

        Returns:
            float: 平均成交量
        """
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            start_date_str = start_date.strftime('%Y-%m-%d')

            query = '''
                SELECT AVG(volume)
                FROM kline_data
                WHERE stock_code = ? AND time_key >= ? AND volume > 0
            '''
            result = self.db_manager.execute_query(query, (stock_code, start_date_str))

            if result and result[0][0]:
                return round(float(result[0][0]), 2)
            return 0.0

        except Exception as e:
            self.logger.warning(f"计算股票 {stock_code} 平均成交量失败: {e}")
            return 0.0

    def count_active_days(self, stock_code: str, days: int = 90) -> int:
        """
        统计活跃交易天数

        Args:
            stock_code: 股票代码
            days: 分析天数

        Returns:
            int: 活跃天数
        """
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            start_date_str = start_date.strftime('%Y-%m-%d')

            query = '''
                SELECT COUNT(*)
                FROM kline_data
                WHERE stock_code = ? AND time_key >= ? AND volume > 0
            '''
            result = self.db_manager.execute_query(query, (stock_code, start_date_str))

            if result and result[0][0]:
                return int(result[0][0])
            return 0

        except Exception as e:
            self.logger.warning(f"统计股票 {stock_code} 活跃天数失败: {e}")
            return 0
