#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一数据缓存层（Phase 4）

职责：
1. L1缓存（内存）：热数据，TTL 30-60秒
2. L2缓存（数据库）：冷数据，持久化
3. 自动降级：内存超限时降级到只写数据库
4. 自动恢复：内存恢复后自动升级
5. 内存监控：实时监控内存使用
"""

import asyncio
import logging
import pickle
import psutil
import sqlite3
import time
import zlib
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """缓存条目"""
    data: Any
    created_at: float
    ttl: float  # 生存时间（秒）
    access_count: int = field(default=0, repr=False)  # P3-2: LFU 计数

    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.ttl


class UnifiedDataCache:
    """统一数据缓存层

    两级缓存架构：
    - L1（内存）：OrderedDict，LRU淘汰
    - L2（数据库）：持久化存储

    自动降级/恢复：
    - 内存使用 > 80%：降级到只写数据库
    - 内存使用 < 60%：恢复L1缓存
    """

    # 内存阈值
    MEMORY_THRESHOLD_DEGRADE = 0.80  # 80%降级
    MEMORY_THRESHOLD_RECOVER = 0.60  # 60%恢复

    # 缓存大小限制
    MAX_L1_SIZE = 10000  # L1最多缓存10000条

    # P3-2: 分级内存阈值
    MEMORY_THRESHOLD_EXPIRE = 0.70   # 70% 清理过期
    MEMORY_THRESHOLD_LFU = 0.80      # 80% LFU清理最低频20%
    MEMORY_THRESHOLD_LRU = 0.90      # 90% LRU清理最久50%
    MEMORY_THRESHOLD_CLEAR = 0.95    # 95% 清空L1保留L2

    def __init__(self, db_manager=None):
        self._db_manager = db_manager

        # L1缓存（内存）
        self._l1_cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._l1_enabled = True

        # 统计
        self._stats = {
            'l1_hits': 0,
            'l1_misses': 0,
            'l2_hits': 0,
            'l2_misses': 0,
            'degraded_count': 0,
            'recovered_count': 0,
        }

        # 内存监控
        self._memory_monitor_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

        # P3-1: 初始化 L2 表
        self._init_l2_table()

    async def start_monitoring(self):
        """启动内存监控"""
        if self._memory_monitor_task is None or self._memory_monitor_task.done():
            self._memory_monitor_task = asyncio.create_task(self._memory_monitor_loop())
            logger.info("统一缓存内存监控已启动")

    async def stop_monitoring(self):
        """停止内存监控"""
        if self._memory_monitor_task and not self._memory_monitor_task.done():
            self._memory_monitor_task.cancel()
            try:
                await self._memory_monitor_task
            except asyncio.CancelledError:
                pass
            logger.info("统一缓存内存监控已停止")

    async def get(self, key: str) -> Optional[Any]:
        """获取缓存数据（L1 -> L2）"""
        async with self._lock:
            # 尝试L1
            if self._l1_enabled and key in self._l1_cache:
                entry = self._l1_cache[key]
                if not entry.is_expired():
                    # 移到末尾（LRU）+ 增加访问计数
                    self._l1_cache.move_to_end(key)
                    entry.access_count += 1
                    self._stats['l1_hits'] += 1
                    return entry.data
                else:
                    # 过期，删除
                    del self._l1_cache[key]

            self._stats['l1_misses'] += 1

            # 尝试L2（数据库）
            if self._db_manager:
                data = await self._get_from_db(key)
                if data is not None:
                    self._stats['l2_hits'] += 1
                    # 回填L1
                    if self._l1_enabled:
                        await self._put_l1(key, data, ttl=60)
                    return data

            self._stats['l2_misses'] += 1
            return None

    async def put(self, key: str, data: Any, ttl: float = 60):
        """写入缓存（L1 + L2）"""
        async with self._lock:
            # 写入L1
            if self._l1_enabled:
                await self._put_l1(key, data, ttl)

            # 写入L2（数据库）
            if self._db_manager:
                await self._put_db(key, data)

    async def delete(self, key: str):
        """删除缓存"""
        async with self._lock:
            # 删除L1
            self._l1_cache.pop(key, None)

            # 删除L2
            if self._db_manager:
                await self._delete_from_db(key)

    async def clear(self):
        """清空缓存"""
        async with self._lock:
            self._l1_cache.clear()
            logger.info("L1缓存已清空")

    def get_stats(self) -> Dict[str, int]:
        """获取统计信息"""
        return {
            **self._stats,
            'l1_size': len(self._l1_cache),
            'l1_enabled': self._l1_enabled,
            'memory_percent': psutil.virtual_memory().percent,
        }

    def is_degraded_mode(self) -> bool:
        """是否处于降级模式"""
        return not self._l1_enabled

    async def _put_l1(self, key: str, data: Any, ttl: float):
        """写入L1缓存"""
        # LRU淘汰
        if len(self._l1_cache) >= self.MAX_L1_SIZE:
            self._l1_cache.popitem(last=False)

        self._l1_cache[key] = CacheEntry(
            data=data,
            created_at=time.time(),
            ttl=ttl
        )

    def _init_l2_table(self):
        """P3-1: 初始化 L2 SQLite 表"""
        if not self._db_manager:
            return
        try:
            with self._db_manager.get_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS cache_entries (
                        key TEXT PRIMARY KEY,
                        value BLOB,
                        expire_at INTEGER,
                        updated_at INTEGER
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.warning(f"L2缓存表创建失败: {e}")

    async def _get_from_db(self, key: str) -> Optional[Any]:
        """P3-1: 从 SQLite 读取（pickle + zlib）"""
        if not self._db_manager:
            return None
        try:
            with self._db_manager.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT value, expire_at FROM cache_entries WHERE key=?", (key,)
                )
                row = cursor.fetchone()
                if row:
                    blob, expire_at = row
                    if expire_at and expire_at < int(time.time()):
                        conn.execute("DELETE FROM cache_entries WHERE key=?", (key,))
                        conn.commit()
                        return None
                    return pickle.loads(zlib.decompress(blob))
        except Exception as e:
            logger.debug(f"L2读取失败 {key}: {e}")
        return None

    async def _put_db(self, key: str, data: Any, ttl: float = 3600):
        """P3-1: 写入 SQLite（pickle + zlib）"""
        if not self._db_manager:
            return
        try:
            blob = zlib.compress(pickle.dumps(data))
            now = int(time.time())
            with self._db_manager.get_connection() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO cache_entries (key, value, expire_at, updated_at) "
                    "VALUES (?, ?, ?, ?)",
                    (key, blob, now + int(ttl), now)
                )
                conn.commit()
        except Exception as e:
            logger.debug(f"L2写入失败 {key}: {e}")

    async def _delete_from_db(self, key: str):
        """P3-1: 从 SQLite 删除"""
        if not self._db_manager:
            return
        try:
            with self._db_manager.get_connection() as conn:
                conn.execute("DELETE FROM cache_entries WHERE key=?", (key,))
                conn.commit()
        except Exception as e:
            logger.debug(f"L2删除失败 {key}: {e}")

    async def _evict_expired(self):
        """清理所有过期条目（不关闭L1）"""
        expired_keys = [
            k for k, v in self._l1_cache.items() if v.is_expired()
        ]
        for k in expired_keys:
            del self._l1_cache[k]
        if expired_keys:
            logger.info(f"清理了 {len(expired_keys)} 个过期缓存条目")
        return len(expired_keys)

    def _evict_lfu(self, pct: float = 0.2):
        """P3-2: LFU 清理最低频 pct% 条目"""
        if not self._l1_cache:
            return 0
        n = max(1, int(len(self._l1_cache) * pct))
        items = sorted(self._l1_cache.items(), key=lambda kv: kv[1].access_count)
        removed = 0
        for k, _ in items[:n]:
            del self._l1_cache[k]
            removed += 1
        return removed

    def _evict_lru(self, pct: float = 0.5):
        """P3-2: LRU 清理最久未访问 pct% 条目"""
        if not self._l1_cache:
            return 0
        n = max(1, int(len(self._l1_cache) * pct))
        removed = 0
        for _ in range(n):
            if self._l1_cache:
                self._l1_cache.popitem(last=False)
                removed += 1
        return removed

    async def _memory_monitor_loop(self):
        """P3-2: 分级内存降级监控循环"""
        while True:
            try:
                memory_percent = psutil.virtual_memory().percent / 100.0

                if memory_percent >= self.MEMORY_THRESHOLD_CLEAR:
                    # 95%: 清空L1，保留L2
                    logger.warning(f"内存{memory_percent*100:.0f}% ≥ 95%，清空L1保留L2")
                    self._l1_enabled = False
                    self._l1_cache.clear()
                    self._stats['degraded_count'] += 1
                elif memory_percent >= self.MEMORY_THRESHOLD_LRU:
                    # 90%: LRU 清理最久 50%
                    n = self._evict_lru(0.5)
                    logger.warning(f"内存{memory_percent*100:.0f}% ≥ 90%，LRU清理{n}条")
                elif memory_percent >= self.MEMORY_THRESHOLD_LFU:
                    # 80%: LFU 清理最低频 20%
                    n = self._evict_lfu(0.2)
                    logger.warning(f"内存{memory_percent*100:.0f}% ≥ 80%，LFU清理{n}条")
                elif memory_percent >= self.MEMORY_THRESHOLD_EXPIRE:
                    # 70%: 清理过期
                    n = await self._evict_expired()
                    if n:
                        logger.info(f"内存{memory_percent*100:.0f}% ≥ 70%，清理{n}条过期")
                else:
                    # 内存正常，恢复L1
                    if not self._l1_enabled:
                        self._l1_enabled = True
                        self._stats['recovered_count'] += 1
                        logger.info("内存恢复正常，重新启用L1缓存")

                await asyncio.sleep(10.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"内存监控异常: {e}")
                await asyncio.sleep(10.0)
