"""
Scalping 引擎工厂

将 ScalpingEngine 的复杂组装逻辑从 business_services.py 提取到此处，
消除 monkey-patch 模式，提供清晰的工厂方法。

用法:
    engine = ScalpingFactory.create_inline_engine(
        core=core_services,
        data=data_services,
    )
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class ScalpingFactory:
    """Scalping 引擎工厂 - 统一管理引擎的创建和组装"""

    @staticmethod
    def create(core_services, data_services):
        """根据环境变量创建对应模式的 Scalping 引擎

        Args:
            core_services: CoreServices 实例（提供 futu_client, db_manager 等）
            data_services: DataServices 实例（提供 subscription_helper 等）

        Returns:
            ScalpingEngine 或 ScalpingProcessManager 实例，失败时返回 None
        """
        scalping_mode = os.environ.get('SCALPING_MODE', 'inline')

        if scalping_mode == 'process':
            return ScalpingFactory._create_process_engine(core_services)

        return ScalpingFactory._create_inline_engine(core_services, data_services)

    @staticmethod
    def _create_process_engine(core_services=None):
        """进程模式：创建 ScalpingProcessManager（子进程代理）"""
        try:
            from .scalping_process_manager import ScalpingProcessManager

            # 从配置读取超时参数
            process_cfg = None
            if core_services and hasattr(core_services, 'config'):
                process_cfg = getattr(core_services.config, 'scalping_process', None)

            engine = ScalpingProcessManager(process_config=process_cfg)
            logger.info("日内超短线引擎初始化完成（进程模式）")
            return engine
        except Exception as e:
            logger.warning(f"Scalping 进程模式初始化失败: {e}")
            return None

    @staticmethod
    def _create_inline_engine(core_services, data_services):
        """单进程模式：创建完整组装的 ScalpingEngine"""
        try:
            from simple_trade.websocket import get_socket_manager
            socket_manager = get_socket_manager()
        except Exception as e:
            logging.warning(f"获取 SocketManager 失败: {e}")
            return None

        try:
            from . import (
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
            from .persistence import ScalpingPersistence
            from .calculators.ofi_calculator import OFICalculator
            from .detectors.pattern_detector import PatternDetector
            from .detectors.action_scorer import ActionScorer

            try:
                from . import StopLossMonitor
            except ImportError:
                StopLossMonitor = None

            from simple_trade.core.state import get_state_manager
            state_manager = get_state_manager()

            # ── 持久化服务 ──
            persistence = ScalpingPersistence(db_manager=core_services.db_manager)

            # ── 核心计算器 ──
            delta_calculator = DeltaCalculator(
                socket_manager=socket_manager, persistence=persistence,
            )
            tape_velocity = TapeVelocityMonitor(socket_manager=socket_manager)
            spoofing_filter = SpoofingFilter(
                socket_manager=socket_manager, persistence=persistence,
            )
            poc_calculator = POCCalculator(
                socket_manager=socket_manager, persistence=persistence,
            )

            # ── 检测器 ──
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
            ofi_calculator = OFICalculator()

            # ── 注入持久化（通过构造函数参数注入） ──
            tape_velocity._persistence = persistence
            tick_credibility_filter._persistence = persistence
            divergence_detector._persistence = persistence
            breakout_monitor._persistence = persistence
            vwap_guard._persistence = persistence

            # ── 信号引擎 ──
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

            # ── 止损监控 ──
            stop_loss_monitor = (
                StopLossMonitor(socket_manager=socket_manager)
                if StopLossMonitor else None
            )

            # ── 行为模式检测器 + 行动评分器 ──
            pattern_detector = PatternDetector()
            action_scorer = ActionScorer()

            # ── 组装引擎 ──
            engine = ScalpingEngine(
                subscription_helper=data_services.subscription_helper,
                realtime_query=data_services.realtime_query,
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
                futu_client=core_services.futu_client,
                persistence=persistence,
                state_manager=state_manager,
                subscription_manager=core_services.subscription_manager,
            )

            # 注入可选组件（构造函数未包含，保持接口稳定）
            engine._pattern_detector = pattern_detector
            engine._action_scorer = action_scorer
            engine._ofi_calculator = ofi_calculator

            logging.info("日内超短线引擎初始化完成（inline 模式）")
            return engine

        except Exception as e:
            logging.warning(f"日内超短线引擎初始化失败: {e}", exc_info=True)
            return None
