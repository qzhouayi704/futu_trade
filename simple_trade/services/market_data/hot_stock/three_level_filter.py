#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三级筛选机制 - 增强模式热门股票过滤器

职责：
- 第一级：活跃度筛选（复用 HotStockFilter 的活跃度条件）
- 第二级：资金流向筛选（50只）
- 第三级：综合质量筛选（20只）
"""

import logging
from typing import Dict, Any, List, Optional
from ....database.core.db_manager import DatabaseManager
from ...analysis import StockHeatCalculator
from .hot_stock_filter import HotStockFilter, ACTIVITY_THRESHOLDS


class ThreeLevelFilter:
    """三级筛选机制"""

    def __init__(
        self,
        db_manager: DatabaseManager,
        heat_calculator: StockHeatCalculator,
        config: Dict[str, Any]
    ):
        """
        初始化三级过滤器

        Args:
            db_manager: 数据库管理器
            heat_calculator: 热度计算器
            config: 三级过滤配置
        """
        self.db_manager = db_manager
        self.heat_calculator = heat_calculator
        self.config = config
        self.logger = logging.getLogger(__name__)

    def apply_three_level_filter(
        self,
        stock_codes: List[str] = None,
        quote_data: Dict = None,
        kline_data: Dict = None,
        plate_data: Dict = None
    ) -> Dict[str, Any]:
        """
        应用三级筛选机制

        Args:
            stock_codes: 股票代码列表
            quote_data: 报价数据字典
            kline_data: K线数据字典
            plate_data: 板块数据字典

        Returns:
            {
                'level1': [...],  # 第一级筛选结果（200只）
                'level2': [...],  # 第二级筛选结果（50只）
                'level3': [...],  # 第三级筛选结果（20只）
                'stats': {...}    # 统计信息
            }
        """
        try:
            # 获取股票池
            if stock_codes is None:
                stock_codes = self._get_active_stock_codes()

            self.logger.info(f"开始三级筛选，初始股票数：{len(stock_codes)}")

            # 第一级：热度初筛
            level1_stocks = self._level1_heat_filter(stock_codes, quote_data)
            self.logger.info(f"第一级筛选完成：{len(level1_stocks)} 只股票")

            # 第二级：资金确认
            level2_stocks = self._level2_capital_filter(level1_stocks, quote_data)
            self.logger.info(f"第二级筛选完成：{len(level2_stocks)} 只股票")

            # 第三级：位置筛选
            level3_stocks = self._level3_position_filter(level2_stocks, quote_data, kline_data, plate_data)
            self.logger.info(f"第三级筛选完成：{len(level3_stocks)} 只股票")

            return {
                'level1': level1_stocks,
                'level2': level2_stocks,
                'level3': level3_stocks,
                'stats': {
                    'enhanced_mode': True,
                    'initial_count': len(stock_codes),
                    'level1_count': len(level1_stocks),
                    'level2_count': len(level2_stocks),
                    'level3_count': len(level3_stocks)
                }
            }

        except Exception as e:
            self.logger.error(f"三级筛选失败: {e}", exc_info=True)
            return {
                'level1': [],
                'level2': [],
                'level3': [],
                'stats': {'error': str(e)}
            }

    def _get_active_stock_codes(self) -> List[str]:
        """获取活跃股票代码列表"""
        try:
            query = '''
                SELECT code FROM stocks
                WHERE is_low_activity = 0
                ORDER BY heat_score DESC
            '''
            results = self.db_manager.execute_query(query)
            return [row[0] for row in results]
        except Exception as e:
            self.logger.error(f"获取活跃股票失败: {e}")
            return []

    def _level1_heat_filter(self, stock_codes: List[str], quote_data: Dict = None) -> List[Dict]:
        """
        第一级：活跃度筛选（复用 HotStockFilter.check_stock_activity）

        筛选条件（与 HotStockFilter 共享 ACTIVITY_THRESHOLDS）：
        - 成交量 >= 阈值（港股50万/美股300万）
        - 换手率 >= 阈值（港股0.1%/美股0.5%）
        - 价格 >= 阈值（港股1元）
        """
        level1_config = self.config.get('level1_heat', {})
        target_count = level1_config.get('target_count', 200)

        # 合并配置：level1_config 中的自定义阈值覆盖默认值
        thresholds = {**ACTIVITY_THRESHOLDS}
        for key in ACTIVITY_THRESHOLDS:
            if key in level1_config:
                thresholds[key] = level1_config[key]

        filtered_stocks = []

        for stock_code in stock_codes:
            quote = quote_data.get(stock_code) if quote_data else None
            if not quote:
                continue

            # 复用 HotStockFilter 的活跃度检查
            if not HotStockFilter.check_stock_activity(stock_code, quote, thresholds):
                continue

            filtered_stocks.append({
                'code': stock_code,
                'quote': quote
            })

        # 按热度排序，取前N只
        filtered_stocks.sort(
            key=lambda x: x['quote'].get('volume_ratio', 0) * x['quote'].get('turnover_rate', 0),
            reverse=True
        )
        return filtered_stocks[:target_count]

    def _level2_capital_filter(self, level1_stocks: List[Dict], quote_data: Dict = None) -> List[Dict]:
        """
        第二级：资金确认（200只 → 50只）

        筛选条件：
        - 主力净流入 >= 0
        - 大单买入占比 >= 50%
        - 资金持续性 >= N个周期
        """
        if not hasattr(self.heat_calculator, 'capital_analyzer') or not self.heat_calculator.capital_analyzer:
            self.logger.warning("资金流向分析器未初始化，跳过第二级筛选")
            return level1_stocks[:50]

        level2_config = self.config.get('level2_capital', {})
        target_count = level2_config.get('target_count', 50)

        stock_codes = [s['code'] for s in level1_stocks]
        capital_data = self.heat_calculator.capital_analyzer.fetch_capital_flow_data(stock_codes)

        filtered_stocks = []

        for stock in level1_stocks:
            stock_code = stock['code']
            capital = capital_data.get(stock_code)

            if not capital:
                continue

            # 净流入占比检查
            net_inflow_ratio = capital.get('net_inflow_ratio', 0)
            min_net_inflow = level2_config.get('min_net_inflow_ratio', 0.0)
            if net_inflow_ratio < min_net_inflow:
                continue

            # 大单买入占比检查
            big_order_ratio = capital.get('big_order_buy_ratio', 0)
            min_big_order = level2_config.get('min_big_order_ratio', 0.5)
            if big_order_ratio < min_big_order:
                continue

            stock['capital_data'] = capital
            filtered_stocks.append(stock)

        # 按资金评分排序
        filtered_stocks.sort(key=lambda x: x['capital_data'].get('capital_score', 0), reverse=True)
        return filtered_stocks[:target_count]

    def _level3_position_filter(
        self,
        level2_stocks: List[Dict],
        quote_data: Dict = None,
        kline_data: Dict = None,
        plate_data: Dict = None
    ) -> List[Dict]:
        """
        第三级：位置筛选（50只 → 20只）

        筛选条件：
        - 价格位置 <= 40%（30日区间）
        - 涨幅范围（按市场区分，资金强确认时放宽上限）
        - 板块强度 >= 70
        """
        if not hasattr(self.heat_calculator, 'enhanced_calculator') or not self.heat_calculator.enhanced_calculator:
            self.logger.warning("增强热度计算器未初始化，跳过第三级筛选")
            return level2_stocks[:20]

        level3_config = self.config.get('level3_position', {})
        target_count = level3_config.get('target_count', 20)

        # 按市场区分的涨幅范围（可配置，有默认值）
        market_change_ranges = level3_config.get('market_change_ranges', {})
        default_min_change = level3_config.get('min_change_pct', 2.5)
        default_max_change = level3_config.get('max_change_pct', 5.0)

        # 资金强确认的涨幅上限放宽倍数
        capital_boost_ratio = level3_config.get('capital_boost_ratio', 1.5)
        capital_strong_threshold = level3_config.get('capital_strong_net_inflow_ratio', 0.2)

        filtered_stocks = []

        for stock in level2_stocks:
            stock_code = stock['code']
            quote = stock.get('quote')
            kline = kline_data.get(stock_code) if kline_data else None
            plate = plate_data.get(stock_code) if plate_data else None

            if not quote:
                continue

            # 按市场获取涨幅范围
            market = "HK" if stock_code.startswith("HK.") else "US"
            market_range = market_change_ranges.get(market, {})
            min_change = market_range.get('min', default_min_change)
            max_change = market_range.get('max', default_max_change)

            # 资金强确认时放宽涨幅上限
            capital_data = stock.get('capital_data', {})
            net_inflow_ratio = capital_data.get('net_inflow_ratio', 0)
            if net_inflow_ratio >= capital_strong_threshold:
                max_change = max_change * capital_boost_ratio

            # 涨幅检查
            change_rate = quote.get('change_percent') or quote.get('change_rate', 0)
            if not (min_change <= change_rate <= max_change):
                continue

            # 价格位置检查（如果有K线数据）
            if kline:
                price_position = self.heat_calculator.enhanced_calculator._calculate_price_position(
                    stock_code, quote, kline
                )
                if price_position:
                    max_position = level3_config.get('max_price_position', 40)
                    if price_position > max_position:
                        continue
                    stock['price_position'] = price_position

            # 板块强度检查（如果有板块数据）
            if plate:
                plate_strength = plate.get('strength_score', 0)
                min_strength = level3_config.get('min_plate_strength', 70)
                if plate_strength < min_strength:
                    continue
                stock['plate_strength'] = plate_strength

            filtered_stocks.append(stock)

        # 综合排序：资金 40% + 涨幅 20% + 位置 40%
        filtered_stocks.sort(
            key=lambda x: (
                x.get('capital_data', {}).get('capital_score', 0) * 0.4 +
                (x.get('quote', {}).get('change_percent', 0) or x.get('quote', {}).get('change_rate', 0)) * 2.0 +
                (100 - x.get('price_position', 50)) * 0.4
            ),
            reverse=True
        )

        return filtered_stocks[:target_count]
