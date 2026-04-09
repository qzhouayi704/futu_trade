"""
回测专用K线数据加载器

只从数据库加载数据，不包含任何API获取逻辑。
用于策略回测，确保回测过程不会触发API请求。
"""

import pandas as pd
from typing import List, Dict, Any
from datetime import datetime, timedelta
import logging

from simple_trade.database.core.db_manager import DatabaseManager


class BacktestKlineLoader:
    """回测专用K线数据加载器（只读数据库）"""

    def __init__(self, db_manager: DatabaseManager):
        """
        初始化回测K线数据加载器

        Args:
            db_manager: 数据库管理器
        """
        self.db_manager = db_manager
        self.logger = logging.getLogger(__name__)

    def load_kline_data(
        self,
        stock_code: str,
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """
        从数据库加载K线数据

        Args:
            stock_code: 股票代码（如 HK.00100）
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            K线数据DataFrame
        """
        kline_data = self._load_from_db(stock_code, start_date, end_date)
        return self._convert_to_dataframe(kline_data)

    def _load_from_db(
        self,
        stock_code: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """从数据库加载K线数据"""
        try:
            # 计算需要的天数（加上buffer）
            days = (end_date - start_date).days + 30

            # 查询数据库
            kline_data = self.db_manager.kline_queries.get_stock_kline(stock_code, days=days)

            # 过滤日期范围
            start_str = start_date.strftime('%Y-%m-%d')
            end_str = end_date.strftime('%Y-%m-%d')

            filtered_data = [
                k for k in kline_data
                if start_str <= k.get('time_key', '') <= end_str
            ]

            if not filtered_data:
                self.logger.warning(
                    f"{stock_code}: 数据库中没有找到 "
                    f"{start_str} 至 {end_str} 的K线数据"
                )

            return filtered_data
        except Exception as e:
            self.logger.warning(f"从数据库加载K线失败 ({stock_code}): {e}")
            return []

    def _convert_to_dataframe(
        self,
        kline_data: List[Dict[str, Any]]
    ) -> pd.DataFrame:
        """将K线数据转换为DataFrame"""
        if not kline_data:
            return pd.DataFrame()

        df = pd.DataFrame(kline_data)

        # 确保包含必要的列
        required_cols = [
            'time_key', 'open_price', 'close_price', 'high_price',
            'low_price', 'volume', 'turnover', 'turnover_rate'
        ]

        for col in required_cols:
            if col not in df.columns:
                df[col] = 0.0

        # 按日期排序
        df = df.sort_values('time_key')

        return df

    def get_kline_at_date(
        self,
        stock_code: str,
        date: datetime,
        lookback_days: int,
        cache_manager
    ) -> List[Dict[str, Any]]:
        """
        获取指定日期及之前N天的K线数据

        Args:
            stock_code: 股票代码
            date: 目标日期
            lookback_days: 回看天数
            cache_manager: 缓存管理器

        Returns:
            K线数据列表（按时间倒序）
        """
        # 计算开始日期（加上buffer）
        start_date = date - timedelta(days=lookback_days * 2)
        end_date = date

        # 加载K线（使用缓存）
        cache_key = f"{stock_code}_{start_date.date()}_{end_date.date()}"
        df = cache_manager.get_kline_cache(cache_key)

        if df is None:
            df = self.load_kline_data(stock_code, start_date, end_date)
            cache_manager.set_kline_cache(cache_key, df)

        if df.empty:
            return []

        # 过滤到目标日期
        date_str = date.strftime('%Y-%m-%d')
        df = df[df['time_key'] <= date_str]

        # 取最近N天
        df = df.tail(lookback_days)

        # 转换为字典列表
        return df.to_dict('records')
