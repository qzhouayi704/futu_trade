#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单的内存缓存工具

用于缓存API响应，减少重复计算和数据库查询
"""

import time
import logging
from typing import Any, Optional, Callable
from functools import wraps


class SimpleCache:
    """简单的内存缓存类"""

    def __init__(self):
        self._cache = {}
        self._timestamps = {}

    def get(self, key: str, max_age: int = 300) -> Optional[Any]:
        """
        获取缓存值

        Args:
            key: 缓存键
            max_age: 最大缓存时间（秒），默认5分钟

        Returns:
            缓存的值，如果不存在或已过期则返回None
        """
        if key not in self._cache:
            return None

        # 检查是否过期
        timestamp = self._timestamps.get(key, 0)
        if time.time() - timestamp > max_age:
            # 过期，删除缓存
            del self._cache[key]
            del self._timestamps[key]
            return None

        return self._cache[key]

    def set(self, key: str, value: Any):
        """
        设置缓存值

        Args:
            key: 缓存键
            value: 缓存值
        """
        self._cache[key] = value
        self._timestamps[key] = time.time()

    def clear(self, key: Optional[str] = None):
        """
        清除缓存

        Args:
            key: 如果指定，只清除该键的缓存；否则清除所有缓存
        """
        if key:
            self._cache.pop(key, None)
            self._timestamps.pop(key, None)
        else:
            self._cache.clear()
            self._timestamps.clear()

    def get_stats(self) -> dict:
        """获取缓存统计信息"""
        return {
            'total_keys': len(self._cache),
            'keys': list(self._cache.keys())
        }


# 全局缓存实例
_global_cache = SimpleCache()


def get_cache() -> SimpleCache:
    """获取全局缓存实例"""
    return _global_cache


def cached(max_age: int = 300, key_prefix: str = ''):
    """
    缓存装饰器

    Args:
        max_age: 缓存有效期（秒）
        key_prefix: 缓存键前缀
    """
    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # 生成缓存键
            cache_key = f"{key_prefix}:{func.__name__}"
            if args:
                cache_key += f":{str(args)}"
            if kwargs:
                cache_key += f":{str(sorted(kwargs.items()))}"

            # 尝试从缓存获取
            cache = get_cache()
            cached_value = cache.get(cache_key, max_age)
            if cached_value is not None:
                logging.debug(f"缓存命中: {cache_key}")
                return cached_value

            # 执行函数
            result = await func(*args, **kwargs)

            # 存入缓存
            cache.set(cache_key, result)
            logging.debug(f"缓存存储: {cache_key}")

            return result

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # 生成缓存键
            cache_key = f"{key_prefix}:{func.__name__}"
            if args:
                cache_key += f":{str(args)}"
            if kwargs:
                cache_key += f":{str(sorted(kwargs.items()))}"

            # 尝试从缓存获取
            cache = get_cache()
            cached_value = cache.get(cache_key, max_age)
            if cached_value is not None:
                logging.debug(f"缓存命中: {cache_key}")
                return cached_value

            # 执行函数
            result = func(*args, **kwargs)

            # 存入缓存
            cache.set(cache_key, result)
            logging.debug(f"缓存存储: {cache_key}")

            return result

        # 根据函数类型返回对应的包装器
        import inspect
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator
