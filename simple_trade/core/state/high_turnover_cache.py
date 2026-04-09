#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
活跃个股预计算缓存

后台定时预计算大单追踪、量比等重计算数据，
API 路由只读取缓存，避免请求链路中执行耗时操作。
"""

import threading
from datetime import datetime
from typing import Dict, Optional


class HighTurnoverCache:
    """线程安全的活跃个股预计算数据缓存"""

    def __init__(self):
        self._lock = threading.RLock()
        self._cache: Dict[str, dict] = {}
        self._last_update: Optional[datetime] = None

    def get_all(self) -> Dict[str, dict]:
        """获取全部缓存数据（返回浅拷贝）"""
        with self._lock:
            return dict(self._cache)

    def get(self, stock_code: str) -> Optional[dict]:
        """获取单只股票的缓存"""
        with self._lock:
            return self._cache.get(stock_code)

    def update_batch(self, data: Dict[str, dict]):
        """批量更新缓存（合并而非替换，保留未更新的条目）"""
        with self._lock:
            self._cache.update(data)
            self._last_update = datetime.now()

    def replace_all(self, data: Dict[str, dict]):
        """全量替换缓存"""
        with self._lock:
            self._cache = dict(data)
            self._last_update = datetime.now()

    @property
    def last_update(self) -> Optional[datetime]:
        with self._lock:
            return self._last_update

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._cache)

    def reset(self):
        with self._lock:
            self._cache.clear()
            self._last_update = None
