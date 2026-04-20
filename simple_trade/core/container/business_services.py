#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
业务服务初始化器 - 负责交易、策略、监控等业务服务

A3 重构：
- 核心服务（交易、监控、风控）保持即时初始化
- 非核心服务（热股、Gemini、Scalping、微信等）改为 @property 懒加载
- 每个懒加载服务有 try-except 保护，初始化失败不影响其他服务
"""

import logging
from typing import Optional

from ...services import (
    FutuTradeService,
    TradeService,
    StrategyMonitorService,
    StrategyScreeningService,
    PriceMonitorService,
)
from ...services.alert.alert_checker import AlertChecker
from ...services.trading import (
    AggressiveTradeService,
    LotTakeProfitService,
    LotOrderTakeProfitService,
    RiskCoordinator,
)
from ...services.trading.risk.dynamic_stop_loss import (
    DynamicStopLossStrategy,
    DynamicStopLossConfig,
)
from ...services.trading.profit.intraday_profit_taker import IntradayProfitTaker
from ...strategy.strategy_registry import StrategyRegistry, auto_discover_strategies
from ..coordination.strategy_dispatcher import StrategyDispatcher
from .core_services import CoreServices
from .data_services import DataServices


class BusinessServices:
    """业务服务容器 - 管理交易、策略、监控等业务逻辑"""

    def __init__(self, core: CoreServices, data: DataServices):
        self.core = core
        self.data = data

        # ===== 核心服务（即时初始化） =====
        self.alert_service: Optional[AlertChecker] = None
        self.futu_trade_service: Optional[FutuTradeService] = None
        self.trade_service: Optional[TradeService] = None
        self.strategy_monitor_service: Optional[StrategyMonitorService] = None
        self.strategy_screening_service: Optional[StrategyScreeningService] = None
        self.price_monitor_service: Optional[PriceMonitorService] = None
        self.lot_take_profit_service: Optional[LotTakeProfitService] = None
        self.lot_order_take_profit_service: Optional[LotOrderTakeProfitService] = None
        self.risk_coordinator: Optional[RiskCoordinator] = None
        self.dynamic_stop_loss_strategy: Optional[DynamicStopLossStrategy] = None
        self.signal_tracker = None

        # 策略相关（即时）
        self.strategy_registry: Optional[StrategyRegistry] = None
        self.strategy_dispatcher: Optional[StrategyDispatcher] = None

        # ===== 非核心服务（懒加载，_xxx 前缀存储） =====
        self._hot_stock_service = None
        self._hot_stock_query_service = None
        self._market_heat_monitor = None
        self._heat_quote_service = None
        self._capital_analyzer = None
        self._big_order_tracker = None
        self._decision_advisor = None
        self._scalping_engine = None
        self._wechat_alert_service = None
        self._aggressive_trade_service = None
        self._intraday_profit_taker = None

    def initialize(self):
        """初始化业务服务（仅核心服务即时创建）"""
        logging.info("开始初始化业务服务...")

        # 1. 策略注册表（自动发现，无需传参）
        auto_discover_strategies()
        logging.info(f"策略注册表初始化完成")

        # 2. 策略调度器
        self.strategy_dispatcher = StrategyDispatcher()

        # 将 StrategyRegistry 中已发现的策略实例化并注册到调度器
        for strategy_name in StrategyRegistry.get_strategy_names():
            instance = StrategyRegistry.create_instance(
                strategy_name, data_service=self.core.stock_data_service
            )
            if instance:
                self.strategy_dispatcher.register(instance)
        logging.info(f"策略调度器初始化完成，已注册 {self.strategy_dispatcher.count} 个策略")

        # 3. 告警服务
        self.alert_service = AlertChecker(
            db_manager=self.core.db_manager,
            config=self.core.config
        )
        logging.info("告警服务初始化完成")

        # 4. 富途交易服务
        self.futu_trade_service = FutuTradeService(
            db_manager=self.core.db_manager,
            config=self.core.config
        )
        logging.info("富途交易服务初始化完成")

        # 5. 交易服务
        self.trade_service = TradeService(
            db_manager=self.core.db_manager,
            config=self.core.config,
            realtime_service=self.data.realtime_query,
            strategy_dispatcher=self.strategy_dispatcher
        )
        logging.info("交易服务初始化完成")

        # 6. 策略监控服务
        self.strategy_monitor_service = StrategyMonitorService(
            db_manager=self.core.db_manager,
            futu_client=self.core.futu_client,
            config=self.core.config
        )
        logging.info("策略监控服务初始化完成")

        # 7. 策略筛选服务
        self.strategy_screening_service = StrategyScreeningService(
            db_manager=self.core.db_manager,
            config=self.core.config,
            strategy_dispatcher=self.strategy_dispatcher
        )
        logging.info("策略筛选服务初始化完成")

        # 8. 价格监控服务
        self.price_monitor_service = PriceMonitorService(
            db_manager=self.core.db_manager,
            config=self.core.config,
            futu_trade_service=self.futu_trade_service
        )
        logging.info("价格监控服务初始化完成")

        # 9. 分仓止盈服务
        self.lot_take_profit_service = LotTakeProfitService(
            db_manager=self.core.db_manager,
            futu_trade_service=self.futu_trade_service,
        )
        logging.info("分仓止盈服务初始化完成")

        # 10. 单笔订单止盈服务
        self.lot_order_take_profit_service = LotOrderTakeProfitService(
            db_manager=self.core.db_manager,
            futu_trade_service=self.futu_trade_service,
        )
        logging.info("单笔订单止盈服务初始化完成")

        # 11. 动态止损策略
        self.dynamic_stop_loss_strategy = DynamicStopLossStrategy(
            realtime_query=self.data.realtime_query,
        )
        logging.info("动态止损策略初始化完成")

        # 12. 风险管理协调器（集成所有止损/止盈路径）
        self.risk_coordinator = RiskCoordinator(
            price_monitor_service=self.price_monitor_service,
            lot_take_profit_service=self.lot_take_profit_service,
            lot_order_take_profit_service=self.lot_order_take_profit_service,
            dynamic_stop_loss_strategy=self.dynamic_stop_loss_strategy,
            screening_engine=self.strategy_screening_service.engine if self.strategy_screening_service else None,
        )
        logging.info("风险管理协调器初始化完成")

        # 13. 信号追踪器
        from ...services.strategy.signal_tracker import SignalTracker
        self.signal_tracker = SignalTracker(self.core.db_manager)
        logging.info("信号追踪器初始化完成")

        # 14. 注入 AnalysisService 到价格位置参数缓存
        self._inject_analysis_service()

        logging.info("业务服务初始化完成（非核心服务将按需懒加载）")

    # ========== 非核心服务 @property 懒加载 ==========

    @property
    def hot_stock_service(self):
        if self._hot_stock_service is None:
            try:
                from ...services.market_data.hot_stock import HotStockCoordinator
                self._hot_stock_service = HotStockCoordinator(
                    db_manager=self.core.db_manager,
                    futu_client=self.core.futu_client,
                    config=self.core.config
                )
                logging.info("热门股票服务懒加载完成")
            except Exception as e:
                logging.warning(f"热门股票服务初始化失败: {e}")
        return self._hot_stock_service

    @property
    def hot_stock_query_service(self):
        if self._hot_stock_query_service is None:
            try:
                from ...services.market_data.hot_stock.hot_stock_query_service import HotStockQueryService
                self._hot_stock_query_service = HotStockQueryService(
                    db_manager=self.core.db_manager
                )
                logging.info("热门股票查询服务懒加载完成")
            except Exception as e:
                logging.warning(f"热门股票查询服务初始化失败: {e}")
        return self._hot_stock_query_service

    @property
    def market_heat_monitor(self):
        if self._market_heat_monitor is None:
            try:
                from ...services.analysis.heat import MarketHeatMonitor
                self._market_heat_monitor = MarketHeatMonitor(
                    db_manager=self.core.db_manager,
                    config=self.core.config
                )
                logging.info("市场热度监控器懒加载完成")
            except Exception as e:
                logging.warning(f"市场热度监控器初始化失败: {e}")
        return self._market_heat_monitor

    @property
    def heat_quote_service(self):
        if self._heat_quote_service is None:
            try:
                from ...services.analysis.heat import HeatQuoteService
                self._heat_quote_service = HeatQuoteService(
                    futu_client=self.core.futu_client
                )
                logging.info("热度报价服务懒加载完成")
            except Exception as e:
                logging.warning(f"热度报价服务初始化失败: {e}")
        return self._heat_quote_service

    @property
    def capital_analyzer(self):
        if self._capital_analyzer is None:
            try:
                from ...services.analysis.flow import CapitalFlowAnalyzer
                from dataclasses import asdict
                config_dict = asdict(self.core.config)
                self._capital_analyzer = CapitalFlowAnalyzer(
                    self.core.futu_client, self.core.db_manager, config_dict
                )
                logging.info("资金流向分析器懒加载完成")
            except Exception as e:
                logging.warning(f"资金流向分析器初始化失败: {e}")
        return self._capital_analyzer

    @property
    def big_order_tracker(self):
        if self._big_order_tracker is None:
            try:
                from ...services.analysis.flow import BigOrderTracker
                from dataclasses import asdict
                config_dict = asdict(self.core.config)
                self._big_order_tracker = BigOrderTracker(
                    self.core.futu_client, self.core.db_manager, config_dict
                )
                logging.info("大单追踪器懒加载完成")
            except Exception as e:
                logging.warning(f"大单追踪器初始化失败: {e}")
        return self._big_order_tracker

    @property
    def aggressive_trade_service(self):
        if self._aggressive_trade_service is None:
            try:
                self._aggressive_trade_service = AggressiveTradeService(
                    db_manager=self.core.db_manager,
                    config=self.core.config,
                    realtime_service=self.data.realtime_query,
                    plate_manager=self.data.plate_manager,
                    kline_service=self.data.kline_service,
                    quote_cache=self.core.quote_cache
                )
                logging.info("激进策略交易服务懒加载完成")
            except Exception as e:
                logging.warning(f"激进策略交易服务初始化失败: {e}")
        return self._aggressive_trade_service

    @property
    def intraday_profit_taker(self):
        if self._intraday_profit_taker is None:
            try:
                self._intraday_profit_taker = IntradayProfitTaker()
                logging.info("日内高抛低吸服务懒加载完成")
            except Exception as e:
                logging.warning(f"日内高抛低吸服务初始化失败: {e}")
        return self._intraday_profit_taker

    @property
    def decision_advisor(self):
        if self._decision_advisor is None:
            try:
                self._decision_advisor = self._create_decision_advisor()
                logging.info("决策助理服务懒加载完成")
            except Exception as e:
                logging.warning(f"决策助理服务初始化失败: {e}")
        return self._decision_advisor

    @property
    def scalping_engine(self):
        if self._scalping_engine is None:
            try:
                from ...services.scalping.scalping_factory import ScalpingFactory
                self._scalping_engine = ScalpingFactory.create(
                    core_services=self.core,
                    data_services=self.data,
                )
                logging.info("Scalping 引擎懒加载完成")
            except Exception as e:
                logging.warning(f"Scalping 引擎初始化失败: {e}", exc_info=True)
        return self._scalping_engine

    @property
    def wechat_alert_service(self):
        if self._wechat_alert_service is None:
            try:
                from ...services.alert.wechat_alert import WeChatAlertService
                self._wechat_alert_service = WeChatAlertService()
                logging.info("企业微信告警服务懒加载完成")
            except Exception as e:
                logging.warning(f"企业微信告警服务初始化失败: {e}")
        return self._wechat_alert_service

    # ========== 私有方法 ==========

    def _create_decision_advisor(self):
        """创建决策助理服务（含 Gemini 分析师可选初始化）"""
        from ...services.advisor import HealthEvaluator, DecisionAdvisor, GeminiAnalyst
        health_evaluator = HealthEvaluator()

        gemini_analyst = None
        gemini_cfg = self.core.config.gemini
        analyst_cfg = self.core.config.gemini_analyst
        if analyst_cfg.get('enabled') and gemini_cfg.get('api_key'):
            from ...services.market_data.vwap_service import VWAPService
            from ...services.market_data.order_book.order_book_service import OrderBookService
            from ...services.market_data.technical_service import TechnicalService

            vwap_svc = VWAPService(self.core.futu_client)
            ob_svc = OrderBookService(self.core.futu_client)
            tech_svc = TechnicalService(
                vwap_service=vwap_svc,
                order_book_service=ob_svc,
                capital_flow_analyzer=self.capital_analyzer,
                big_order_tracker=self.big_order_tracker,
            )
            gemini_analyst = GeminiAnalyst(
                api_key=gemini_cfg['api_key'],
                model=gemini_cfg.get('model', 'gemini-3-flash-preview'),
                technical_service=tech_svc,
                config=analyst_cfg,
                proxy=gemini_cfg.get('proxy'),
            )
            logging.info("Gemini 量化分析师初始化完成")

        return DecisionAdvisor(
            health_evaluator=health_evaluator,
            gemini_analyst=gemini_analyst,
        )

    def _inject_analysis_service(self):
        """将 AnalysisService 注入到策略监控服务的参数缓存管理器"""
        try:
            if not self.strategy_monitor_service:
                return
            from ...services.analysis import AnalysisService
            analysis_service = AnalysisService(
                db_manager=self.core.db_manager,
                kline_service=self.data.kline_service,
                futu_client=self.core.futu_client,
            )
            self.strategy_monitor_service.inject_analysis_service(analysis_service)
        except Exception as e:
            logging.warning(f"注入 AnalysisService 失败（价格位置实时策略不可用）: {e}")
