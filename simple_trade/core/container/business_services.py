#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
业务服务初始化器 - 负责交易、策略、监控等业务服务
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
from ...services.market_data.hot_stock import HotStockCoordinator
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
from ...strategy.strategy_registry import StrategyRegistry, auto_discover_strategies
from ..coordination.strategy_dispatcher import StrategyDispatcher
from .core_services import CoreServices
from .data_services import DataServices


class BusinessServices:
    """业务服务容器 - 管理交易、策略、监控等业务逻辑"""

    def __init__(self, core: CoreServices, data: DataServices):
        self.core = core
        self.data = data

        # 业务服务
        self.alert_service: Optional[AlertChecker] = None
        self.futu_trade_service: Optional[FutuTradeService] = None
        self.trade_service: Optional[TradeService] = None
        self.strategy_monitor_service: Optional[StrategyMonitorService] = None
        self.strategy_screening_service: Optional[StrategyScreeningService] = None
        self.price_monitor_service: Optional[PriceMonitorService] = None
        self.hot_stock_service: Optional[HotStockCoordinator] = None
        self.aggressive_trade_service: Optional[AggressiveTradeService] = None
        self.lot_take_profit_service: Optional[LotTakeProfitService] = None
        self.lot_order_take_profit_service: Optional[LotOrderTakeProfitService] = None
        self.risk_coordinator: Optional[RiskCoordinator] = None
        self.dynamic_stop_loss_strategy: Optional[DynamicStopLossStrategy] = None
        self.signal_tracker = None

        # 策略相关
        self.strategy_registry: Optional[StrategyRegistry] = None
        self.strategy_dispatcher: Optional[StrategyDispatcher] = None

        # 决策助理
        self.decision_advisor = None

        # 日内超短线引擎
        self.scalping_engine = None

    def initialize(self):
        """初始化业务服务"""
        logging.info("开始初始化业务服务...")

        # 1. 策略注册表（自动发现，无需传参）
        auto_discover_strategies()
        logging.info(f"策略注册表初始化完成")

        # 2. 策略调度器
        self.strategy_dispatcher = StrategyDispatcher()
        logging.info("策略调度器初始化完成")

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

        # 9. 热门股票服务
        self.hot_stock_service = HotStockCoordinator(
            db_manager=self.core.db_manager,
            futu_client=self.core.futu_client,
            config=self.core.config
        )
        logging.info("热门股票服务初始化完成")

        # 10. 激进策略交易服务
        self.aggressive_trade_service = AggressiveTradeService(
            db_manager=self.core.db_manager,
            config=self.core.config,
            realtime_service=self.data.realtime_query,
            plate_manager=self.data.plate_manager,
            kline_service=self.data.kline_service
        )
        logging.info("激进策略交易服务初始化完成")

        # 11. 分仓止盈服务
        self.lot_take_profit_service = LotTakeProfitService(
            db_manager=self.core.db_manager,
            futu_trade_service=self.futu_trade_service,
        )
        logging.info("分仓止盈服务初始化完成")

        # 12. 单笔订单止盈服务
        self.lot_order_take_profit_service = LotOrderTakeProfitService(
            db_manager=self.core.db_manager,
            futu_trade_service=self.futu_trade_service,
        )
        logging.info("单笔订单止盈服务初始化完成")

        # 13. 动态止损策略
        self.dynamic_stop_loss_strategy = DynamicStopLossStrategy(
            realtime_query=self.data.realtime_query,
        )
        logging.info("动态止损策略初始化完成")

        # 14. 风险管理协调器（集成所有止损/止盈路径）
        self.risk_coordinator = RiskCoordinator(
            price_monitor_service=self.price_monitor_service,
            lot_take_profit_service=self.lot_take_profit_service,
            lot_order_take_profit_service=self.lot_order_take_profit_service,
            dynamic_stop_loss_strategy=self.dynamic_stop_loss_strategy,
            screening_engine=self.strategy_screening_service.engine if self.strategy_screening_service else None,
        )
        logging.info("风险管理协调器初始化完成")

        # 15. 信号追踪器
        from ...services.strategy.signal_tracker import SignalTracker
        self.signal_tracker = SignalTracker(self.core.db_manager)
        logging.info("信号追踪器初始化完成")

        # 16. 注入 AnalysisService 到价格位置参数缓存
        self._inject_analysis_service()

        # 17. 决策助理服务
        from ...services.advisor import HealthEvaluator, DecisionAdvisor, GeminiAnalyst
        health_evaluator = HealthEvaluator()

        # 初始化 Gemini 量化分析师（如果配置启用）
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
                capital_flow_analyzer=getattr(self.data, 'capital_flow_analyzer', None),
                big_order_tracker=getattr(self.data, 'big_order_tracker', None),
            )
            gemini_analyst = GeminiAnalyst(
                api_key=gemini_cfg['api_key'],
                model=gemini_cfg.get('model', 'gemini-3-flash-preview'),
                technical_service=tech_svc,
                config=analyst_cfg,
                proxy=gemini_cfg.get('proxy'),
            )
            logging.info("Gemini 量化分析师初始化完成")

        self.decision_advisor = DecisionAdvisor(
            health_evaluator=health_evaluator,
            gemini_analyst=gemini_analyst,
        )
        logging.info("决策助理服务初始化完成")

        # 18. 日内超短线引擎（Scalping Engine）
        self._init_scalping_engine()

        logging.info("业务服务初始化完成")

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

    def _init_scalping_engine(self):
        """初始化日内超短线引擎及其依赖的计算器组件

        依赖注入：
        - subscription_helper: 订阅管理（来自 DataServices）
        - realtime_query: 数据查询（来自 DataServices）
        - socket_manager: WebSocket 推送（全局单例）
        - persistence: Scalping 数据持久化服务
        """
        try:
            from ...websocket import get_socket_manager
            from ...services.scalping import (
                ScalpingEngine,
                DeltaCalculator,
                TapeVelocityMonitor,
                SpoofingFilter,
                POCCalculator,
                SignalEngine,
                OrderFlowDivergenceDetector,
                BreakoutSurvivalMonitor,
                VwapExtensionGuard,
                TickCredibilityFilter,
            )
            from ...services.scalping.persistence import ScalpingPersistence

            try:
                from ...services.scalping import StopLossMonitor
            except ImportError:
                StopLossMonitor = None

            socket_manager = get_socket_manager()

            # 持久化服务
            persistence = ScalpingPersistence(db_manager=self.core.db_manager)

            # 核心计算器
            delta_calculator = DeltaCalculator(socket_manager=socket_manager, persistence=persistence)
            tape_velocity = TapeVelocityMonitor(socket_manager=socket_manager)
            spoofing_filter = SpoofingFilter(socket_manager=socket_manager, persistence=persistence)
            poc_calculator = POCCalculator(socket_manager=socket_manager, persistence=persistence)

            # 新增检测器（需要在 SignalEngine 之前初始化）
            tick_credibility_filter = TickCredibilityFilter(
                socket_manager=socket_manager,
            )
            divergence_detector = OrderFlowDivergenceDetector(
                socket_manager=socket_manager,
                delta_calculator=delta_calculator,
            )
            breakout_monitor = BreakoutSurvivalMonitor(
                socket_manager=socket_manager,
                tape_velocity=tape_velocity,
                spoofing_filter=spoofing_filter,
            )
            vwap_guard = VwapExtensionGuard(socket_manager=socket_manager)

            # 注入持久化到所有检测器
            tape_velocity._persistence = persistence
            tick_credibility_filter._persistence = persistence
            divergence_detector._persistence = persistence
            breakout_monitor._persistence = persistence
            vwap_guard._persistence = persistence

            # OFI 计算器
            from ...services.scalping.calculators.ofi_calculator import OFICalculator
            ofi_calculator = OFICalculator()

            # 信号引擎（依赖 vwap_guard 和 ofi_calculator）
            signal_engine = SignalEngine(
                socket_manager=socket_manager,
                delta_calculator=delta_calculator,
                tape_velocity=tape_velocity,
                spoofing_filter=spoofing_filter,
                poc_calculator=poc_calculator,
                vwap_guard=vwap_guard,
                ofi_calculator=ofi_calculator,
                persistence=persistence,
            )
            stop_loss_monitor = (
                StopLossMonitor(socket_manager=socket_manager)
                if StopLossMonitor else None
            )

            from ...core.state import get_state_manager
            state_manager = get_state_manager()

            # 行为模式检测器 + 行动评分器
            from ...services.scalping.detectors.pattern_detector import PatternDetector
            from ...services.scalping.detectors.action_scorer import ActionScorer
            pattern_detector = PatternDetector()
            action_scorer = ActionScorer()

            # 协调器注入所有依赖
            self.scalping_engine = ScalpingEngine(
                subscription_helper=self.data.subscription_helper,
                realtime_query=self.data.realtime_query,
                socket_manager=socket_manager,
                delta_calculator=delta_calculator,
                tape_velocity=tape_velocity,
                spoofing_filter=spoofing_filter,
                poc_calculator=poc_calculator,
                signal_engine=signal_engine,
                tick_credibility_filter=tick_credibility_filter,
                divergence_detector=divergence_detector,
                breakout_monitor=breakout_monitor,
                vwap_guard=vwap_guard,
                stop_loss_monitor=stop_loss_monitor,
                futu_client=self.core.futu_client,
                persistence=persistence,
                state_manager=state_manager,
                subscription_manager=self.core.subscription_manager,
            )
            # 注入模式检测器（不修改构造函数签名）
            self.scalping_engine._pattern_detector = pattern_detector
            self.scalping_engine._action_scorer = action_scorer
            self.scalping_engine._ofi_calculator = ofi_calculator
            logging.info("日内超短线引擎初始化完成")

        except Exception as e:
            logging.warning(
                f"日内超短线引擎初始化失败（Scalping 功能不可用）: {e}"
            )



