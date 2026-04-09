"""
K线数据加载器（支持API获取）

负责从数据库和API加载K线数据。
用于数据获取工具，支持从API补充缺失的数据。
"""

import pandas as pd
from typing import List, Dict, Any
from datetime import datetime, timedelta
import logging

from simple_trade.database.core.db_manager import DatabaseManager
from simple_trade.services.analysis.kline.kline_fetcher import KlineFetcher
from simple_trade.services.analysis.kline.kline_storage import KlineStorage


class KlineDataLoader:
    """K线数据加载器"""

    def __init__(
        self,
        db_manager: DatabaseManager,
        enable_api_fetch: bool = True,
        max_api_requests: int = 100
    ):
        """
        初始化K线数据加载器

        Args:
            db_manager: 数据库管理器
            enable_api_fetch: 是否启用API获取数据
            max_api_requests: 最大API请求次数限制
        """
        self.db_manager = db_manager
        self.enable_api_fetch = enable_api_fetch
        self.max_api_requests = max_api_requests
        self.logger = logging.getLogger(__name__)

        # 初始化K线服务
        self.kline_fetcher = None
        self.kline_storage = KlineStorage(db_manager)

        # API请求计数
        self._api_request_count = 0
        self._skipped_stocks = []

        # 初始化API客户端（如果启用）
        if enable_api_fetch:
            self._init_api_client()

    def _init_api_client(self):
        """初始化API客户端"""
        try:
            self.logger.info("初始化K线数据获取服务...")
            self.kline_fetcher = KlineFetcher(self.db_manager)
            self.logger.info("✅ K线数据获取服务初始化成功")
        except Exception as e:
            self.logger.warning(f"⚠️ K线数据获取服务初始化失败: {e}")
            self.logger.warning("   将只使用数据库现有数据进行回测")
            self.kline_fetcher = None

    def load_kline_data(
        self,
        stock_code: str,
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """
        加载K线数据

        Args:
            stock_code: 股票代码（如 HK.00100）
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            K线数据DataFrame
        """
        # 从数据库加载
        db_kline_data = self._load_from_db(stock_code, start_date, end_date)

        # 如果数据不足，尝试从API补充
        expected_days = self._calculate_expected_days(start_date, end_date)
        if len(db_kline_data) < expected_days:
            self.logger.info(
                f"{stock_code}: 数据库数据不足 "
                f"({len(db_kline_data)}/{expected_days}条)，尝试从API补充"
            )
            api_kline_data = self._load_from_api(
                stock_code, start_date, end_date
            )

            # 如果API获取成功，使用API数据；否则继续使用数据库数据
            if api_kline_data:
                kline_data = api_kline_data
                self.logger.info(
                    f"{stock_code}: 使用API数据 ({len(api_kline_data)}条)"
                )
            else:
                self.logger.warning(
                    f"{stock_code}: API获取失败，"
                    f"使用数据库现有数据 ({len(db_kline_data)}条)"
                )
                kline_data = db_kline_data
        else:
            kline_data = db_kline_data

        # 转换为DataFrame
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

            return filtered_data
        except Exception as e:
            self.logger.warning(f"从数据库加载K线失败 ({stock_code}): {e}")
            return []

    def _load_from_api(
        self,
        stock_code: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """从API加载K线数据"""
        # 检查是否启用API获取
        if not self.enable_api_fetch:
            self.logger.debug(f"{stock_code}: API获取已禁用")
            return []

        # 检查K线获取服务是否可用
        if not self.kline_fetcher:
            self.logger.debug(f"{stock_code}: K线获取服务不可用")
            return []

        # 检查API请求次数限制
        if self._api_request_count >= self.max_api_requests:
            self.logger.warning(
                f"{stock_code}: 已达到API请求次数限制"
                f"({self.max_api_requests})，跳过"
            )
            self._skipped_stocks.append(stock_code)
            return []

        try:
            # 计算需要的天数
            days = (end_date - start_date).days + 10  # 加10天buffer

            self.logger.info(
                f"{stock_code}: 从API获取K线数据 "
                f"({start_date.date()} 至 {end_date.date()}, {days}天)"
            )

            # 使用现有系统的KlineFetcher获取数据
            kline_data = self.kline_fetcher.fetch_kline_data(stock_code, days)

            # 增加请求计数
            self._api_request_count += 1

            if kline_data:
                # 过滤日期范围
                start_str = start_date.strftime('%Y-%m-%d')
                end_str = end_date.strftime('%Y-%m-%d')

                filtered_data = [
                    k for k in kline_data
                    if start_str <= k.get('time_key', '') <= end_str
                ]

                self.logger.info(
                    f"{stock_code}: 从API获取了 {len(filtered_data)} 条K线数据"
                )

                # 保存到数据库
                if filtered_data:
                    saved_count = self.kline_storage.save_kline_batch(
                        stock_code, kline_data
                    )
                    self.logger.debug(
                        f"{stock_code}: 已保存 {saved_count} 条K线数据到数据库"
                    )

                return filtered_data
            else:
                self.logger.warning(f"{stock_code}: API返回数据为空")
                return []

        except Exception as e:
            self.logger.error(f"{stock_code}: 从API获取K线数据失败: {e}")
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

    def _calculate_expected_days(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> int:
        """计算预期的交易日数量（粗略估计）"""
        total_days = (end_date - start_date).days
        # 假设交易日占比70%（排除周末和节假日）
        return int(total_days * 0.7)

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

    def get_api_stats(self) -> Dict[str, Any]:
        """获取API使用统计"""
        return {
            'api_request_count': self._api_request_count,
            'max_api_requests': self.max_api_requests,
            'skipped_stocks_count': len(self._skipped_stocks),
            'skipped_stocks': self._skipped_stocks[:10]  # 只返回前10个
        }
