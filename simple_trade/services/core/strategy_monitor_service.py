#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""策略监控服务（协调器）- 管理多策略、预设、信号检测和历史"""

import logging
from typing import Dict, List, Any, Optional

from ...config.config import Config, ConfigManager
from ...database.core.db_manager import DatabaseManager
from ...strategy.base_strategy import BaseStrategy
from ..strategy.signal_detector import SignalDetector
from ..strategy.signal_history import SignalHistoryManager
from ..strategy.multi_strategy_manager import MultiStrategyManager
from ..strategy.models import DEFAULT_STRATEGIES
from ..trading.price_position import ParamsCacheManager


class StrategyMonitorService:
    """策略监控服务（协调器） - 支持两级选择（策略 + 预设）+ 多策略并行"""

    def __init__(self, db_manager: DatabaseManager, futu_client=None, config: Config = None):
        self.db_manager = db_manager
        self.futu_client = futu_client
        self.config = config

        # 加载策略配置
        self.strategies = self._load_strategies()

        # 当前激活的策略ID（向后兼容）
        self.active_strategy_id = self._get_active_strategy_id()

        # 当前激活的预设名称（向后兼容）
        self.active_preset_name = self._get_active_preset_name()

        # 策略实例（根据当前选择初始化）
        self.strategy = self._create_strategy()

        # 初始化子服务
        self._init_sub_services()

        # 初始化多策略管理器
        self.multi_strategy = MultiStrategyManager(self.strategies)

        # 初始化价格位置参数缓存管理器
        self.params_cache_manager = ParamsCacheManager()
        self.multi_strategy.set_strategy_post_init_hook(self._on_strategy_created)

        # 从 config.json 恢复已启用策略
        self._restore_enabled_strategies()

        logging.info(f"策略监控服务初始化完成，当前策略: {self.active_strategy_id}, 预设: {self.active_preset_name}")

    def _init_sub_services(self):
        """初始化子服务"""
        sc = self._active_strategy_config()
        strategy_name = sc.get('name', self.active_strategy_id)
        self.signal_detector = SignalDetector(
            strategy=self.strategy,
            strategy_id=self.active_strategy_id,
            strategy_name=strategy_name,
            preset_name=self.active_preset_name
        )
        self.signal_history_manager = SignalHistoryManager(
            db_manager=self.db_manager,
            max_memory_history=100
        )

    def _load_strategies(self) -> Dict[str, Dict[str, Any]]:
        """加载所有策略配置"""
        try:
            available = getattr(self.config, 'strategies', {}).get('available', {})
            strategies = available if available else DEFAULT_STRATEGIES
            logging.info(f"加载策略: {list(strategies.keys())}")
            return strategies
        except Exception as e:
            logging.error(f"加载策略失败: {e}")
            return DEFAULT_STRATEGIES

    def _get_active_strategy_id(self) -> str:
        try:
            return getattr(self.config, 'strategies', {}).get('active_strategy', 'trend_reversal')
        except Exception:
            return 'trend_reversal'

    def _get_active_preset_name(self) -> str:
        try:
            return self.strategies.get(self.active_strategy_id, {}).get('active_preset', 'B-建议')
        except Exception:
            return 'B-建议'

    def _create_strategy(self) -> BaseStrategy:
        """根据当前策略和预设，通过注册表创建策略实例"""
        from ..strategy.multi_strategy_manager import create_strategy_instance
        return create_strategy_instance(
            self.active_strategy_id, self.strategies, self.active_preset_name
        )

    def get_strategies(self) -> Dict[str, Dict[str, Any]]:
        """获取所有可用策略（用于策略选择下拉框）"""
        return {
            sid: {
                'id': sid, 'name': sc.get('name', sid),
                'description': sc.get('description', ''),
                'active_preset': sc.get('active_preset', ''),
                'preset_count': len(sc.get('presets', {}))
            }
            for sid, sc in self.strategies.items()
        }

    def get_active_strategy(self) -> Dict[str, Any]:
        """获取当前激活的策略信息"""
        sc = self._active_strategy_config()
        return {
            'id': self.active_strategy_id,
            'name': sc.get('name', self.active_strategy_id),
            'description': sc.get('description', ''),
            'active_preset': self.active_preset_name,
            'presets': list(sc.get('presets', {}).keys())
        }

    def set_active_strategy(self, strategy_id: str) -> Dict[str, Any]:
        """切换当前策略"""
        if strategy_id not in self.strategies:
            return {'success': False, 'message': f"策略 '{strategy_id}' 不存在"}
        try:
            self.active_strategy_id = strategy_id
            sc = self.strategies[strategy_id]
            presets = sc.get('presets', {})
            self.active_preset_name = sc.get('active_preset',
                list(presets.keys())[0] if presets else 'default')
            self.strategy = self._create_strategy()
            self._update_signal_detector()
            logging.info(f"切换策略: {strategy_id}, 预设: {self.active_preset_name}")
            return {
                'success': True,
                'message': f"已切换到策略 '{sc.get('name', strategy_id)}'",
                'strategy': self.get_active_strategy(),
                'preset': self.get_active_preset()
            }
        except Exception as e:
            logging.error(f"切换策略失败: {e}")
            return {'success': False, 'message': f"切换失败: {str(e)}"}

    def _update_signal_detector(self):
        """更新信号检测器的策略配置"""
        sc = self._active_strategy_config()
        self.signal_detector.update_strategy(
            strategy=self.strategy,
            strategy_id=self.active_strategy_id,
            strategy_name=sc.get('name', self.active_strategy_id),
            preset_name=self.active_preset_name
        )

    def get_presets(self) -> Dict[str, Dict[str, Any]]:
        return self._active_strategy_config().get('presets', {})

    def get_presets_by_strategy(self, strategy_id: str) -> Dict[str, Dict[str, Any]]:
        return self.strategies.get(strategy_id, {}).get('presets', {})

    def get_active_preset(self) -> Dict[str, Any]:
        """获取当前激活的预设详情"""
        sc = self._active_strategy_config()
        preset = sc.get('presets', {}).get(self.active_preset_name, {})
        return {
            'name': self.active_preset_name,
            'preset': preset,
            'strategy_id': self.active_strategy_id,
            'strategy_name': sc.get('name', self.active_strategy_id)
        }

    def set_active_preset(self, preset_name: str) -> Dict[str, Any]:
        """切换当前策略的预设"""
        presets = self._active_strategy_config().get('presets', {})
        if preset_name not in presets:
            return {'success': False, 'message': f"预设 '{preset_name}' 不存在"}
        try:
            self.active_preset_name = preset_name
            self.strategy = self._create_strategy()
            self._update_signal_detector()
            logging.info(f"切换预设: {preset_name}")
            return {'success': True, 'message': f"已切换到预设 '{preset_name}'", 'preset': presets[preset_name]}
        except Exception as e:
            logging.error(f"切换预设失败: {e}")
            return {'success': False, 'message': f"切换失败: {str(e)}"}

    def check_signals(
        self,
        quotes: List[Dict[str, Any]],
        kline_data: Dict[str, List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """检查股票池中所有股票的买卖信号（向后兼容单策略接口）"""
        signals = self.signal_detector.check_signals(quotes, kline_data)
        for signal in signals:
            self.signal_history_manager.add_signal(signal)
        return signals

    def analyze_stock(self, quote: Dict[str, Any], klines: List[Dict[str, Any]]) -> Dict[str, Any]:
        return self.signal_detector.analyze_stock(quote, klines)

    def get_signal_history(self, limit: int = 50, days: int = 7) -> List[Dict[str, Any]]:
        """获取信号历史（从数据库读取，按天去重）"""
        sc = self._active_strategy_config()
        return self.signal_history_manager.get_history(
            limit=limit, days=days,
            strategy_id=self.active_strategy_id,
            strategy_name=sc.get('name', self.active_strategy_id),
            preset_name=self.active_preset_name
        )

    def clear_signal_history(self):
        self.signal_history_manager.clear_memory_history()

    def get_signal_statistics(self, days: int = 7) -> Dict[str, Any]:
        return self.signal_history_manager.get_statistics(days=days)

    def _active_strategy_config(self) -> Dict[str, Any]:
        """获取当前激活策略的配置"""
        return self.strategies.get(self.active_strategy_id, {})

    def get_service_status(self) -> Dict[str, Any]:
        """获取服务状态"""
        sc = self._active_strategy_config()
        presets = sc.get('presets', {})
        return {
            'active_strategy_id': self.active_strategy_id,
            'active_strategy_name': sc.get('name', self.active_strategy_id),
            'active_preset_name': self.active_preset_name,
            'preset_config': presets.get(self.active_preset_name, {}),
            'available_strategies': list(self.strategies.keys()),
            'available_presets': list(presets.keys()),
            'signal_history_count': self.signal_history_manager.get_memory_history_count(),
        }

    def get_strategy_indicators(self) -> Dict[str, Any]:
        """获取当前策略的详细指标信息"""
        sc = self._active_strategy_config()
        preset = sc.get('presets', {}).get(self.active_preset_name, {})
        s = self.strategy
        return {
            'strategy_id': self.active_strategy_id,
            'strategy_name': sc.get('name', self.active_strategy_id),
            'strategy_description': sc.get('description', ''),
            'preset_name': self.active_preset_name,
            'preset_description': preset.get('description', ''),
            'parameters': preset,
            'buy_conditions': s.get_buy_conditions() if hasattr(s, 'get_buy_conditions') else [],
            'sell_conditions': s.get_sell_conditions() if hasattr(s, 'get_sell_conditions') else [],
            'stop_loss_conditions': s.get_stop_loss_conditions() if hasattr(s, 'get_stop_loss_conditions') else [],
        }

    def enable_strategy(self, strategy_id: str, preset_name: str) -> Dict[str, Any]:
        """启用一个策略"""
        result = self.multi_strategy.enable_strategy(strategy_id, preset_name)
        if result.get('success'):
            self._persist_enabled_strategies()
        return result

    def disable_strategy(self, strategy_id: str) -> Dict[str, Any]:
        """禁用一个策略"""
        result = self.multi_strategy.disable_strategy(strategy_id)
        if result.get('success'):
            self._persist_enabled_strategies()
        return result

    def update_strategy_preset(self, strategy_id: str, preset_name: str) -> Dict[str, Any]:
        """修改已启用策略的预设"""
        result = self.multi_strategy.update_strategy_preset(strategy_id, preset_name)
        if result.get('success'):
            self._persist_enabled_strategies()
        return result

    def get_enabled_strategies(self) -> List[Dict[str, Any]]:
        return self.multi_strategy.get_enabled_strategies()

    def check_signals_all(
        self,
        quotes: List[Dict[str, Any]],
        kline_data: Dict[str, List[Dict[str, Any]]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """遍历所有已启用策略执行信号检测"""
        results = self.multi_strategy.check_signals_all(quotes, kline_data)
        # 将所有信号添加到历史记录
        for signals in results.values():
            for signal in signals:
                self.signal_history_manager.add_signal(signal)
        return results

    def set_auto_trade_strategy(self, strategy_id: str) -> Dict[str, Any]:
        """设置自动交易跟随策略"""
        result = self.multi_strategy.set_auto_trade_strategy(strategy_id)
        if result.get('success'):
            self._persist_enabled_strategies()
        return result

    def get_auto_trade_strategy(self) -> Optional[str]:
        return self.multi_strategy.get_auto_trade_strategy()

    # ==================== 配置持久化 ====================

    def inject_analysis_service(self, analysis_service) -> None:
        """注入 AnalysisService（系统启动后调用）"""
        self.params_cache_manager.set_analysis_service(analysis_service)
        logging.info("已注入 AnalysisService 到参数缓存管理器")

    def _on_strategy_created(self, strategy_id: str, instance) -> None:
        """策略实例创建后的回调，用于注入依赖"""
        if strategy_id == 'price_position_live' and hasattr(instance, 'set_params_cache'):
            instance.set_params_cache(self.params_cache_manager)
            logging.info("已注入 ParamsCacheManager 到日内价格位置策略")

    def _persist_enabled_strategies(self) -> None:
        """将已启用策略持久化到 config.json"""
        self.multi_strategy.persist_to_config(ConfigManager.DEFAULT_CONFIG_PATH)

    def _restore_enabled_strategies(self) -> None:
        """从 config.json 恢复已启用策略"""
        strategies_config = getattr(self.config, 'strategies', {})
        self.multi_strategy.restore_from_config(strategies_config)
