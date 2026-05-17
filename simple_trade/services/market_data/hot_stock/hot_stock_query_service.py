#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
热门股票查询服务

职责：
- 持仓股票查询
- 热度计算
- 股票过滤和排序
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple, Optional, Set

from ....utils.converters import get_last_price
from ....database.core.db_manager import DatabaseManager


class HotStockQueryService:
    """热门股票查询与过滤服务"""

    def __init__(self, db_manager: DatabaseManager):
        self._db = db_manager
        # 波动率缓存：近30天有高波动的股票代码集合
        self._volatile_codes: Set[str] = set()
        self._stocks_with_kline: Set[str] = set()
        self._volatile_cache_time: Optional[datetime] = None
        self._volatile_cache_minutes: int = 10

    def get_position_codes(self, futu_trade_service=None) -> Set[str]:
        """获取持仓股票代码集合

        优先从数据库查询 POSITION_MONITOR 板块，
        若无记录则尝试从交易服务获取实时持仓。
        """
        position_codes: Set[str] = set()
        try:
            rows = self._db.execute_query('''
                SELECT DISTINCT s.code FROM stocks s
                INNER JOIN stock_plates sp ON s.id = sp.stock_id
                INNER JOIN plates p ON sp.plate_id = p.id
                WHERE p.plate_code = 'POSITION_MONITOR'
            ''')
            position_codes = {row[0] for row in rows} if rows else set()

            if not position_codes and futu_trade_service is not None:
                try:
                    pos_result = futu_trade_service.get_positions()
                    if pos_result.get('success') and pos_result.get('positions'):
                        for pos in pos_result['positions']:
                            if pos.get('qty', 0) > 0:
                                position_codes.add(pos.get('stock_code', ''))
                except Exception:
                    pass
        except Exception as e:
            logging.warning(f"获取持仓股票列表失败: {e}")
        return position_codes

    @staticmethod
    def calculate_stock_heat(
        quote: Dict[str, Any],
        stock_code: str,
        cached_heat_scores: Dict[str, Dict[str, Any]],
        filter_config: Dict[str, Any],
    ) -> float:
        """计算热度分数：优先用后台已算好的热度，否则用报价实时计算"""
        if stock_code in cached_heat_scores:
            return cached_heat_scores[stock_code]['heat_score']

        turnover_rate = quote.get('turnover_rate', 0) or 0
        turnover = quote.get('turnover', 0) or 0

        turnover_rate_weight = filter_config.get('turnover_rate_weight', 0.4)
        turnover_weight = filter_config.get('turnover_weight', 0.6)
        turnover_rate_max = filter_config.get('turnover_rate_max_threshold', 5.0)
        turnover_max = filter_config.get('turnover_max_threshold', 50000000)

        rate_score = min(turnover_rate / turnover_rate_max, 1.0) * 100 if turnover_rate_max > 0 else 0
        turnover_score = min(turnover / turnover_max, 1.0) * 100 if turnover_max > 0 else 0

        return rate_score * turnover_rate_weight + turnover_score * turnover_weight

    def filter_and_sort_stocks(
        self,
        stocks_data: List[Dict[str, Any]],
        quotes_map: Dict[str, Dict[str, Any]],
        cached_heat_scores: Dict[str, Dict[str, Any]],
        filter_config: Dict[str, Any],
        min_stock_price: Dict[str, float],
        market_filter: Optional[str] = None,
        search_filter: Optional[str] = None,
        limit: int = 100,
        position_codes: Optional[Set[str]] = None,
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """过滤和排序股票

        Returns:
            (过滤后的股票列表, 过滤摘要)
        """
        filter_enabled = filter_config.get('enabled', True)
        min_volume = filter_config.get('min_volume', 100000)
        _position_codes = position_codes or set()

        # 获取波动率过滤集合（近30天有过高波动的股票）
        volatile_codes, stocks_with_kline = self._get_volatile_stock_codes()

        filtered_stocks = []
        filter_summary: List[str] = []

        for stock in stocks_data:
            stock_code = stock['code']
            stock_market = stock.get('market', '')
            stock_name = stock.get('name', '')
            is_position = stock_code in _position_codes

            if market_filter and stock_market != market_filter:
                continue
            if search_filter and search_filter not in stock_code.lower() and search_filter not in stock_name.lower():
                continue

            quote = quotes_map.get(stock_code)
            has_quote = bool(quote)
            if not quote:
                # 无报价时使用空占位，确保股票仍然显示（启动初期/缓存过期）
                quote = {'code': stock_code, 'volume': 0, 'turnover': 0, 'turnover_rate': 0}

            # 持仓股票跳过成交量和价格筛选；无报价时也跳过（确保启动时能显示）
            if not is_position and has_quote:
                volume = quote.get('volume', 0) or 0
                if filter_enabled and volume < min_volume:
                    if '成交量过低' not in filter_summary:
                        filter_summary.append('成交量过低')
                    continue

                cur_price = get_last_price(quote)
                min_price = min_stock_price.get(stock_market, 0)
                if filter_enabled and cur_price < min_price:
                    if '价格过低' not in filter_summary:
                        filter_summary.append('价格过低')
                    continue

                # 波动率过滤：近30天平均振幅不达标的股票排除
                # 但当日有异常表现的股票豁免（突然放量/大幅波动）
                # 注意：没有K线数据的股票不过滤（缺数据≠低波动）
                if (filter_enabled and volatile_codes
                        and stock_code in stocks_with_kline
                        and stock_code not in volatile_codes):
                    # 当日异常豁免条件
                    high = quote.get('high_price', 0) or 0
                    low = quote.get('low_price', 0) or 0
                    intraday_amp = ((high - low) / low * 100) if low > 0 else 0
                    change_rate = abs(quote.get('change_rate', 0) or quote.get('change_percent', 0) or 0)
                    turnover_rate = quote.get('turnover_rate', 0) or 0
                    volume_ratio = quote.get('volume_ratio', 0) or 0

                    today_anomaly = (
                        intraday_amp >= 5.0       # 当日振幅 >= 5%
                        or change_rate >= 5.0     # 当日涨跌幅 >= 5%
                        or turnover_rate >= 3.0   # 当日换手率 >= 3%
                        or volume_ratio >= 2.0    # 量比 >= 2（成交量是近期均值2倍）
                    )
                    if not today_anomaly:
                        if '低波动' not in filter_summary:
                            filter_summary.append('低波动')
                        continue

            heat_score = self.calculate_stock_heat(quote, stock_code, cached_heat_scores, filter_config)
            stock['heat_score'] = heat_score
            filtered_stocks.append(stock)

        filtered_stocks.sort(key=lambda x: x.get('heat_score', 0), reverse=True)
        return filtered_stocks[:limit], filter_summary

    def _get_volatile_stock_codes(
        self, min_avg_amplitude_pct: float = 5.0, lookback_days: int = 30
    ) -> Tuple[Set[str], Set[str]]:
        """获取近30天平均日振幅达标的股票代码集合（带缓存）

        筛选条件：近 lookback_days 天的日K线平均振幅 >= min_avg_amplitude_pct%
        振幅 = (最高 - 最低) / 最低 × 100

        Returns:
            (volatile_codes, stocks_with_kline):
            - volatile_codes: 满足平均波动率条件的股票代码集合
            - stocks_with_kline: 近30天有K线数据的股票代码集合
        """
        # 检查缓存
        if (self._volatile_cache_time
                and self._volatile_codes is not None
                and (datetime.now() - self._volatile_cache_time).total_seconds() / 60 < self._volatile_cache_minutes):
            return self._volatile_codes, self._stocks_with_kline

        try:
            cutoff_date = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')

            # 查询1：近30天有K线数据的所有股票
            kline_rows = self._db.execute_query("""
                SELECT DISTINCT stock_code
                FROM kline_data
                WHERE date(time_key) >= ?
            """, (cutoff_date,))
            self._stocks_with_kline = {row[0] for row in kline_rows} if kline_rows else set()

            # 查询2：近30天平均日振幅 >= 阈值的股票
            rows = self._db.execute_query("""
                SELECT stock_code
                FROM kline_data
                WHERE date(time_key) >= ?
                  AND low_price > 0
                GROUP BY stock_code
                HAVING AVG((high_price - low_price) / low_price * 100) >= ?
            """, (cutoff_date, min_avg_amplitude_pct))

            self._volatile_codes = {row[0] for row in rows} if rows else set()
            self._volatile_cache_time = datetime.now()
            logging.info(
                f"波动率过滤缓存更新: {len(self._volatile_codes)}/{len(self._stocks_with_kline)} "
                f"只股票近{lookback_days}天平均振幅>={min_avg_amplitude_pct}%"
            )

        except Exception as e:
            logging.warning(f"获取波动率数据失败: {e}")
            if not hasattr(self, '_stocks_with_kline'):
                self._stocks_with_kline = set()
            if self._volatile_codes is None:
                self._volatile_codes = set()

        return self._volatile_codes, self._stocks_with_kline

    def trigger_kline_download_for_missing(
        self, all_stock_codes: Set[str], stocks_with_kline: Set[str]
    ) -> None:
        """后台触发缺少K线数据的股票下载（非阻塞）

        在单独线程中运行，不影响 API 响应速度。
        如果 API 额度不足，下载会自动失败，不影响过滤逻辑。
        """
        missing_codes = all_stock_codes - stocks_with_kline
        if not missing_codes:
            return

        # 限制每次最多下载 20 只，避免占用太多额度
        codes_to_download = list(missing_codes)[:20]
        logging.info(f"检测到 {len(missing_codes)} 只股票缺少近期K线，后台下载 {len(codes_to_download)} 只")

        import threading

        def _download():
            try:
                from ...services.realtime.realtime_kline_service import RealtimeKlineService
                kline_svc = RealtimeKlineService(self._db, None)
                # 初始化 futu_client
                from ...api.futu_client import FutuClient
                client = FutuClient()
                if not client.is_available():
                    logging.debug("K线下载: 富途API不可用，跳过")
                    return
                kline_svc.futu_client = client
                result = kline_svc.fetch_and_save_kline_data(
                    stock_codes=codes_to_download, limit=35
                )
                if result['success']:
                    logging.info(f"后台K线下载完成: {result['message']}")
                    # 清除缓存以便下次重新计算波动率
                    self._volatile_cache_time = None
                else:
                    logging.debug(f"后台K线下载未成功: {result['message']}")
            except Exception as e:
                logging.debug(f"后台K线下载异常（可忽略）: {e}")

        t = threading.Thread(target=_download, daemon=True, name="kline-volatility-fill")
        t.start()
