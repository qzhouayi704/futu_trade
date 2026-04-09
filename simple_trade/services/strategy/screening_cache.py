#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
筛选结果缓存管理

职责：
- 管理筛选结果缓存
- 管理K线数据可用性缓存
- 管理热门股票集合
- 管理持仓股票集合
"""

import logging
from datetime import datetime
from typing import Dict, List, Any, Optional, Set

from ...database.core.db_manager import DatabaseManager
from ...config.config import Config
from ...core.state import get_state_manager
from ...utils.converters import get_last_price


class ScreeningCache:
    """
    筛选结果缓存管理器

    负责管理各种缓存数据：
    1. 筛选结果缓存
    2. K线数据可用性缓存
    3. 热门股票集合缓存
    4. 持仓股票集合
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        config: Config,
        futu_trade_service=None
    ):
        self.db_manager = db_manager
        self.config = config
        self.futu_trade_service = futu_trade_service

        # 筛选结果缓存
        self._screening_results: Dict[str, Any] = {}
        self._last_screening_time: Optional[datetime] = None

        # K线数据状态缓存
        self._stocks_with_kline: Set[str] = set()  # 有K线数据的股票集合
        self._kline_cache_time: Optional[datetime] = None
        self._kline_cache_valid_minutes: int = 30  # K线缓存有效时间（分钟）

        # 热门股票集合缓存（用于过滤首页信号，只显示热门股票的信号）
        self._hot_stock_codes: Set[str] = set()
        self._hot_stocks_cache_time: Optional[datetime] = None
        self._hot_stocks_cache_valid_minutes: int = 5  # 热门股票缓存有效时间（分钟）

        # 持仓股票集合（持仓股票的信号也需要显示）
        self._position_codes: Set[str] = set()

        logging.info("筛选结果缓存管理器初始化完成")

    def update_screening_results(self, results: Dict[str, Any]) -> None:
        """更新筛选结果缓存"""
        self._screening_results = results
        self._last_screening_time = datetime.now()

    def get_screening_results(self) -> Dict[str, Any]:
        """获取筛选结果缓存"""
        return self._screening_results

    def get_last_screening_time(self) -> Optional[datetime]:
        """获取最后筛选时间"""
        return self._last_screening_time

    def get_stock_result(self, stock_code: str) -> Optional[Any]:
        """获取单只股票的筛选结果"""
        return self._screening_results.get(stock_code)

    def get_stocks_with_kline_data(
        self,
        required_days: int,
        force_refresh: bool = False
    ) -> Set[str]:
        """获取有足够K线数据的股票集合（带缓存）

        Args:
            required_days: 策略需要的K线天数
            force_refresh: 是否强制刷新缓存

        Returns:
            有K线数据的股票代码集合
        """
        try:
            # 检查缓存是否有效
            if not force_refresh and self._is_kline_cache_valid():
                return self._stocks_with_kline

            # 从数据库获取有足够K线数据的股票
            stock_codes = self.db_manager.kline_queries.get_stocks_with_kline_data(min_days=required_days)

            # 更新缓存
            self._stocks_with_kline = set(stock_codes)
            self._kline_cache_time = datetime.now()

            logging.info(f"更新K线数据缓存: {len(self._stocks_with_kline)}只股票有足够K线数据")

            return self._stocks_with_kline

        except Exception as e:
            logging.error(f"获取有K线数据的股票失败: {e}")
            return self._stocks_with_kline  # 返回旧缓存

    def _is_kline_cache_valid(self) -> bool:
        """检查K线缓存是否有效"""
        if not self._kline_cache_time or not self._stocks_with_kline:
            return False

        elapsed_minutes = (datetime.now() - self._kline_cache_time).total_seconds() / 60
        return elapsed_minutes < self._kline_cache_valid_minutes

    def refresh_kline_cache(self, required_days: int) -> int:
        """强制刷新K线数据缓存

        Args:
            required_days: 策略需要的K线天数

        Returns:
            有K线数据的股票数量
        """
        # 清除缓存时间，强制下次调用时刷新
        self._kline_cache_time = None

        # 重新获取
        stocks_with_kline = self.get_stocks_with_kline_data(required_days, force_refresh=True)

        logging.info(f"K线数据缓存已刷新: {len(stocks_with_kline)}只股票有足够数据")

        return len(stocks_with_kline)

    def get_hot_stock_codes(self) -> Set[str]:
        """获取热门股票代码集合（Top 100）

        从 state_manager 的缓存报价中计算热门股票

        Returns:
            热门股票代码集合
        """
        try:
            # 检查缓存是否有效
            if self._is_hot_stocks_cache_valid():
                return self._hot_stock_codes

            # 从 state_manager 获取缓存的报价
            state = get_state_manager()
            cached_quotes = state.get_cached_quotes() or []

            if not cached_quotes:
                logging.debug("无缓存报价数据，热门股票集合为空")
                return set()

            # 获取筛选配置
            from ...utils.market_helper import MarketTimeHelper
            active_markets = MarketTimeHelper.get_current_active_markets()

            # 从配置读取筛选参数
            filter_config = getattr(self.config, 'realtime_hot_filter', None) or {}
            min_volume = filter_config.get('min_volume', 100000)
            turnover_rate_weight = filter_config.get('turnover_rate_weight', 0.4)
            turnover_weight = filter_config.get('turnover_weight', 0.6)
            turnover_rate_max = filter_config.get('turnover_rate_max_threshold', 5.0)
            turnover_max = filter_config.get('turnover_max_threshold', 50000000)
            min_stock_price = getattr(self.config, 'min_stock_price', None) or {'HK': 1.0, 'US': 0}

            # 计算热度分并筛选
            hot_candidates = []
            for quote in cached_quotes:
                if not isinstance(quote, dict):
                    continue

                code = quote.get('code', '')
                if not code:
                    continue

                # 市场筛选
                market = 'HK' if code.startswith('HK.') else 'US' if code.startswith('US.') else ''
                if market not in active_markets:
                    continue

                # 成交量筛选
                volume = quote.get('volume', 0) or 0
                if volume < min_volume:
                    continue

                # 价格筛选
                cur_price = get_last_price(quote)
                min_price = min_stock_price.get(market, 0)
                if min_price > 0 and cur_price < min_price:
                    continue

                # 计算热度分
                turnover_rate = quote.get('turnover_rate', 0) or 0
                turnover = quote.get('turnover', 0) or 0
                rate_score = min(turnover_rate / turnover_rate_max, 1.0) * 100 if turnover_rate_max > 0 else 0
                turnover_score = min(turnover / turnover_max, 1.0) * 100 if turnover_max > 0 else 0
                heat_score = rate_score * turnover_rate_weight + turnover_score * turnover_weight

                hot_candidates.append((code, heat_score))

            # 按热度分排序，取前100
            hot_candidates.sort(key=lambda x: x[1], reverse=True)
            self._hot_stock_codes = {code for code, _ in hot_candidates[:100]}
            self._hot_stocks_cache_time = datetime.now()

            logging.info(f"更新热门股票缓存: {len(self._hot_stock_codes)} 只热门股票")

            return self._hot_stock_codes

        except Exception as e:
            logging.error(f"获取热门股票集合失败: {e}")
            return self._hot_stock_codes  # 返回旧缓存

    def _is_hot_stocks_cache_valid(self) -> bool:
        """检查热门股票缓存是否有效"""
        if not self._hot_stocks_cache_time or not self._hot_stock_codes:
            return False

        elapsed_minutes = (datetime.now() - self._hot_stocks_cache_time).total_seconds() / 60
        return elapsed_minutes < self._hot_stocks_cache_valid_minutes

    def get_position_codes(self) -> Set[str]:
        """获取持仓股票代码集合

        Returns:
            持仓股票代码集合
        """
        try:
            # 从持仓监控板块获取
            position_stocks = self.db_manager.execute_query('''
                SELECT DISTINCT s.code FROM stocks s
                INNER JOIN stock_plates sp ON s.id = sp.stock_id
                INNER JOIN plates p ON sp.plate_id = p.id
                WHERE p.plate_code = 'POSITION_MONITOR'
            ''')

            self._position_codes = {row[0] for row in position_stocks} if position_stocks else set()

            if self._position_codes:
                logging.debug(f"获取到 {len(self._position_codes)} 只持仓股票")

            return self._position_codes

        except Exception as e:
            logging.debug(f"获取持仓股票失败（可忽略）: {e}")
            return self._position_codes

    def get_actual_position_codes(self) -> Set[str]:
        """从富途API获取实际持仓股票代码

        直接调用富途交易API获取当前持仓，这是最准确的方式。
        如果API调用失败，降级到从 POSITION_MONITOR 板块获取。

        Returns:
            实际持仓股票代码集合
        """
        try:
            # 如果有 futu_trade_service，直接调用API获取持仓
            if self.futu_trade_service:
                positions_result = self.futu_trade_service.get_positions()

                if positions_result['success']:
                    position_codes = {
                        pos['stock_code']
                        for pos in positions_result['positions']
                        if pos.get('qty', 0) > 0
                    }

                    if position_codes:
                        logging.debug(f"从富途API获取到 {len(position_codes)} 只实际持仓股票")

                    return position_codes
                else:
                    logging.debug(f"获取富途持仓失败，使用降级方案: {positions_result['message']}")

            # 降级方案：从 POSITION_MONITOR 板块获取
            return self.get_position_codes()

        except Exception as e:
            logging.error(f"获取实际持仓股票失败: {e}")
            return self.get_position_codes()  # 降级到板块方式

    def is_hot_stock(self, stock_code: str) -> bool:
        """判断股票是否是热门股票（或持仓股票）

        Args:
            stock_code: 股票代码

        Returns:
            True 如果是热门股票或持仓股票
        """
        hot_codes = self.get_hot_stock_codes()
        position_codes = self.get_position_codes()
        return stock_code in hot_codes or stock_code in position_codes

    def get_hot_stock_filter_info(self) -> Dict[str, Any]:
        """获取热门股票过滤信息

        Returns:
            过滤器状态信息
        """
        hot_codes = self.get_hot_stock_codes()
        position_codes = self.get_position_codes()

        return {
            'hot_stocks_count': len(hot_codes),
            'position_stocks_count': len(position_codes),
            'total_allowed': len(hot_codes | position_codes),
            'cache_valid': self._is_hot_stocks_cache_valid(),
            'cache_time': self._hot_stocks_cache_time.isoformat() if self._hot_stocks_cache_time else None,
            'cache_valid_minutes': self._hot_stocks_cache_valid_minutes
        }

    def get_kline_cache_info(self) -> Dict[str, Any]:
        """获取K线缓存信息

        Returns:
            K线缓存状态信息
        """
        return {
            'stocks_with_kline': len(self._stocks_with_kline),
            'kline_cache_valid': self._is_kline_cache_valid(),
            'kline_cache_time': self._kline_cache_time.isoformat() if self._kline_cache_time else None,
            'kline_cache_valid_minutes': self._kline_cache_valid_minutes
        }
