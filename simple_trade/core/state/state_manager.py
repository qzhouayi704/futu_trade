#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一状态管理器 - 兼容层

保持原有单例模式和所有方法签名不变，
内部委托给领域状态管理器：
- QuoteCache: 报价缓存
- TradingState: 交易状态
- PoolState: 股票池状态
- InitProgress: 初始化进度

订阅状态、系统运行状态、回调机制暂时保留在本类中。
"""

import logging
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable

from simple_trade.core.state.quote_cache import QuoteCache
from simple_trade.core.state.trading_state import TradingState
from simple_trade.core.state.pool_state import PoolState
from simple_trade.core.state.init_progress import InitProgress
from simple_trade.core.state.scalping_metrics import ScalpingMetrics, ScalpingMetricsState
from simple_trade.core.state.ticker_df_cache import TickerDataFrameCache


class StateManager:
    """统一状态管理器 - 单例模式（兼容层）"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self._state_lock = threading.RLock()

        # ========== 领域状态管理器 ==========
        self.quote_cache = QuoteCache()
        self.trading_state = TradingState()
        self.pool_state = PoolState()
        self.init_progress = InitProgress()
        self.scalping_metrics = ScalpingMetricsState()
        self.ticker_df_cache = TickerDataFrameCache()

        # ========== 订阅状态（暂保留） ==========
        self._subscribed_stocks: set = set()
        self._subscription_version: Optional[str] = None
        self._subscription_initialized: bool = False

        # ========== 系统运行状态（暂保留） ==========
        self._is_running: bool = False
        self._last_update: Optional[datetime] = None

        # ========== 状态变更回调（暂保留） ==========
        self._callbacks: Dict[str, List[Callable]] = {}

        # ========== 依赖注入 ==========
        self._subscription_manager: Optional[Any] = None

        # 注入回调到子模块
        self.pool_state.set_pool_changed_callback(
            lambda: self._notify_callbacks('stock_pool_changed')
        )
        self.trading_state.set_signals_changed_callback(
            lambda: self._notify_callbacks('trade_signals_changed')
        )

        logging.info("StateManager 初始化完成（兼容层）")

    # ==================== 股票池操作（委托 PoolState） ====================

    def get_stock_pool(self) -> Dict[str, Any]:
        return self.pool_state.get_stock_pool()

    def set_stock_pool(self, plates: List[Dict], stocks: List[Dict]):
        self.pool_state.set_stock_pool(plates, stocks)

    def get_active_stocks(self, limit: Optional[int] = None) -> List[tuple]:
        return self.pool_state.get_active_stocks(limit)

    def is_stock_pool_initialized(self) -> bool:
        return self.pool_state.is_stock_pool_initialized()

    # ==================== 初始化进度操作（委托 InitProgress） ====================

    def get_init_progress(self) -> Dict[str, Any]:
        return self.init_progress.get_init_progress()

    def start_init_progress(self, total_steps: int = 0):
        self.init_progress.start_init_progress(total_steps)

    def update_init_progress(self, step: int = None, action: str = None,
                            total: int = None, error: str = None):
        self.init_progress.update_init_progress(step, action, total, error)

    def finish_init_progress(self, success: bool = True, error: str = None):
        self.init_progress.finish_init_progress(success, error)

    # ==================== 报价缓存操作（委托 QuoteCache） ====================

    def set_quotes_ttl(self, ttl: int):
        self.quote_cache.set_quotes_ttl(ttl)

    def get_cached_quotes(self) -> Optional[List[Dict]]:
        return self.quote_cache.get_cached_quotes()

    def update_quotes_cache(self, quotes: List[Dict]):
        self.quote_cache.update_quotes_cache(quotes)

    def invalidate_quotes_cache(self):
        self.quote_cache.invalidate_quotes_cache()

    def is_quotes_cache_valid(self) -> bool:
        return self.quote_cache.is_quotes_cache_valid()

    # ==================== 交易条件操作（委托 TradingState） ====================

    def get_trading_conditions(self) -> Dict[str, Any]:
        return self.trading_state.get_trading_conditions()

    def update_trading_conditions(self, conditions: Dict[str, Any]):
        self.trading_state.update_trading_conditions(conditions)

    def clear_trading_conditions(self):
        self.trading_state.clear_trading_conditions()

    # ==================== 交易信号操作（委托 TradingState） ====================

    def get_trade_signals(self) -> List[Dict[str, Any]]:
        return self.trading_state.get_trade_signals()

    def set_trade_signals(self, signals: List[Dict[str, Any]]):
        self.trading_state.set_trade_signals(signals)

    def add_trade_signal(self, signal: Dict[str, Any]):
        self.trading_state.add_trade_signal(signal)

    def clear_trade_signals(self):
        self.trading_state.clear_trade_signals()

    # ==================== 按策略分组的信号操作（委托 TradingState） ====================

    def set_signals_by_strategy(self, signals_dict: Dict[str, List[Dict[str, Any]]]):
        self.trading_state.set_signals_by_strategy(signals_dict)

    def get_signals_by_strategy(self) -> Dict[str, List[Dict[str, Any]]]:
        return self.trading_state.get_signals_by_strategy()

    def get_signals_for_strategy(self, strategy_id: str) -> List[Dict[str, Any]]:
        return self.trading_state.get_signals_for_strategy(strategy_id)

    # ==================== 预警累积操作（委托 TradingState） ====================

    def accumulate_alerts(self, alerts: List[Dict[str, Any]]):
        self.trading_state.accumulate_alerts(alerts)

    def get_accumulated_alerts(self) -> List[Dict[str, Any]]:
        return self.trading_state.get_accumulated_alerts()

    # ==================== 订阅状态操作（暂保留） ====================

    def get_subscribed_stocks(self) -> set:
        with self._state_lock:
            return self._subscribed_stocks.copy()

    def add_subscribed_stocks(self, codes: List[str]):
        with self._state_lock:
            self._subscribed_stocks.update(codes)

    def clear_subscribed_stocks(self):
        with self._state_lock:
            self._subscribed_stocks.clear()

    def is_subscription_initialized(self) -> bool:
        with self._state_lock:
            return self._subscription_initialized

    def set_subscription_initialized(self, initialized: bool, version: str = None):
        with self._state_lock:
            self._subscription_initialized = initialized
            if version:
                self._subscription_version = version

    def get_subscription_version(self) -> Optional[str]:
        with self._state_lock:
            return self._subscription_version

    # ==================== 依赖注入 ====================

    def set_subscription_manager(self, subscription_manager):
        """设置订阅管理器（用于获取已订阅股票）"""
        self._subscription_manager = subscription_manager
        logging.debug("SubscriptionManager 已注入到 StateManager")

    def get_target_stocks(self) -> List[Dict[str, Any]]:
        """获取策略监控的目标股票（已订阅股票）

        Returns:
            已订阅股票列表，格式: [{'id': 1, 'code': 'US.AAPL', 'name': '苹果', ...}]
        """
        with self._state_lock:
            if not self._subscription_manager:
                logging.warning("SubscriptionManager 未设置，返回空列表")
                return []

            try:
                subscribed_codes = list(self._subscription_manager.subscribed_stocks)
                if not subscribed_codes:
                    return []

                stocks = self.pool_state.get_stocks()
                target_stocks = [
                    stock for stock in stocks
                    if stock.get('code') in subscribed_codes
                ]
                return target_stocks

            except Exception as e:
                logging.error(f"获取目标股票失败: {e}")
                return []

    # ==================== Scalping 指标共享（委托 ScalpingMetricsState） ====================

    def set_scalping_metrics(self, stock_code: str, metrics: ScalpingMetrics) -> None:
        """写入 Scalping 指标快照（由 Scalping 系统调用）"""
        self.scalping_metrics.set(stock_code, metrics)

    def get_scalping_metrics(self, stock_code: str) -> Optional[ScalpingMetrics]:
        """读取 Scalping 指标快照，过期返回 None（由 Strategy 系统调用）"""
        return self.scalping_metrics.get(stock_code)

    # ==================== 系统运行状态（暂保留） ====================

    def is_running(self) -> bool:
        with self._state_lock:
            return self._is_running

    def set_running(self, running: bool):
        with self._state_lock:
            self._is_running = running

    def get_last_update(self) -> Optional[datetime]:
        with self._state_lock:
            return self._last_update

    def set_last_update(self, update_time: datetime = None):
        with self._state_lock:
            self._last_update = update_time or datetime.now()

    # ==================== 状态变更回调（暂保留） ====================

    def register_callback(self, event: str, callback: Callable):
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)

    def unregister_callback(self, event: str, callback: Callable):
        if event in self._callbacks and callback in self._callbacks[event]:
            self._callbacks[event].remove(callback)

    def _notify_callbacks(self, event: str):
        if event in self._callbacks:
            for callback in self._callbacks[event]:
                try:
                    callback()
                except Exception as e:
                    logging.error(f"状态变更回调执行失败: {e}")

    # ==================== 状态重置 ====================

    def reset_all(self):
        """重置所有状态"""
        with self._state_lock:
            # 委托给子模块重置
            self.pool_state.reset()
            self.init_progress.reset()
            self.quote_cache.reset()
            self.trading_state.reset()
            self.scalping_metrics.reset()
            self.ticker_df_cache.reset()

            # 重置本地保留的状态
            self._subscribed_stocks = set()
            self._subscription_version = None
            self._subscription_initialized = False
            self._is_running = False
            self._last_update = None

        logging.info("StateManager 状态已重置")


# 全局状态管理器实例
_state_manager: Optional[StateManager] = None


def get_state_manager() -> StateManager:
    """获取全局状态管理器实例"""
    global _state_manager
    if _state_manager is None:
        _state_manager = StateManager()
    return _state_manager
