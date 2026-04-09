#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K线数据获取模块
负责K线额度管理、快速初始化（30天）、数据清理和代理方法
"""

import logging
import time
from typing import Dict, Any, List, Optional, Tuple

from ....database.core.db_manager import DatabaseManager
from ....config.config import Config
from ....api.futu_client import FutuClient
from ...analysis.kline import KlineFetcher, KlineParser, KlineStorage


class KlineDataFetcher:
    """K线数据获取服务"""

    def __init__(self, db_manager: DatabaseManager, futu_client: FutuClient, config: Config):
        self.db_manager = db_manager
        self.futu_client = futu_client
        self.config = config

        # 初始化子服务
        self.fetcher = KlineFetcher(futu_client, config)
        self.parser = KlineParser(db_manager)
        self.storage = KlineStorage(db_manager)

        # 频率控制器（从 fetcher 获取，保持全局一致）
        self.rate_limiter = self.fetcher.rate_limiter

    # ==================== 额度管理 ====================

    def get_quota_info(self, force_refresh: bool = False) -> Dict[str, Any]:
        """获取K线额度信息（带缓存）"""
        return self.fetcher.get_quota_info(force_refresh)

    def get_cached_quota_info(self) -> Optional[Dict[str, Any]]:
        """获取缓存的额度信息"""
        return self.fetcher.get_cached_quota_info()

    def clear_quota_cache(self):
        """清除额度缓存"""
        self.fetcher.clear_quota_cache()

    # ==================== 快速初始化（30天） ====================

    def initialize_kline_data(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        初始化K线数据（快速模式，30天）
        1. 获取并缓存K线额度信息
        2. 获取活跃股票的历史K线数据
        3. 增量更新股票池
        """
        result = {
            'success': False,
            'message': '',
            'quota_info': {},
            'stocks_processed': 0,
            'kline_records': 0,
            'new_stocks_added': 0,
            'errors': []
        }

        try:
            logging.info("开始初始化K线数据...")

            # 步骤1: 获取K线额度信息
            quota_info = self.get_quota_info(force_refresh=force_refresh)
            result['quota_info'] = quota_info

            if quota_info['status'] != 'connected' or quota_info['remaining'] <= 0:
                result['message'] = f"K线额度不足或API未连接: {quota_info['status']}"
                result['errors'].append(result['message'])
                return result

            # 步骤2: 获取股票列表
            stocks = self._get_stocks()
            if not stocks:
                result['message'] = "没有找到股票"
                return result

            # 步骤3: 批量获取K线数据
            kline_result = self._batch_get_kline_data(stocks, quota_info['remaining'])
            result.update(kline_result)

            # 步骤4: 增量更新股票池
            if result['stocks_processed'] > 0:
                update_result = self.storage.update_stock_pool(stocks)
                result['new_stocks_added'] = update_result['new_stocks_added']

            result['success'] = True
            result['message'] = (
                f"K线数据初始化完成: 处理{result['stocks_processed']}只股票，"
                f"获取{result['kline_records']}条记录，"
                f"新增{result['new_stocks_added']}只股票"
            )
            logging.info(result['message'])

        except Exception as e:
            logging.error(f"K线数据初始化失败: {e}", exc_info=True)
            result.update({
                'success': False,
                'message': f'K线数据初始化失败: {str(e)}'
            })
            result['errors'].append(str(e))

        return result

    def _get_stocks(self) -> List[Tuple]:
        """获取股票列表 - 使用配置中的数量而不是硬编码"""
        try:
            stocks = self.db_manager.stock_queries.get_stocks(self.config.max_stocks_for_kline_update)
            logging.info(f"获取到{len(stocks)}只股票")
            return stocks
        except Exception as e:
            logging.error(f"获取股票失败: {e}", exc_info=True)
            return []

    def _batch_get_kline_data(self, stocks: List[Tuple], max_quota: int) -> Dict[str, Any]:
        """批量获取K线数据（30天）"""
        result = {
            'stocks_processed': 0,
            'kline_records': 0,
            'errors': []
        }

        try:
            # 限制处理的股票数量，避免超出额度
            max_stocks = min(len(stocks), max_quota, 20)

            for i, stock in enumerate(stocks[:max_stocks]):
                try:
                    stock_code = stock[1]  # 股票代码

                    # 检查是否已有最近的K线数据
                    if self.parser.has_recent_kline_data(stock_code):
                        logging.debug(f"股票{stock_code}已有最近K线数据，跳过")
                        continue

                    # 获取K线数据（30天）
                    kline_data = self.fetcher.fetch_kline_data_with_limit(stock_code, days=30, limit_days=30)

                    if kline_data:
                        # 过滤今天的不完整数据
                        filtered_data = self.parser.filter_today_incomplete_data(stock_code, kline_data)
                        # 保存到数据库
                        saved_count = self.storage.save_kline_batch(stock_code, filtered_data)
                        result['kline_records'] += saved_count
                        logging.info(f"股票{stock_code}获取{len(kline_data)}条K线数据，保存{saved_count}条")

                    result['stocks_processed'] += 1

                    # fetcher 已内置频率控制，这里只需批次间额外延迟
                    fast_mode_delay = self.config.kline_rate_limit.get("fast_mode_delay", 0.5)
                    time.sleep(fast_mode_delay)

                except Exception as e:
                    error_msg = f"处理股票{stock[1]}失败: {e}"
                    logging.error(error_msg)
                    result['errors'].append(error_msg)

        except Exception as e:
            logging.error(f"批量获取K线数据失败: {e}", exc_info=True)
            result['errors'].append(str(e))

        return result

    # ==================== 数据清理 ====================

    def clean_today_incomplete_kline(self) -> Dict[str, Any]:
        """清理今天的不完整K线数据（考虑时差）"""
        return self.storage.clean_today_incomplete_kline()

    def clean_incomplete_kline_by_date(self, date_str: str) -> Dict[str, Any]:
        """清理指定日期的K线数据"""
        return self.storage.clean_incomplete_kline_by_date(date_str)

    # ==================== 内部方法（供其他服务调用） ====================

    def _has_enough_kline_data(self, stock_code: str, required_days: int) -> bool:
        """检查是否有足够的K线数据（代理到 parser）"""
        return self.parser.has_enough_kline_data(stock_code, required_days)

    def _fetch_kline_data(self, stock_code: str, days: int) -> List[Dict]:
        """获取K线数据（代理到 fetcher）"""
        return self.fetcher.fetch_kline_data(stock_code, days)

    def _save_kline_data(self, stock_code: str, kline_data: List[Dict]) -> int:
        """保存K线数据（代理到 storage）"""
        filtered_data = self.parser.filter_today_incomplete_data(stock_code, kline_data)
        return self.storage.save_kline_batch(stock_code, filtered_data)
