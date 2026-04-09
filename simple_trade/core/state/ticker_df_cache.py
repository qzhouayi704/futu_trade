#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ticker DataFrame 共享缓存

按 stock_code 缓存 ScalpingDataPoller 拉取的原始 ticker DataFrame，
供 TickerService 复用，避免重复调用 futu API。

设计原则：
- 与 ScalpingMetricsState 一致的缓存模式
- 线程安全：RLock 保护读写
- TTL 5 秒，惰性过期（get 时检查）
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)

_DEFAULT_TTL = 5.0


@dataclass
class _CachedDataFrame:
    """缓存条目（内部使用）"""
    df: "pd.DataFrame"
    updated_at: float  # time.time()


class TickerDataFrameCache:
    """Ticker DataFrame 共享缓存

    线程安全：RLock 保护读写
    TTL：5 秒，按 stock_code 独立过期
    """

    def __init__(self, ttl: float = _DEFAULT_TTL):
        self._lock = threading.RLock()
        self._ttl = ttl
        self._store: Dict[str, _CachedDataFrame] = {}

    def set(self, stock_code: str, df: "pd.DataFrame") -> None:
        """写入 DataFrame 缓存"""
        with self._lock:
            self._store[stock_code] = _CachedDataFrame(
                df=df, updated_at=time.time()
            )

    def get(self, stock_code: str) -> Optional["pd.DataFrame"]:
        """读取 DataFrame，过期返回 None"""
        with self._lock:
            entry = self._store.get(stock_code)
            if entry is None:
                return None
            if time.time() - entry.updated_at > self._ttl:
                del self._store[stock_code]
                return None
            return entry.df

    def clear(self) -> None:
        """清空所有缓存"""
        with self._lock:
            self._store.clear()

    def reset(self) -> None:
        """重置（与 clear 相同，兼容 StateManager.reset_all）"""
        self.clear()
        logger.info("TickerDataFrameCache 已重置")
