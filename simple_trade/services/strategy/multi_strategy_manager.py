#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多策略管理器 - 管理多策略启用/禁用、预设切换、信号检测协调和自动交易策略选择"""

import json
import logging
import os
from typing import Dict, List, Any, Optional, Callable

from ...strategy.base_strategy import BaseStrategy
from ...strategy.strategy_registry import StrategyRegistry
from .models import EnabledStrategyInfo, EnabledStrategyConfig
from .signal_detector import SignalDetector


class MultiStrategyManager:
    """多策略管理器 - 管理多个已启用策略的生命周期"""

    def __init__(self, strategies_config: Dict[str, Dict[str, Any]]):
        """
        Args:
            strategies_config: 所有可用策略的配置（来自 config.json 的 strategies.available）
        """
        self._strategies_config = strategies_config
        self.enabled_strategies: Dict[str, EnabledStrategyInfo] = {}
        self.auto_trade_strategy_id: Optional[str] = None
        self._post_init_hook: Optional[Callable] = None

    def set_strategy_post_init_hook(self, hook: Callable[[str, BaseStrategy], None]):
        """设置策略实例创建后的回调（用于注入依赖）"""
        self._post_init_hook = hook

    # ==================== 策略启用/禁用 ====================

    def enable_strategy(self, strategy_id: str, preset_name: str) -> Dict[str, Any]:
        """启用一个策略，返回 {success, message, data?}"""
        if strategy_id not in self._strategies_config:
            return {'success': False, 'message': f"策略 '{strategy_id}' 不存在"}

        strategy_config = self._strategies_config[strategy_id]
        presets = strategy_config.get('presets', {})

        # 验证预设存在
        if preset_name not in presets:
            return {'success': False, 'message': f"预设 '{preset_name}' 不存在"}

        try:
            info = self._create_enabled_strategy(strategy_id, strategy_config, preset_name)
            self.enabled_strategies[strategy_id] = info
            logging.info(f"已启用策略: {strategy_id}, 预设: {preset_name}")
            return {
                'success': True,
                'message': f"已启用策略 '{info.strategy_name}'",
                'data': info.to_dict()
            }
        except Exception as e:
            logging.error(f"启用策略失败 {strategy_id}: {e}")
            return {'success': False, 'message': f"启用失败: {str(e)}"}

    def disable_strategy(self, strategy_id: str) -> Dict[str, Any]:
        """禁用一个策略"""
        if strategy_id not in self.enabled_strategies:
            return {'success': False, 'message': f"策略 '{strategy_id}' 未启用"}

        info = self.enabled_strategies.pop(strategy_id)
        auto_trade_paused = False

        # 如果禁用的是自动交易策略，自动暂停
        if self.auto_trade_strategy_id == strategy_id:
            self.auto_trade_strategy_id = None
            auto_trade_paused = True

        logging.info(f"已禁用策略: {strategy_id}")
        return {
            'success': True,
            'message': f"已禁用策略 '{info.strategy_name}'",
            'auto_trade_paused': auto_trade_paused
        }

    def update_strategy_preset(self, strategy_id: str, preset_name: str) -> Dict[str, Any]:
        """修改已启用策略的预设"""
        if strategy_id not in self.enabled_strategies:
            return {'success': False, 'message': f"策略 '{strategy_id}' 未启用"}

        strategy_config = self._strategies_config.get(strategy_id, {})
        presets = strategy_config.get('presets', {})

        if preset_name not in presets:
            return {'success': False, 'message': f"预设 '{preset_name}' 不存在"}

        try:
            info = self._create_enabled_strategy(strategy_id, strategy_config, preset_name)
            self.enabled_strategies[strategy_id] = info
            logging.info(f"策略 {strategy_id} 预设已切换为: {preset_name}")
            return {
                'success': True,
                'message': f"预设已切换为 '{preset_name}'",
                'data': info.to_dict()
            }
        except Exception as e:
            logging.error(f"切换预设失败 {strategy_id}: {e}")
            return {'success': False, 'message': f"切换失败: {str(e)}"}

    def get_enabled_strategies(self) -> List[Dict[str, Any]]:
        """获取所有已启用策略的信息列表"""
        return [info.to_dict() for info in self.enabled_strategies.values()]

    # ==================== 自动交易策略 ====================

    def set_auto_trade_strategy(self, strategy_id: str) -> Dict[str, Any]:
        """设置自动交易跟随策略"""
        if strategy_id not in self.enabled_strategies:
            return {
                'success': False,
                'message': f"策略 '{strategy_id}' 未在已启用策略中"
            }

        self.auto_trade_strategy_id = strategy_id
        name = self.enabled_strategies[strategy_id].strategy_name
        logging.info(f"自动交易跟随策略设置为: {strategy_id}")
        return {
            'success': True,
            'message': f"自动交易已跟随策略 '{name}'"
        }

    def get_auto_trade_strategy(self) -> Optional[str]:
        """获取当前自动交易跟随策略 ID"""
        return self.auto_trade_strategy_id

    # ==================== 信号检测 ====================

    def check_signals_all(
        self,
        quotes: List[Dict[str, Any]],
        kline_data: Dict[str, List[Dict[str, Any]]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """遍历所有已启用策略执行信号检测，返回 {strategy_id: [signal_dict]}"""
        results: Dict[str, List[Dict[str, Any]]] = {}

        for strategy_id, info in self.enabled_strategies.items():
            try:
                signals = info.signal_detector.check_signals(quotes, kline_data)
                results[strategy_id] = signals

                # 更新信号计数
                info.signal_count_buy = sum(
                    1 for s in signals if s.get('signal_type') == 'BUY'
                )
                info.signal_count_sell = sum(
                    1 for s in signals if s.get('signal_type') == 'SELL'
                )
            except Exception as e:
                logging.error(f"策略 {strategy_id} 信号检测异常: {e}")
                results[strategy_id] = []

        return results

    # ==================== 配置导出 ====================

    def get_enabled_configs(self) -> List[EnabledStrategyConfig]:
        """导出当前已启用策略的持久化配置"""
        return [
            EnabledStrategyConfig(
                strategy_id=sid,
                preset_name=info.preset_name
            )
            for sid, info in self.enabled_strategies.items()
        ]

    def update_strategies_config(self, strategies_config: Dict[str, Dict[str, Any]]):
        """更新可用策略配置（config 热更新时调用）"""
        self._strategies_config = strategies_config

    # ==================== 配置持久化 ====================

    def persist_to_config(self, config_path: str) -> None:
        """将已启用策略和自动交易策略持久化到 config.json"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            strategies = data.setdefault('strategies', {})
            strategies['enabled_strategies'] = [
                c.to_dict() for c in self.get_enabled_configs()
            ]
            strategies['auto_trade_strategy'] = self.auto_trade_strategy_id

            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            logging.info("已启用策略配置已持久化")
        except Exception as e:
            logging.error(f"持久化已启用策略失败: {e}")

    def restore_from_config(self, strategies_config: dict) -> None:
        """从 strategies 配置字典恢复已启用策略"""
        try:
            enabled_list = strategies_config.get('enabled_strategies', None)

            if not isinstance(enabled_list, list):
                self._apply_default_enabled()
                return

            restored = False
            for item in enabled_list:
                cfg = EnabledStrategyConfig.from_dict(item) if isinstance(item, dict) else None
                if cfg and cfg.strategy_id in self._strategies_config:
                    result = self.enable_strategy(cfg.strategy_id, cfg.preset_name)
                    if result.get('success'):
                        restored = True

            # 恢复自动交易策略
            auto_trade = strategies_config.get('auto_trade_strategy')
            if auto_trade and auto_trade in self.enabled_strategies:
                self.set_auto_trade_strategy(auto_trade)

            if not restored:
                self._apply_default_enabled()
        except Exception as e:
            logging.warning(f"恢复已启用策略失败，使用默认配置: {e}")
            self._apply_default_enabled()

    def _apply_default_enabled(self) -> None:
        """应用默认已启用策略：仅启用 trend_reversal + B-建议"""
        self.enable_strategy('trend_reversal', 'B-建议')

    # ==================== 内部方法 ====================

    def _create_enabled_strategy(
        self,
        strategy_id: str,
        strategy_config: Dict[str, Any],
        preset_name: str
    ) -> EnabledStrategyInfo:
        """创建已启用策略的完整信息（实例 + 检测器）"""
        presets = strategy_config.get('presets', {})
        preset = presets.get(preset_name, {})
        strategy_name = strategy_config.get('name', strategy_id)

        # 构建策略参数（复用模块级辅助函数）
        config = _build_strategy_config(preset)

        # 通过注册表创建策略实例
        instance = StrategyRegistry.create_instance(strategy_id, config=config)
        if not instance:
            instance = StrategyRegistry.create_instance(config=config)
        if not instance:
            raise ValueError(f"无法创建策略实例: {strategy_id}")

        # 调用创建后回调（注入依赖）
        if self._post_init_hook:
            try:
                self._post_init_hook(strategy_id, instance)
            except Exception as e:
                logging.warning(f"策略创建后回调失败 {strategy_id}: {e}")

        # 创建信号检测器
        detector = SignalDetector(
            strategy=instance,
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            preset_name=preset_name
        )

        return EnabledStrategyInfo(
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            preset_name=preset_name,
            instance=instance,
            signal_detector=detector,
        )


def _build_strategy_config(preset: Dict[str, Any]) -> Dict[str, Any]:
    """从预设参数构建策略配置字典（消除重复逻辑）"""
    return {
        'lookback_days': preset.get('lookback_days', 10),
        'min_drop_pct': preset.get('min_drop_pct', 13.0),
        'min_rise_pct': preset.get('min_rise_pct', 12.0),
        'min_reversal_pct': preset.get('min_reversal_pct', 2.0),
        'max_up_ratio_buy': preset.get('max_up_ratio_buy', 0.5),
        'min_up_ratio_sell': preset.get('min_up_ratio_sell', 0.6),
        'stop_loss_pct': preset.get('stop_loss_pct', -5.0),
        'stop_loss_days': preset.get('stop_loss_days', 3),
    }


def create_strategy_instance(
    strategy_id: str,
    strategies_config: Dict[str, Dict[str, Any]],
    preset_name: str
) -> BaseStrategy:
    """根据策略 ID 和预设名称创建策略实例（供 StrategyMonitorService 调用）"""
    preset = strategies_config.get(strategy_id, {}).get('presets', {}).get(preset_name, {})
    config = _build_strategy_config(preset)
    instance = StrategyRegistry.create_instance(strategy_id, config=config)
    if not instance:
        instance = StrategyRegistry.create_instance(config=config)
    if not instance:
        raise ValueError(f"无法创建策略实例: {strategy_id}")
    return instance

