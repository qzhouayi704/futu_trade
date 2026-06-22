#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
业务服务初始化器 - 负责交易、策略、监控等业务服务

A3 重构：
- 核心服务（交易、监控、风控）保持即时初始化
- 非核心服务（热股、Gemini、微信等）改为 @property 懒加载
- 每个懒加载服务有 try-except 保护，初始化失败不影响其他服务
"""

import logging
from typing import Any, Optional

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

        # Legacy BaseStrategy dispatcher. Current production scoring is StockScorer V2.
        self.strategy_registry: Optional[Any] = None
        self.strategy_dispatcher: Optional[Any] = None

        # ===== 非核心服务（懒加载，_xxx 前缀存储） =====
        self._hot_stock_service = None
        self._hot_stock_query_service = None
        self._market_heat_monitor = None
        self._heat_quote_service = None
        self._capital_analyzer = None
        self._big_order_tracker = None
        self._decision_advisor = None
        self._wechat_alert_service = None
        self._aggressive_trade_service = None
        self._intraday_profit_taker = None
        self._capital_flow_signal_engine = None
        self._baseline_service = None
        self._liquidity_calculator = None  # 新增：流动性计算器
        self._stock_scorer = None
        self._trade_frequency_guard = None
        self._trading_phase_manager = None
        self._capital_flow_rotator = None
        self._smart_position_manager = None
        self._stock_ai_analyzer = None
        self._trade_decision_engine = None

    def __getattr__(self, name: str):
        """代理到 core/data 子容器，使 DecisionEngine 等服务能访问 db_manager 等"""
        for attr in ('core', 'data'):
            try:
                sub = object.__getattribute__(self, attr)
                if sub is not None:
                    return getattr(sub, name)
            except AttributeError:
                continue
        raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")

    def initialize(self):
        """初始化业务服务（仅核心服务即时创建）"""
        logging.info("开始初始化业务服务...")

        # 1-2. StrategyDispatcher is a legacy BaseStrategy path. The live system now
        # uses StockScorer V2 (TREND/BREAKOUT/MOMENTUM) via the quote/sniper/momentum
        # pipeline, so old strategies are not auto-discovered or registered at startup.
        self.strategy_registry = None
        self.strategy_dispatcher = None
        logging.info("Legacy StrategyDispatcher disabled; using StockScorer V2 strategy pipeline")

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
            market_heat_monitor=self.market_heat_monitor,
            realtime_query=self.data.realtime_query,
            quote_cache=self.core.quote_cache,
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
    def baseline_service(self):
        if self._baseline_service is None:
            try:
                from ...services.baseline import BaselineService
                self._baseline_service = BaselineService(self.core.db_manager)
                logging.info("历史基准服务懒加载完成")
            except Exception as e:
                logging.warning(f"历史基准服务初始化失败: {e}")
        return self._baseline_service

    @property
    def capital_analyzer(self):
        if self._capital_analyzer is None:
            try:
                from ...services.analysis.flow import CapitalFlowAnalyzer
                from dataclasses import asdict
                config_dict = asdict(self.core.config)
                self._capital_analyzer = CapitalFlowAnalyzer(
                    self.core.futu_client, self.core.db_manager, config_dict,
                    baseline_service=self.baseline_service,
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
                    self.core.futu_client, self.core.db_manager, config_dict,
                    baseline_service=self.baseline_service,
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
    def capital_flow_signal_engine(self):
        if self._capital_flow_signal_engine is None:
            try:
                from ...services.analysis.flow import CapitalFlowSignalEngine

                # 初始化5分钟动量分析器
                momentum_analyzer = None
                try:
                    from ...services.analysis.momentum import Momentum5MinAnalyzer
                    momentum_analyzer = Momentum5MinAnalyzer(self.core.db_manager)
                    logging.info("5分钟动量分析器初始化完成")
                except Exception as e:
                    logging.warning(f"5分钟动量分析器初始化失败（信号引擎将不含动量数据）: {e}")

                self._capital_flow_signal_engine = CapitalFlowSignalEngine(
                    capital_flow_analyzer=self.capital_analyzer,
                    db_manager=self.core.db_manager,
                    futu_client=self.core.futu_client,
                    momentum_analyzer=momentum_analyzer,
                )
                logging.info("资金流向信号引擎懒加载完成")
            except Exception as e:
                logging.warning(f"资金流向信号引擎初始化失败: {e}")
        return self._capital_flow_signal_engine

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

        # 官方 Claude 客户端（优先引擎）；持仓顾问后台运行，effort=medium。
        from ...services.llm import build_claude_client_from_env
        claude_client = build_claude_client_from_env(effort="medium", thinking=True)

        # Claude 或 Gemini 任一可用即初始化分析师（需 analyst 开关打开以构建技术服务）。
        if analyst_cfg.get('enabled') and (gemini_cfg.get('api_key') or claude_client is not None):
            from ...services.market_data.vwap_service import VWAPService
            from ...services.market_data.order_book.order_book_service import OrderBookService
            from ...services.market_data.technical_service import TechnicalService

            vwap_svc = VWAPService(
                self.core.futu_client,
                global_coordinator=getattr(self.core, 'global_subscription_coordinator', None)
            )
            ob_svc = OrderBookService(
                self.core.futu_client,
                subscription_manager=self.core.subscription_manager
            )
            tech_svc = TechnicalService(
                vwap_service=vwap_svc,
                order_book_service=ob_svc,
                capital_flow_analyzer=self.capital_analyzer,
                big_order_tracker=self.big_order_tracker,
            )
            gemini_analyst = GeminiAnalyst(
                api_key=gemini_cfg.get('api_key', ''),
                model=gemini_cfg.get('model', 'gemini-3-flash-preview'),
                technical_service=tech_svc,
                config=analyst_cfg,
                proxy=gemini_cfg.get('proxy'),
                claude_config=self.core.config.claude,
                claude_client=claude_client,
            )
            _engine = claude_client.model if claude_client else gemini_cfg.get('model')
            logging.info(f"AI 量化分析师初始化完成 (引擎: {_engine})")

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

    @property
    def liquidity_calculator(self):
        """流动性计算器（懒加载）"""
        if self._liquidity_calculator is None:
            try:
                from ...services.market_data.liquidity_calculator import LiquidityCalculator
                # 获取流动性配置（如果不存在则传递空字典）
                liquidity_config = getattr(self.core.config, 'liquidity_filter', None)
                self._liquidity_calculator = LiquidityCalculator(
                    db_manager=self.core.db_manager,
                    config=liquidity_config
                )
                logging.info("流动性计算器懒加载完成")
            except Exception as e:
                logging.warning(f"流动性计算器初始化失败: {e}")
        return self._liquidity_calculator

    @property
    def stock_scorer(self):
        """标的评分引擎（懒加载）"""
        if self._stock_scorer is None:
            try:
                from ...services.strategy.stock_scorer import StockScorer
                self._stock_scorer = StockScorer()
                logging.info("标的评分引擎懒加载完成")
            except Exception as e:
                logging.warning(f"标的评分引擎初始化失败: {e}")
        return self._stock_scorer

    @property
    def trade_frequency_guard(self):
        """交易频率守卫（懒加载）"""
        if self._trade_frequency_guard is None:
            try:
                from ...services.trading.guard import TradeFrequencyGuard
                self._trade_frequency_guard = TradeFrequencyGuard()
                logging.info("交易频率守卫懒加载完成")
            except Exception as e:
                logging.warning(f"交易频率守卫初始化失败: {e}")
        return self._trade_frequency_guard

    @property
    def trading_phase_manager(self):
        """日内交易阶段管理器（懒加载）"""
        if self._trading_phase_manager is None:
            try:
                from ...services.strategy.trading_phase_manager import TradingPhaseManager
                self._trading_phase_manager = TradingPhaseManager()
                logging.info("日内交易阶段管理器懒加载完成")
            except Exception as e:
                logging.warning(f"日��交易阶段管理器初始化失败: {e}")
        return self._trading_phase_manager

    @property
    def capital_flow_rotator(self):
        """资金流换票引擎（懒加载）"""
        if self._capital_flow_rotator is None:
            try:
                from ...services.strategy.capital_flow_rotator import CapitalFlowRotator
                self._capital_flow_rotator = CapitalFlowRotator()
                logging.info("资金流换票引擎懒加载完成")
            except Exception as e:
                logging.warning(f"资金流换票引擎初始化失败: {e}")
        return self._capital_flow_rotator

    @property
    def smart_position_manager(self):
        """智能持仓管理器（懒加载）"""
        if self._smart_position_manager is None:
            try:
                from ...services.trading.risk.smart_position_manager import SmartPositionManager
                self._smart_position_manager = SmartPositionManager()
                logging.info("智能持仓管理器懒加载完成")
            except Exception as e:
                logging.warning(f"智能持仓管理器初始化失败: {e}")
        return self._smart_position_manager

    @property
    def stock_ai_analyzer(self):
        """AI 股票分析器（懒加载）"""
        if self._stock_ai_analyzer is None:
            try:
                import os
                from ...services.advisor.analyst.stock_ai_analyzer import StockAIAnalyzer
                from ...services.llm import build_claude_client_from_env

                # Claude 客户端（官方 SDK，读 ANTHROPIC_AUTH_TOKEN/ANTHROPIC_BASE_URL）。
                # 配置则优先用 Claude；未配置返回 None，自动回退 Gemini。
                # 交互式个股分析对延迟敏感 → effort=medium。
                claude_client = build_claude_client_from_env(effort="medium", thinking=True)

                # 优先读取 Vertex AI 环境变量
                project = os.environ.get('VERTEX_AI_PROJECT', '')
                location = os.environ.get('VERTEX_AI_LOCATION', 'global')
                credentials = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', '')
                model = os.environ.get('VERTEX_AI_MODEL', 'gemini-3.1-pro-preview')

                gemini_cfg = self.core.config.gemini
                api_key = gemini_cfg.get('api_key', '')
                proxy = gemini_cfg.get('proxy', '')

                _engine = (claude_client.model if claude_client else None)
                if project:
                    self._stock_ai_analyzer = StockAIAnalyzer(
                        model=model,
                        project=project,
                        location=location,
                        credentials_path=credentials,
                        proxy=proxy,
                        claude_client=claude_client,
                    )
                    logging.info(
                        f"AI 股票分析器懒加载完成 (引擎: {_engine or model}, "
                        f"Gemini 回退: Vertex AI {model})"
                    )
                elif api_key:
                    self._stock_ai_analyzer = StockAIAnalyzer(
                        model=gemini_cfg.get('model', model),
                        api_key=api_key,
                        proxy=proxy,
                        claude_client=claude_client,
                    )
                    logging.info(f"AI 股票分析器懒加载完成 (引擎: {_engine or 'Gemini API Key'})")
                elif claude_client:
                    # 仅 Claude（无 Gemini 凭证）
                    self._stock_ai_analyzer = StockAIAnalyzer(claude_client=claude_client)
                    logging.info(f"AI 股票分析器懒加载完成 (引擎: {_engine}, 无 Gemini 回退)")
                else:
                    logging.warning("AI 股票分析器跳过：未配置 Claude / Vertex AI / API Key")
            except Exception as e:
                logging.warning(f"AI 股票分析器初始化失败: {e}")
        return self._stock_ai_analyzer

    @property
    def trade_decision_engine(self):
        """统一交易决策引擎（懒加载）"""
        if self._trade_decision_engine is None:
            try:
                from ...services.trading.decision import UnifiedTradeDecisionEngine
                self._trade_decision_engine = UnifiedTradeDecisionEngine(
                    container=self, simulate=True  # 初期模拟模式
                )
                logging.info("统一交易决策引擎懒加载完成 (模拟模式)")
            except Exception as e:
                logging.warning(f"统一交易决策引擎初始化失败: {e}")
        return self._trade_decision_engine
