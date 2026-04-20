#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
激进策略交易服务（协调器）

独立的激进交易策略服务，专注于强势板块龙头股的短线交易。
作为协调器，统一管理信号处理和订单管理子服务。
"""

import logging
from datetime import datetime, date
from typing import List, Dict, Any, Optional
from ....database.core.db_manager import DatabaseManager
from ....config.config import Config
from ....strategy.strategy_registry import StrategyRegistry
from ...market_data.plate.plate_strength_service import PlateStrengthService, PlateStrengthScore
from ...market_data.leader_stock_filter import LeaderStockFilter, LeaderFilterConfig
from ....core.validation.signal_scorer import SignalScorer, SignalScore
from ....core.validation.risk_checker import RiskChecker, RiskConfig
from .aggressive_signal_processor import AggressiveSignalProcessor
from .aggressive_order_manager import AggressiveOrderManager


class AggressiveTradeService:
    """
    激进策略交易服务（协调器）

    提供完整的激进交易策略功能：
    1. 板块强势度计算
    2. 龙头股筛选
    3. 信号生成和评分
    4. 风险检查和止盈止损

    作为协调器，将具体功能委托给子服务：
    - AggressiveSignalProcessor: 信号处理
    - AggressiveOrderManager: 订单和风险管理
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        config: Config,
        realtime_service,
        plate_manager,
        kline_service,
        quote_cache=None
    ):
        """
        初始化激进策略交易服务

        Args:
            db_manager: 数据库管理器
            config: 配置对象
            realtime_service: 实时行情服务
            plate_manager: 板块管理服务
            kline_service: K线数据服务
            quote_cache: 全局报价缓存（可选，用于板块强势度计算）
        """
        self.db_manager = db_manager
        self.config = config
        self.realtime_service = realtime_service
        self.plate_manager = plate_manager
        self.kline_service = kline_service
        self.quote_cache = quote_cache
        self.logger = logging.getLogger(__name__)

        # 获取激进策略配置
        self.strategy_config = self._load_strategy_config()

        # 初始化基础服务
        self.plate_strength_service = PlateStrengthService(
            realtime_service=realtime_service,
            plate_manager=plate_manager
        )

        self.leader_filter = LeaderStockFilter(
            kline_service=kline_service,
            config=self._create_leader_filter_config()
        )

        self.signal_scorer = SignalScorer(
            max_daily_signals=self.strategy_config.get('signal', {}).get('max_daily_signals', 2),
            min_score=self.strategy_config.get('signal', {}).get('min_signal_strength', 0.7) * 100
        )

        self.risk_checker = RiskChecker(
            config=self._create_risk_config()
        )

        # 初始化子服务：信号处理器
        self.signal_processor = AggressiveSignalProcessor(
            db_manager=db_manager,
            signal_scorer=self.signal_scorer,
            leader_filter=self.leader_filter,
            plate_strength_service=self.plate_strength_service,
            realtime_service=realtime_service,
            kline_service=kline_service
        )

        # 初始化子服务：订单管理器
        self.order_manager = AggressiveOrderManager(
            db_manager=db_manager,
            risk_checker=self.risk_checker,
            plate_strength_service=self.plate_strength_service,
            plate_manager=plate_manager,
            realtime_service=realtime_service
        )

        # 创建激进策略实例
        self.strategy = StrategyRegistry.create_instance(
            'aggressive',
            data_service=kline_service,
            config=self.strategy_config
        )

        self.logger.info("激进策略交易服务初始化完成")

    def _load_strategy_config(self) -> Dict[str, Any]:
        """加载激进策略配置"""
        try:
            strategies = self.config.strategies.get('available', {})
            aggressive_config = strategies.get('aggressive', {})

            if not aggressive_config:
                self.logger.warning("未找到激进策略配置，使用默认配置")
                return {}

            # 获取活跃预设
            active_preset = aggressive_config.get('active_preset', '默认')
            presets = aggressive_config.get('presets', {})
            preset_config = presets.get(active_preset, {})

            self.logger.info(f"加载激进策略配置: {active_preset}")
            return preset_config

        except Exception as e:
            self.logger.error(f"加载激进策略配置失败: {e}")
            return {}

    def _create_leader_filter_config(self) -> LeaderFilterConfig:
        """创建龙头股筛选配置"""
        stock_filter = self.strategy_config.get('stock_filter', {})

        return LeaderFilterConfig(
            min_change_pct=stock_filter.get('min_change_pct', 3.0),
            max_change_pct=stock_filter.get('max_change_pct', 50.0),
            min_volume=stock_filter.get('min_volume', 1000000),
            min_turnover_rate=stock_filter.get('min_turnover_rate', 0.8),
            max_leaders_per_plate=3,
            min_signal_strength=self.strategy_config.get('signal', {}).get('min_signal_strength', 0.3)
        )

    def _create_risk_config(self) -> RiskConfig:
        """创建风险配置"""
        take_profit = self.strategy_config.get('take_profit', {})
        stop_loss = self.strategy_config.get('stop_loss', {})

        return RiskConfig(
            target_profit_pct=take_profit.get('target_pct', 8.0),
            trailing_trigger_pct=take_profit.get('trailing_trigger_pct', 6.0),
            trailing_callback_pct=take_profit.get('trailing_callback_pct', 2.0),
            fixed_stop_loss_pct=stop_loss.get('fixed_pct', -5.0),
            quick_stop_loss_pct=stop_loss.get('quick_stop_pct', -3.0),
            plate_rank_threshold=stop_loss.get('plate_rank_threshold', 5),
            max_holding_days=stop_loss.get('max_holding_days', 1),
            min_profit_after_days=2.0
        )

    async def generate_signals(self) -> List[Dict[str, Any]]:
        """
        生成交易信号（主入口方法）

        Returns:
            信号列表，每个信号包含：
            - stock_code: 股票代码
            - stock_name: 股票名称
            - signal_type: 信号类型（buy/sell）
            - price: 当前价格
            - plate_name: 所属板块
            - plate_strength: 板块强势度
            - signal_score: 信号评分
            - reason: 信号原因
        """
        try:
            self.logger.info("开始生成激进策略交易信号")

            # 1. 获取强势板块（前3名）
            strong_plates = await self._get_strong_plates()
            if not strong_plates:
                self.logger.info("未找到强势板块")
                return []

            self.logger.info(f"找到 {len(strong_plates)} 个强势板块")

            # 2. 从强势板块中筛选龙头股（委托给信号处理器）
            leader_candidates = await self.signal_processor.filter_leader_stocks(strong_plates)
            if not leader_candidates:
                self.logger.info("未找到符合条件的龙头股")
                return []

            self.logger.info(f"找到 {len(leader_candidates)} 个龙头股候选")

            # 3. 对候选股票进行评分和筛选（委托给信号处理器）
            signals = await self.signal_processor.score_and_filter_signals(
                leader_candidates,
                strong_plates
            )

            # 4. 保存信号到数据库（委托给订单管理器）
            if signals:
                self.order_manager.save_signals_batch(signals)

            self.logger.info(f"生成 {len(signals)} 个交易信号")
            return signals

        except Exception as e:
            self.logger.error(f"生成交易信号失败: {e}", exc_info=True)
            return []

    async def _get_strong_plates(self) -> List[PlateStrengthScore]:
        """
        获取强势板块（前3名）

        优先从全局报价缓存读取数据，避免对未订阅股票发起API请求。

        Returns:
            强势板块列表，按强势度排序
        """
        try:
            # 获取所有板块
            plates_result = self.plate_manager.get_target_plates()
            if not plates_result or not plates_result.get('success'):
                return []

            plates = plates_result.get('plates', [])
            if not plates:
                return []

            # 计算每个板块的强势度
            plate_scores = []
            cache_hit = 0
            cache_miss = 0
            for plate in plates:
                # 获取板块内股票列表
                stocks = self.db_manager.stock_queries.get_stocks_by_plate(plate['code'])
                if not stocks:
                    continue

                stock_codes = [s['code'] for s in stocks]

                # 优先从全局报价缓存读取
                quotes_dict = {}
                if self.quote_cache:
                    cached = self.quote_cache.get_quotes_for_codes(stock_codes)
                    if cached:
                        quotes_dict = cached
                        cache_hit += 1

                # 缓存未命中时回退到实时API（向后兼容）
                if not quotes_dict:
                    cache_miss += 1
                    quotes_result = self.realtime_service.get_realtime_quotes(stock_codes)
                    if quotes_result and quotes_result.get('success'):
                        for quote in quotes_result.get('quotes', []):
                            if quote and isinstance(quote, dict) and 'code' in quote:
                                quotes_dict[quote['code']] = quote

                if not quotes_dict:
                    continue

                # 计算板块强势度
                score = self.plate_strength_service.calculate_plate_strength(
                    plate_code=plate['code'],
                    plate_name=plate['name'],
                    market=plate.get('market', 'HK'),
                    quotes=quotes_dict
                )

                if score and score.strength_score >= 70:  # 强势度阈值
                    plate_scores.append(score)

            if cache_hit > 0 or cache_miss > 0:
                self.logger.info(
                    f"板块强势度计算: 缓存命中 {cache_hit} 个板块, "
                    f"缓存未命中 {cache_miss} 个板块"
                )

            # 按强势度排序，取前3名
            plate_scores.sort(key=lambda x: x.strength_score, reverse=True)
            top_plates = plate_scores[:3]

            return top_plates

        except Exception as e:
            self.logger.error(f"获取强势板块失败: {e}", exc_info=True)
            return []

    async def check_positions_risk(self) -> List[Dict[str, Any]]:
        """
        检查持仓风险（止盈止损）

        委托给订单管理器处理

        Returns:
            风险检查结果列表
        """
        return await self.order_manager.check_positions_risk()
