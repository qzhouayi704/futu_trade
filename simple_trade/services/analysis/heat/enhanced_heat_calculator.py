#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强热度计算器

职责：
1. 多维度热度计算（基础热度+资金流向+价格动能+板块联动）
2. 追高风险检查
3. 假突破识别
4. 整合所有分析模块
"""

import logging
from typing import Dict, List, Optional, Tuple

from simple_trade.utils.converters import get_last_price


class EnhancedHeatCalculator:
    """增强热度计算器"""

    def __init__(self, futu_client=None, db_manager=None, capital_analyzer=None,
                 big_order_tracker=None, config: dict = None, *, ctx=None):
        """
        初始化增强热度计算器

        Args:
            ctx: AnalysisContext（推荐）
            futu_client: 富途API客户端（向后兼容）
            db_manager: 数据库管理器（向后兼容）
            capital_analyzer: 资金流向分析器
            big_order_tracker: 大单追踪器
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
        self.capital_analyzer = capital_analyzer
        self.big_order_tracker = big_order_tracker

        # 权重配置
        self.weights = self.config.get('weights', {})
        self.base_heat_weight = self.weights.get('base_heat', 0.4)
        self.capital_flow_weight = self.weights.get('capital_flow', 0.3)
        self.momentum_weight = self.weights.get('momentum', 0.2)
        self.plate_linkage_weight = self.weights.get('plate_linkage', 0.1)

        # 日内优化配置
        self.intraday_config = self.config.get('intraday_optimization', {})
        self.max_price_position = self.intraday_config.get('max_price_position', 40)
        self.max_3d_change = self.intraday_config.get('max_3d_change', 15)

    def calculate_multi_dimension_heat(self, stock_codes: List[str],
                                       quote_data: Dict = None,
                                       kline_data: Dict = None,
                                       plate_data: Dict = None) -> Dict[str, dict]:
        """
        计算多维度热度

        Args:
            stock_codes: 股票代码列表
            quote_data: 报价数据字典 {stock_code: quote}
            kline_data: K线数据字典 {stock_code: kline_df}
            plate_data: 板块数据字典 {stock_code: plate_info}

        Returns:
            {stock_code: {热度数据}} 字典
        """
        result = {}

        # 获取资金流向数据
        capital_flow_data = self.capital_analyzer.fetch_capital_flow_data(stock_codes)

        # 获取大单数据（仅前20只）
        big_order_data = self.big_order_tracker.track_rt_tickers(stock_codes, top_n=20)

        for stock_code in stock_codes:
            try:
                # 1. 基础热度（40%）
                base_heat = self.calculate_base_heat(
                    stock_code,
                    quote_data.get(stock_code) if quote_data else None
                )

                # 2. 资金流向热度（30%）
                capital_heat = self.calculate_capital_heat(
                    stock_code,
                    capital_flow_data.get(stock_code)
                )

                # 3. 价格动能热度（20%）
                momentum_heat = self.calculate_momentum_heat(
                    stock_code,
                    quote_data.get(stock_code) if quote_data else None,
                    kline_data.get(stock_code) if kline_data else None
                )

                # 4. 板块联动热度（10%）
                plate_heat = self.calculate_plate_linkage_heat(
                    stock_code,
                    plate_data.get(stock_code) if plate_data else None
                )

                # 计算总热度
                total_heat = (
                    base_heat * self.base_heat_weight +
                    capital_heat * self.capital_flow_weight +
                    momentum_heat * self.momentum_weight +
                    plate_heat * self.plate_linkage_weight
                )

                result[stock_code] = {
                    'total_heat': round(total_heat, 2),
                    'base_heat': round(base_heat, 2),
                    'capital_heat': round(capital_heat, 2),
                    'momentum_heat': round(momentum_heat, 2),
                    'plate_heat': round(plate_heat, 2),
                    'capital_data': capital_flow_data.get(stock_code),
                    'big_order_data': big_order_data.get(stock_code)
                }

            except Exception as e:
                logging.error(f"计算多维度热度失败: {stock_code}, {e}")
                continue

        return result

    def calculate_base_heat(self, stock_code: str, quote: dict = None) -> float:
        """
        计算基础热度（量比+换手率+成交额）

        Returns:
            0-100的评分
        """
        if not quote:
            return 0.0

        # 量比评分 (0-40分)
        volume_ratio = quote.get('volume_ratio', 0)
        volume_ratio_score = min(volume_ratio / 5.0, 1.0) * 40

        # 换手率评分 (0-30分)
        turnover_rate = quote.get('turnover_rate', 0)
        turnover_rate_score = min(turnover_rate / 10.0, 1.0) * 30

        # 成交额评分 (0-30分) - 归一化到50M
        turnover = quote.get('turnover', 0)
        turnover_score = min(turnover / 50000000, 1.0) * 30

        total = volume_ratio_score + turnover_rate_score + turnover_score
        return min(total, 100)

    def calculate_capital_heat(self, stock_code: str, capital_data: dict = None) -> float:
        """
        计算资金流向热度

        Returns:
            0-100的评分
        """
        if not capital_data:
            return 0.0

        # 直接使用资金评分
        return capital_data.get('capital_score', 0.0)

    def calculate_momentum_heat(self, stock_code: str, quote: dict = None, kline_data = None) -> float:
        """
        计算价格动能热度（涨跌幅+价格位置+突破信号）

        Returns:
            0-100的评分
        """
        if not quote:
            return 0.0

        # 涨跌幅评分 (0-50分) - 只计算上涨
        change_rate = quote.get('change_percent') or quote.get('change_rate', 0)
        if change_rate > 0:
            change_score = min(change_rate / 10.0, 1.0) * 50
        else:
            change_score = 0

        # 价格位置评分 (0-25分) - 低位优先
        price_position = self._calculate_price_position(stock_code, quote, kline_data)
        if price_position is not None:
            # 0-40%位置得满分，40-100%线性递减
            if price_position <= 40:
                position_score = 25
            else:
                position_score = max(25 * (100 - price_position) / 60, 0)
        else:
            position_score = 0

        # 突破信号评分 (0-25分)
        breakthrough_score = self._check_breakthrough_signal(quote, kline_data)

        total = change_score + position_score + breakthrough_score
        return min(total, 100)

    def calculate_plate_linkage_heat(self, stock_code: str, plate_info: dict = None) -> float:
        """
        计算板块联动热度

        Returns:
            0-100的评分
        """
        if not plate_info:
            return 50.0  # 默认中等分数

        # 板块强度评分 (0-50分)
        plate_strength = plate_info.get('strength_score', 0)
        strength_score = min(plate_strength / 100 * 50, 50)

        # 板块内排名评分 (0-50分)
        plate_rank = plate_info.get('rank', 999)
        if plate_rank <= 3:
            rank_score = 50
        elif plate_rank <= 10:
            rank_score = 30
        elif plate_rank <= 20:
            rank_score = 10
        else:
            rank_score = 0

        total = strength_score + rank_score
        return min(total, 100)

    def _calculate_price_position(self, stock_code: str, quote: dict, kline_data) -> Optional[float]:
        """计算价格位置（30日区间）"""
        if not kline_data or len(kline_data) < 30:
            return None

        try:
            current_price = get_last_price(quote)
            high_30d = kline_data['high'].tail(30).max()
            low_30d = kline_data['low'].tail(30).min()

            if high_30d == low_30d:
                return 50.0

            position = (current_price - low_30d) / (high_30d - low_30d) * 100
            return round(position, 2)

        except Exception as e:
            logging.error(f"计算价格位置失败: {stock_code}, {e}")
            return None

    def _check_breakthrough_signal(self, quote: dict, kline_data) -> float:
        """检查突破信号"""
        if not kline_data or len(kline_data) < 5:
            return 0.0

        try:
            current_price = get_last_price(quote)
            high_5d = kline_data['high'].tail(5).max()

            # 突破5日高点
            if current_price > high_5d * 1.01:
                return 25.0

            return 0.0

        except Exception as e:
            return 0.0

    def check_chase_high_risk(self, stock_code: str, quote: dict, kline_data) -> Tuple[bool, str]:
        """
        检查追高风险

        Returns:
            (is_risky, reason) - True表示有追高风险
        """
        if not quote or not kline_data or len(kline_data) < 30:
            return False, ""

        try:
            # 1. 价格位置检查
            price_position = self._calculate_price_position(stock_code, quote, kline_data)
            if price_position and price_position > self.max_price_position:
                return True, f"价格位置过高({price_position:.1f}%)"

            # 2. 短期涨幅检查（3日）
            if len(kline_data) >= 3:
                close_3d_ago = kline_data['close'].iloc[-4]
                current_price = get_last_price(quote)
                change_3d = (current_price - close_3d_ago) / close_3d_ago * 100

                if change_3d > self.max_3d_change:
                    return True, f"3日涨幅过大({change_3d:.1f}%)"

            # 3. 成交量异常检查
            volume_ratio = quote.get('volume_ratio', 0)
            if volume_ratio > 10:
                return True, f"成交量异常放大({volume_ratio:.1f}倍)"

            return False, ""

        except Exception as e:
            logging.error(f"检查追高风险失败: {stock_code}, {e}")
            return False, ""

    def detect_false_breakout(self, stock_code: str, quote: dict,
                             capital_data: dict = None,
                             big_order_data: dict = None,
                             plate_info: dict = None) -> Tuple[bool, str]:
        """
        识别假突破

        Returns:
            (is_false, reason) - True表示可能是假突破
        """
        if not quote:
            return False, ""

        try:
            # 1. 资金流向确认
            if capital_data:
                net_inflow_ratio = capital_data.get('net_inflow_ratio', 0)
                if net_inflow_ratio < 0:
                    return True, "资金流出，假突破"

            # 2. 大单确认
            if big_order_data:
                buy_sell_ratio = big_order_data.get('buy_sell_ratio', 1.0)
                if buy_sell_ratio < 1.0:
                    return True, "大单卖出为主，假突破"

            # 3. 换手率确认
            turnover_rate = quote.get('turnover_rate', 0)
            if turnover_rate < 1.0:
                return True, "换手率不足，突破无力"

            # 4. 板块联动确认
            if plate_info:
                plate_strength = plate_info.get('strength_score', 0)
                if plate_strength < 60:
                    return True, "板块不强，孤立突破"

            return False, ""

        except Exception as e:
            logging.error(f"识别假突破失败: {stock_code}, {e}")
            return False, ""
