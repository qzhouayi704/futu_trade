#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时数据查询模块 - 负责实时行情和订阅状态的查询

从 realtime_service.py 拆分而来，包含：
- 实时行情查询
- K线数据查询
- 已订阅股票信息查询
- 订阅状态检查
"""

import logging
from typing import Dict, Any, List, Optional

from ...database.core.db_manager import DatabaseManager
from ...api.futu_client import FutuClient
from ...api.subscription_manager import SubscriptionManager
from ...api.quote_service import QuoteService
from .realtime_kline_service import RealtimeKlineService
from .realtime_stock_query_service import RealtimeStockQueryService
from .realtime_quote_service_wrapper import RealtimeQuoteServiceWrapper
from ..subscription.subscription_version import SubscriptionVersionService


class RealtimeQuery:
    """实时数据查询服务 - 负责行情和订阅状态的查询"""

    def __init__(self, db_manager: DatabaseManager, futu_client: FutuClient,
                 subscription_manager: SubscriptionManager = None,
                 quote_service: QuoteService = None, config=None):
        self.db_manager = db_manager
        self.subscription_manager = subscription_manager

        self.kline_service = RealtimeKlineService(
            db_manager=db_manager,
            futu_client=futu_client
        )
        self.stock_query_service = RealtimeStockQueryService(
            db_manager=db_manager,
            futu_client=futu_client,
            config=config
        )
        self.quote_service_wrapper = RealtimeQuoteServiceWrapper(
            futu_client=futu_client,
            quote_service=quote_service,
            config=config
        )
        self.version_service = SubscriptionVersionService(db_manager=db_manager)

    @property
    def subscribed_stocks(self) -> set:
        """获取已订阅股票集合（委托给 SubscriptionManager）"""
        if self.subscription_manager:
            return self.subscription_manager.subscribed_stocks
        return set()

    def get_target_stocks(self, limit: Optional[int] = None,
                         markets: Optional[List[str]] = None,
                         kline_priority: bool = True) -> List[Dict[str, Any]]:
        """从全局股票池获取目标股票 - 委托给 RealtimeStockQueryService"""
        return self.stock_query_service.get_target_stocks(limit, markets, kline_priority)

    def get_realtime_quotes(self, stock_codes: Optional[List[str]] = None) -> Dict[str, Any]:
        """获取实时行情数据 - 委托给 RealtimeQuoteServiceWrapper"""
        if stock_codes is None:
            if not self.subscribed_stocks:
                target_stocks = self.get_target_stocks()
                stock_codes = [stock['code'] for stock in target_stocks]
            else:
                stock_codes = None  # 让 wrapper 处理

        return self.quote_service_wrapper.get_realtime_quotes(
            stock_codes, subscribed_stocks=self.subscribed_stocks
        )

    def fetch_and_save_kline_data(self, stock_codes: Optional[List[str]] = None,
                                  ktype: str = 'K_DAY',
                                  limit: int = 100) -> Dict[str, Any]:
        """获取并保存K线数据 - 委托给 RealtimeKlineService"""
        if stock_codes is None:
            target_stocks = self.get_target_stocks()
            stock_codes = [stock['code'] for stock in target_stocks]
        return self.kline_service.fetch_and_save_kline_data(stock_codes, ktype, limit)

    def get_stock_kline_from_db(self, stock_code: str,
                                limit: int = 100) -> Dict[str, Any]:
        """从数据库获取股票K线数据 - 委托给 RealtimeKlineService"""
        return self.kline_service.get_stock_kline_from_db(stock_code, limit)

    def get_subscribed_stocks(self) -> List[str]:
        """获取已订阅的股票列表"""
        return list(self.subscribed_stocks)

    def get_subscribed_stocks_info(self) -> List[Dict[str, Any]]:
        """获取已订阅股票的完整信息"""
        stocks_info = []

        try:
            if not self.subscribed_stocks:
                logging.info("没有已订阅的股票")
                return stocks_info

            placeholders = ','.join(['?' for _ in self.subscribed_stocks])
            sql = f'''
                SELECT DISTINCT s.id, s.code, s.name, s.market,
                       p.plate_name, p.priority
                FROM stocks s
                INNER JOIN stock_plates sp ON s.id = sp.stock_id
                INNER JOIN plates p ON sp.plate_id = p.id
                WHERE s.code IN ({placeholders})
                ORDER BY p.priority DESC, s.name ASC
            '''

            rows = self.db_manager.execute_query(
                sql, tuple(self.subscribed_stocks)
            )

            for row in rows:
                stocks_info.append({
                    'id': row[0], 'code': row[1], 'name': row[2],
                    'market': row[3], 'plate_name': row[4], 'priority': row[5]
                })

            if stocks_info:
                logging.info(f"获取到 {len(stocks_info)} 只已订阅股票的详细信息")
            else:
                logging.warning(
                    f"数据库中未找到已订阅股票的信息，"
                    f"订阅列表: {list(self.subscribed_stocks)}"
                )
                stocks_info = self._build_fallback_info()

        except Exception as e:
            logging.error(f"获取已订阅股票信息失败: {e}", exc_info=True)
            stocks_info = self._build_fallback_info()

        return stocks_info

    def check_subscription_status(self) -> Dict[str, Any]:
        """检查订阅状态和股票池变更 - 委托给 SubscriptionVersionService"""
        return self.version_service.check_subscription_status()

    def _build_fallback_info(self) -> List[Dict[str, Any]]:
        """构建兜底的股票信息（当数据库查询失败时）"""
        return [
            {
                'id': 0, 'code': code, 'name': code,
                'market': 'Unknown', 'plate_name': '', 'priority': 10
            }
            for code in self.subscribed_stocks
        ]
