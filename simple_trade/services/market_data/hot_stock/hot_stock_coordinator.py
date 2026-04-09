#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
热门股票分析服务（协调器）- 重构版

职责：
1. 协调各个分析子服务
2. 提供统一的热度分析接口
3. 管理热度数据的更新和缓存
4. 提供板块概览数据
"""

import logging
from dataclasses import asdict
from typing import Dict, Any, List, Optional, Callable
from ....database.core.db_manager import DatabaseManager
from ....api.futu_client import FutuClient
from ....config.config import Config
from ...analysis import StockHeatCalculator, KlineAnalyzer, PlateOverviewService
from .realtime_heat_service import RealtimeHeatService
from .three_level_filter import ThreeLevelFilter


class HotStockCoordinator:
    """
    热门股票分析服务（协调器）

    功能：
    1. 协调各个分析子服务
    2. 提供统一的热度分析接口
    3. 管理热度数据的更新和缓存
    4. 提供板块概览数据
    """

    # 默认配置
    DEFAULT_ANALYSIS_DAYS = 90  # 分析过去90天
    DEFAULT_TOP_HOT_COUNT = 100  # 热门股票数量（取热度分排名前100）

    def __init__(
        self,
        db_manager: DatabaseManager,
        futu_client: FutuClient,
        config: Config = None,
        quote_service=None
    ):
        """
        初始化热门股票服务

        Args:
            db_manager: 数据库管理器
            futu_client: Futu API客户端
            config: 配置对象
            quote_service: 报价服务（可选）
        """
        self.db_manager = db_manager
        self.futu_client = futu_client
        self.config = config
        self.quote_service = quote_service
        self.logger = logging.getLogger(__name__)

        # 初始化子服务
        self.heat_calculator = StockHeatCalculator(
            futu_client,
            db_manager=db_manager,
            config=asdict(config) if config else None
        )
        self.kline_analyzer = KlineAnalyzer(db_manager)
        self.plate_overview = PlateOverviewService(db_manager)

        # 初始化实时热度服务
        self.realtime_heat = RealtimeHeatService(
            db_manager,
            futu_client,
            self.heat_calculator,
            quote_service
        )

        # 检查是否启用增强模式
        config_data = asdict(config) if config else {}
        enhanced_config = config_data.get('enhanced_heat_config', {})
        self.enhanced_enabled = enhanced_config.get('enabled', False)
        self.three_level_config = enhanced_config.get('three_level_filter', {})

        # 初始化三级过滤器
        if self.enhanced_enabled:
            self.three_level_filter = ThreeLevelFilter(
                db_manager,
                self.heat_calculator,
                self.three_level_config
            )
        else:
            self.three_level_filter = None

        # 分析状态
        self._is_analyzing = False
        self._analysis_progress = {
            'total': 0,
            'processed': 0,
            'current_stock': '',
            'status': 'idle'
        }

    # ==================== 热门股票列表 ====================

    def get_hot_stocks(self, limit: int = None) -> List[Dict[str, Any]]:
        """获取热门股票列表（基于历史热度分）"""
        if limit is None:
            limit = self.DEFAULT_TOP_HOT_COUNT
        return self.realtime_heat.get_hot_stocks_realtime(limit)

    def get_non_hot_stocks(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取非热门股票列表（热度分为0或较低）"""
        stocks = []

        try:
            query = '''
                SELECT s.id, s.code, s.name, s.market,
                       s.heat_score, s.avg_turnover_rate, s.avg_volume, s.active_days,
                       s.heat_update_time
                FROM stocks s
                WHERE s.heat_score = 0 OR s.heat_score IS NULL
                ORDER BY s.code
                LIMIT ?
            '''
            results = self.db_manager.execute_query(query, (limit,))

            for row in results:
                stocks.append({
                    'id': row[0],
                    'code': row[1],
                    'name': row[2],
                    'market': row[3],
                    'heat_score': row[4] or 0,
                    'avg_turnover_rate': row[5],
                    'avg_volume': row[6],
                    'active_days': row[7],
                    'heat_update_time': row[8]
                })

        except Exception as e:
            self.logger.error(f"获取非热门股票失败: {e}")

        return stocks

    # ==================== 实时热度更新 ====================

    def calculate_realtime_heat_scores(
        self,
        stock_codes: List[str],
        use_cache: bool = True,
        cache_duration: int = 3600
    ) -> Dict[str, Dict[str, Any]]:
        """计算实时热度分（代理方法）"""
        return self.realtime_heat.calculate_realtime_heat_scores(
            stock_codes, use_cache, cache_duration
        )

    def get_cached_heat_scores(self) -> Dict[str, Dict[str, Any]]:
        """只读取已缓存的热度分数据，不触发任何 API 调用"""
        return self.realtime_heat.get_cached_heat_scores()

    def update_realtime_heat_scores(self, force: bool = False) -> Dict[str, Any]:
        """更新实时热度数据（批量更新所有已订阅股票）"""
        return self.realtime_heat.update_realtime_heat_scores(force)

    # ==================== 板块概览 ====================

    def get_plate_overview(self) -> List[Dict[str, Any]]:
        """获取板块概览（含股票数量、热门股数量和市场热度）"""
        from ...utils.market_helper import MarketTimeHelper

        try:
            active_markets = MarketTimeHelper.get_current_active_markets()
            self.logger.debug(f"获取板块概览 - 活跃市场: {active_markets}")

            # 获取板块列表
            plates = self.plate_overview.get_plate_overview(active_markets)
            if not plates:
                return []

            # 获取所有股票代码并计算热度
            plate_ids = [p['id'] for p in plates]
            plate_stocks = self.plate_overview.get_plate_stocks_map(plate_ids)
            all_codes = set(code for codes in plate_stocks.values() for code in codes)

            # 从缓存获取报价并计算热度
            quotes_map = self.plate_overview.get_realtime_quotes_from_cache(list(all_codes))
            self.plate_overview.calculate_plate_heat(plates, quotes_map)

            self.logger.debug(f"获取到 {len(plates)} 个板块")
            return plates

        except Exception as e:
            self.logger.error(f"获取板块概览失败: {e}")
            return []

    # ==================== 三级筛选机制（增强模式） ====================

    def get_hot_stocks_with_three_level_filter(
        self,
        stock_codes: List[str] = None,
        quote_data: Dict = None,
        kline_data: Dict = None,
        plate_data: Dict = None
    ) -> Dict[str, Any]:
        """
        三级筛选机制获取高质量热门股票

        Args:
            stock_codes: 股票代码列表（如果为None，从数据库获取）
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
        if not self.enhanced_enabled or not self.three_level_filter:
            self.logger.warning("增强模式未启用，使用基础热门股票列表")
            return {
                'level1': [],
                'level2': [],
                'level3': self.get_hot_stocks(limit=20),
                'stats': {'enhanced_mode': False}
            }

        return self.three_level_filter.apply_three_level_filter(
            stock_codes, quote_data, kline_data, plate_data
        )

    # ==================== 状态查询 ====================

    def get_heat_status(self) -> Dict[str, Any]:
        """获取热度分析状态"""
        return {
            'is_analyzing': self._is_analyzing,
            'progress': self._analysis_progress,
            'enhanced_enabled': self.enhanced_enabled
        }

    def is_analyzing(self) -> bool:
        """检查是否正在分析"""
        return self._is_analyzing

    # ==================== 历史热度分析（已废弃） ====================

    def analyze_hot_stocks(self, progress_callback: Callable = None, force_update: bool = False) -> Dict[str, Any]:
        """【已废弃】历史热度分析功能已移除，请使用实时热度"""
        self.logger.warning("analyze_hot_stocks() 已废弃，请使用实时热度")
        return {'success': True, 'skipped': True, 'message': '历史热度功能已废弃', 'hot_count': 0}
