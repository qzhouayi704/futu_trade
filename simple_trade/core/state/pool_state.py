#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票池状态管理器

从 StateManager 提取的股票池领域状态，
负责管理板块列表、股票列表和初始化状态。
"""

import logging
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable


class PoolState:
    """股票池状态管理器 - 管理板块和股票池数据"""

    def __init__(self):
        self._lock = threading.RLock()
        self._stock_pool: Dict[str, Any] = {
            'plates': [],
            'stocks': [],
            'initialized': False,
            'last_update': None
        }
        # 状态变更回调（由 StateManager 注入）
        self._on_pool_changed: Optional[Callable] = None

    def set_pool_changed_callback(self, callback: Callable):
        """设置股票池变更回调"""
        self._on_pool_changed = callback

    def get_stock_pool(self) -> Dict[str, Any]:
        """获取股票池数据"""
        with self._lock:
            return self._stock_pool.copy()

    def set_stock_pool(self, plates: List[Dict], stocks: List[Dict]):
        """设置股票池数据"""
        with self._lock:
            self._stock_pool.update({
                'plates': plates,
                'stocks': stocks,
                'initialized': True,
                'last_update': datetime.now().isoformat()
            })
        if self._on_pool_changed:
            self._on_pool_changed()
        logging.debug(f"股票池更新: {len(plates)}个板块, {len(stocks)}只股票")

    def get_active_stocks(self, limit: Optional[int] = None) -> List[tuple]:
        """获取活跃股票列表

        Returns:
            List[tuple]: (id, code, name, market, plate_name)
        """
        with self._lock:
            if not self._stock_pool['initialized']:
                return []

            stocks = self._stock_pool['stocks']
            if limit:
                stocks = stocks[:limit]

            return [
                (s.get('id', 0), s['code'], s['name'], s['market'], s.get('plate_name', ''))
                for s in stocks
            ]

    def is_stock_pool_initialized(self) -> bool:
        """检查股票池是否已初始化"""
        with self._lock:
            return self._stock_pool['initialized']

    def get_stocks(self) -> List[Dict]:
        """获取股票列表（内部使用）"""
        with self._lock:
            return self._stock_pool['stocks']

    def reset(self):
        """重置股票池状态"""
        with self._lock:
            self._stock_pool = {
                'plates': [],
                'stocks': [],
                'initialized': False,
                'last_update': None
            }
