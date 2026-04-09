#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时大单追踪器

职责：
1. 追踪实时逐笔成交数据
2. 识别大单交易（单笔成交额超过阈值）
3. 计算大单买卖比
4. 评估大单强度
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional


class BigOrderTracker:
    """实时大单追踪器"""

    def __init__(self, futu_client=None, db_manager=None, config: dict = None, *, ctx=None):
        """
        初始化大单追踪器

        Args:
            ctx: AnalysisContext（推荐）
            futu_client: 富途API客户端（向后兼容）
            db_manager: 数据库管理器（向后兼容）
            config: 配置字典（向后兼容）
        """
        if ctx is not None:
            self.futu_client = ctx.futu_client
            self.db_manager = ctx.db_manager
            self.config = ctx.enhanced_heat_config
        else:
            self.futu_client = futu_client
            self.db_manager = db_manager
            self.config = (config or {}).get('enhanced_heat_config', {})
        self.big_order_config = self.config.get('big_order_config', {})

        # 配置参数
        self.enabled = self.big_order_config.get('enabled', True)
        self.track_top_n = self.big_order_config.get('track_top_n', 20)
        self.min_order_amount = self.big_order_config.get('min_order_amount', 100000)
        self.update_interval = self.big_order_config.get('update_interval', 60)

        # 已订阅 Ticker 的股票集合，避免重复订阅
        self._ticker_subscribed: set = set()
        # 订阅失败的股票集合，避免重复尝试
        self._ticker_failed: set = set()

    def _ensure_ticker_subscribed(self, stock_code: str):
        """确保已订阅该股票的 Ticker 数据（富途要求先订阅才能获取逐笔成交）"""
        # 跳过已订阅或已知失败的股票
        if stock_code in self._ticker_subscribed or stock_code in self._ticker_failed:
            return
        try:
            from futu import SubType, RET_OK
            client = self.futu_client.client if hasattr(self.futu_client, 'client') else self.futu_client
            if client is None:
                return
            ret, err = client.subscribe([stock_code], [SubType.TICKER])
            if ret == RET_OK:
                self._ticker_subscribed.add(stock_code)
                logging.debug(f"已订阅 Ticker: {stock_code}")
            else:
                # 记录失败的股票，避免重复尝试和警告
                self._ticker_failed.add(stock_code)
                logging.debug(f"订阅 Ticker 失败(已记录): {stock_code}, {err}")
        except Exception as e:
            self._ticker_failed.add(stock_code)
            logging.error(f"订阅 Ticker 异常: {stock_code}, {e}")

    def track_rt_tickers(self, stock_codes: List[str], top_n: int = None) -> Dict[str, dict]:
        """
        追踪多只股票的实时逐笔成交

        Args:
            stock_codes: 股票代码列表
            top_n: 追踪前N只股票，默认使用配置值

        Returns:
            {stock_code: {大单数据}} 字典
        """
        if not self.enabled:
            logging.debug("大单追踪功能已禁用")
            return {}

        if top_n is None:
            top_n = self.track_top_n

        # 只追踪前N只股票
        tracked_codes = stock_codes[:top_n]
        result = {}

        for stock_code in tracked_codes:
            big_order_data = self._track_single_stock(stock_code)
            if big_order_data:
                result[stock_code] = big_order_data

        return result

    def _track_single_stock(self, stock_code: str) -> Optional[dict]:
        """追踪单只股票的大单"""
        try:
            from futu import RET_OK, SubType

            # 富途 API 要求先订阅 Ticker 才能获取逐笔成交
            self._ensure_ticker_subscribed(stock_code)

            # 获取实时逐笔成交
            ret, data = self.futu_client.get_rt_ticker(stock_code, num=500)

            if ret != RET_OK or data is None or len(data) == 0:
                logging.warning(f"获取逐笔成交失败: {stock_code}")
                return None

            # 识别大单
            big_orders = self.identify_big_orders(data)

            # 计算统计数据（即使没有大单也返回零值结果）
            big_buy_count = sum(1 for order in big_orders if order['direction'] == 'BUY')
            big_sell_count = sum(1 for order in big_orders if order['direction'] == 'SELL')
            big_buy_amount = sum(order['turnover'] for order in big_orders if order['direction'] == 'BUY')
            big_sell_amount = sum(order['turnover'] for order in big_orders if order['direction'] == 'SELL')

            # 计算买卖比
            buy_sell_ratio = self.calculate_buy_sell_ratio(big_orders)

            # 计算大单强度
            order_strength = self.get_order_strength(big_orders)

            big_order_data = {
                'stock_code': stock_code,
                'timestamp': datetime.now(),
                'big_buy_count': big_buy_count,
                'big_sell_count': big_sell_count,
                'big_buy_amount': float(big_buy_amount),
                'big_sell_amount': float(big_sell_amount),
                'buy_sell_ratio': float(buy_sell_ratio),
                'order_strength': float(order_strength)
            }

            # 保存到数据库
            self._save_to_db(big_order_data)

            return big_order_data

        except Exception as e:
            logging.error(f"追踪大单异常: {stock_code}, {e}")
            return None

    def identify_big_orders(self, ticker_data) -> List[dict]:
        """
        识别大单交易

        Args:
            ticker_data: 逐笔成交DataFrame

        Returns:
            大单列表
        """
        big_orders = []

        for _, row in ticker_data.iterrows():
            turnover = row.get('turnover', 0)

            # 判断是否为大单
            if turnover >= self.min_order_amount:
                direction = row.get('ticker_direction', 'NEUTRAL')

                big_orders.append({
                    'time': row.get('time'),
                    'price': row.get('price'),
                    'volume': row.get('volume'),
                    'turnover': turnover,
                    'direction': direction
                })

        return big_orders

    def calculate_buy_sell_ratio(self, big_orders: List[dict]) -> float:
        """
        计算大单买卖比

        Args:
            big_orders: 大单列表

        Returns:
            买卖比（买入金额 / 卖出金额）
        """
        buy_amount = sum(order['turnover'] for order in big_orders if order['direction'] == 'BUY')
        sell_amount = sum(order['turnover'] for order in big_orders if order['direction'] == 'SELL')

        if sell_amount == 0:
            return 10.0 if buy_amount > 0 else 1.0

        return buy_amount / sell_amount

    def get_order_strength(self, big_orders: List[dict]) -> float:
        """
        计算大单强度

        强度 = (大单买入笔数 - 大单卖出笔数) / 总大单笔数

        Returns:
            -1到1的强度值，正值表示买入强，负值表示卖出强
        """
        if not big_orders:
            return 0.0

        buy_count = sum(1 for order in big_orders if order['direction'] == 'BUY')
        sell_count = sum(1 for order in big_orders if order['direction'] == 'SELL')
        total_count = len(big_orders)

        if total_count == 0:
            return 0.0

        strength = (buy_count - sell_count) / total_count
        return round(strength, 2)

    def _save_to_db(self, big_order_data: dict):
        """保存大单数据到数据库"""
        try:
            self.db_manager.execute_update("""
                INSERT OR REPLACE INTO big_order_tracking
                (stock_code, timestamp, big_buy_count, big_sell_count,
                 big_buy_amount, big_sell_amount, buy_sell_ratio, order_strength)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                big_order_data['stock_code'],
                big_order_data['timestamp'].isoformat(),
                big_order_data['big_buy_count'],
                big_order_data['big_sell_count'],
                big_order_data['big_buy_amount'],
                big_order_data['big_sell_amount'],
                big_order_data['buy_sell_ratio'],
                big_order_data['order_strength']
            ))

        except Exception as e:
            logging.error(f"保存大单数据失败: {big_order_data['stock_code']}, {e}")

    def get_cached_big_order_data(self, stock_code: str) -> Optional[dict]:
        """从数据库获取最近的大单数据"""
        try:
            cache_time_threshold = datetime.now() - timedelta(seconds=self.update_interval)

            rows = self.db_manager.execute_query("""
                SELECT * FROM big_order_tracking
                WHERE stock_code = ? AND timestamp > ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (stock_code, cache_time_threshold.isoformat()))

            if rows and len(rows) > 0:
                row = rows[0]
                return {
                    'stock_code': row[1],
                    'timestamp': datetime.fromisoformat(row[2]),
                    'big_buy_count': row[3],
                    'big_sell_count': row[4],
                    'big_buy_amount': row[5],
                    'big_sell_amount': row[6],
                    'buy_sell_ratio': row[7],
                    'order_strength': row[8]
                }

            return None

        except Exception as e:
            logging.error(f"读取大单缓存失败: {stock_code}, {e}")
            return None
