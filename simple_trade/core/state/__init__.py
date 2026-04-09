#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
领域状态管理器

将原 StateManager 按业务领域拆分为独立的状态管理器：
- QuoteCache: 报价缓存管理
- TradingState: 交易状态管理
- PoolState: 股票池状态管理
- InitProgress: 初始化进度管理
- StateManager: 统一状态管理器（向后兼容）
"""

from simple_trade.core.state.quote_cache import QuoteCache
from simple_trade.core.state.trading_state import TradingState
from simple_trade.core.state.pool_state import PoolState
from simple_trade.core.state.init_progress import InitProgress
from simple_trade.core.state.state_manager import StateManager, get_state_manager

__all__ = [
    'QuoteCache',
    'TradingState',
    'PoolState',
    'InitProgress',
    'StateManager',
    'get_state_manager',
]
