#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报价缓存管理器

从 StateManager 提取的报价缓存领域状态，
负责管理行情报价数据的缓存、过期和失效逻辑。
"""

import logging
import threading
from datetime import datetime
from typing import Dict, List, Optional


class QuoteCache:
    """报价缓存管理器 - 管理行情报价数据的缓存"""

    def __init__(self):
        self._lock = threading.RLock()
        self._quotes_cache: Dict = {
            'data': [],
            'timestamp': None,
            'ttl': 5,  # 默认5秒，可通过 set_quotes_ttl 修改
            'is_valid': False
        }

    def set_quotes_ttl(self, ttl: int):
        """设置报价缓存TTL（秒）"""
        with self._lock:
            self._quotes_cache['ttl'] = ttl

    def get_cached_quotes(self) -> Optional[List[Dict]]:
        """获取缓存的报价数据（如果有效）"""
        with self._lock:
            if not self._quotes_cache['is_valid']:
                logging.debug("【调试】报价缓存无效")
                return None
            if not self._quotes_cache['timestamp']:
                logging.debug("【调试】报价缓存无时间戳")
                return None

            elapsed = (datetime.now() - self._quotes_cache['timestamp']).total_seconds()
            if elapsed >= self._quotes_cache['ttl']:
                logging.debug(
                    f"【调试】报价缓存过期: 已过 {elapsed:.1f} 秒, "
                    f"TTL={self._quotes_cache['ttl']}"
                )
                self._quotes_cache['is_valid'] = False
                return None

            logging.info(
                f"【调试】返回报价缓存: {len(self._quotes_cache['data'])}条记录, "
                f"已缓存 {elapsed:.1f} 秒"
            )
            return self._quotes_cache['data'].copy()

    def update_quotes_cache(self, quotes: List[Dict]):
        """更新报价缓存"""
        with self._lock:
            self._quotes_cache.update({
                'data': quotes.copy(),
                'timestamp': datetime.now(),
                'is_valid': True
            })
        logging.debug(
            f"【调试】报价缓存更新: {len(quotes)}条记录, "
            f"时间戳={self._quotes_cache['timestamp']}"
        )

    def invalidate_quotes_cache(self):
        """使报价缓存失效"""
        with self._lock:
            self._quotes_cache['is_valid'] = False

    def is_quotes_cache_valid(self) -> bool:
        """检查报价缓存是否有效"""
        with self._lock:
            if not self._quotes_cache['is_valid']:
                return False
            if not self._quotes_cache['timestamp']:
                return False

            elapsed = (datetime.now() - self._quotes_cache['timestamp']).total_seconds()
            return elapsed < self._quotes_cache['ttl']

    def reset(self):
        """重置报价缓存状态"""
        with self._lock:
            ttl = self._quotes_cache.get('ttl', 5)
            self._quotes_cache = {
                'data': [],
                'timestamp': None,
                'ttl': ttl,
                'is_valid': False
            }
