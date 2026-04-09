#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易状态管理器

从 StateManager 提取的交易领域状态，
负责管理交易条件和交易信号数据。
支持按策略分组的信号存储（多策略并行监控）。
"""

import copy
import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, List, Callable, Optional


class TradingState:
    """交易状态管理器 - 管理交易条件和交易信号"""

    def __init__(self):
        self._lock = threading.RLock()
        self._trading_conditions: Dict[str, Any] = {}
        self._trade_signals: List[Dict[str, Any]] = []
        # 按策略分组的信号存储
        self._signals_by_strategy: Dict[str, List[Dict[str, Any]]] = {}
        # 预警累积缓存：{stock_code:type -> alert_dict}
        self._alert_cache: Dict[str, Dict[str, Any]] = {}
        # 预警保留时长（秒）
        self._alert_retention_seconds = 600  # 10分钟
        # 状态变更回调（由 StateManager 注入）
        self._on_signals_changed: Optional[Callable] = None

    def set_signals_changed_callback(self, callback: Callable):
        """设置信号变更回调"""
        self._on_signals_changed = callback

    # ==================== 交易条件操作 ====================

    def get_trading_conditions(self) -> Dict[str, Any]:
        """获取交易条件数据"""
        with self._lock:
            return self._trading_conditions.copy()

    def update_trading_conditions(self, conditions: Dict[str, Any]):
        """更新交易条件数据"""
        with self._lock:
            self._trading_conditions.update(conditions)
        logging.debug(f"交易条件更新: {len(conditions)}条记录")

    def clear_trading_conditions(self):
        """清空交易条件数据"""
        with self._lock:
            self._trading_conditions = {}

    # ==================== 交易信号操作（向后兼容） ====================

    def get_trade_signals(self) -> List[Dict[str, Any]]:
        """获取所有交易信号（合并所有策略的信号）"""
        with self._lock:
            if self._signals_by_strategy:
                merged = []
                for signals in self._signals_by_strategy.values():
                    merged.extend(signals)
                return copy.deepcopy(merged)
            return self._trade_signals.copy()

    def set_trade_signals(self, signals: List[Dict[str, Any]]):
        """设置交易信号列表（向后兼容，同时按 strategy_id 分组存储）"""
        with self._lock:
            self._trade_signals = signals.copy()
            # 同步到按策略分组存储
            grouped: Dict[str, List[Dict[str, Any]]] = {}
            for signal in signals:
                sid = signal.get('strategy_id', '_default')
                grouped.setdefault(sid, []).append(signal)
            self._signals_by_strategy = grouped
        if self._on_signals_changed:
            self._on_signals_changed()
        logging.debug(f"交易信号更新: {len(signals)}条记录")

    def add_trade_signal(self, signal: Dict[str, Any]):
        """添加交易信号"""
        with self._lock:
            self._trade_signals.append(signal)
            sid = signal.get('strategy_id', '_default')
            self._signals_by_strategy.setdefault(sid, []).append(signal)
        if self._on_signals_changed:
            self._on_signals_changed()

    def clear_trade_signals(self):
        """清空交易信号"""
        with self._lock:
            self._trade_signals = []
            self._signals_by_strategy = {}

    # ==================== 按策略分组的信号操作 ====================

    def set_signals_by_strategy(self, signals_dict: Dict[str, List[Dict[str, Any]]]):
        """设置按策略分组的信号数据

        Args:
            signals_dict: {strategy_id: [signal_dict, ...]}
        """
        with self._lock:
            self._signals_by_strategy = copy.deepcopy(signals_dict)
            # 同步到兼容的 _trade_signals
            merged = []
            for signals in signals_dict.values():
                merged.extend(signals)
            self._trade_signals = merged
        if self._on_signals_changed:
            self._on_signals_changed()
        total = sum(len(v) for v in signals_dict.values())
        logging.debug(f"按策略分组信号更新: {len(signals_dict)}个策略, {total}条信号")

    def get_signals_by_strategy(self) -> Dict[str, List[Dict[str, Any]]]:
        """获取按策略分组的信号数据（深拷贝，防止外部修改）"""
        with self._lock:
            return copy.deepcopy(self._signals_by_strategy)

    def get_signals_for_strategy(self, strategy_id: str) -> List[Dict[str, Any]]:
        """获取指定策略的信号列表（深拷贝）"""
        with self._lock:
            signals = self._signals_by_strategy.get(strategy_id, [])
            return copy.deepcopy(signals)

    # ==================== 预警累积操作 ====================

    def accumulate_alerts(self, new_alerts: List[Dict[str, Any]]):
        """累积新预警到缓存，同 stock_code+type 只保留最新"""
        if not new_alerts:
            return
        with self._lock:
            for alert in new_alerts:
                key = f"{alert.get('stock_code', '')}:{alert.get('type', '')}"
                self._alert_cache[key] = alert
            self._cleanup_expired_alerts()

    def get_accumulated_alerts(self) -> List[Dict[str, Any]]:
        """获取累积的预警列表（按时间倒序）"""
        with self._lock:
            self._cleanup_expired_alerts()
            alerts = list(self._alert_cache.values())
        alerts.sort(
            key=lambda a: a.get('timestamp', ''), reverse=True
        )
        return alerts

    def _cleanup_expired_alerts(self):
        """清理过期预警（需在锁内调用）"""
        cutoff = datetime.now() - timedelta(seconds=self._alert_retention_seconds)
        expired_keys = [
            key for key, alert in self._alert_cache.items()
            if datetime.fromisoformat(alert.get('timestamp', '')) < cutoff
        ]
        for key in expired_keys:
            del self._alert_cache[key]

    def reset(self):
        """重置交易状态"""
        with self._lock:
            self._trading_conditions = {}
            self._trade_signals = []
            self._signals_by_strategy = {}
            self._alert_cache = {}
