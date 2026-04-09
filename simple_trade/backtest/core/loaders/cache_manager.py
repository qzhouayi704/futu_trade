"""
缓存管理器

负责管理K线数据缓存和API请求计数
"""

import pandas as pd
from typing import Dict, Optional
import logging


class CacheManager:
    """缓存管理器"""

    def __init__(self):
        """初始化缓存管理器"""
        self.logger = logging.getLogger(__name__)

        # K线数据缓存
        self._kline_cache: Dict[str, pd.DataFrame] = {}

    def get_kline_cache(self, cache_key: str) -> Optional[pd.DataFrame]:
        """
        获取K线缓存

        Args:
            cache_key: 缓存键

        Returns:
            缓存的DataFrame，如果不存在则返回None
        """
        return self._kline_cache.get(cache_key)

    def set_kline_cache(self, cache_key: str, data: pd.DataFrame):
        """
        设置K线缓存

        Args:
            cache_key: 缓存键
            data: K线数据DataFrame
        """
        self._kline_cache[cache_key] = data

    def clear_kline_cache(self):
        """清除K线缓存"""
        self._kline_cache.clear()
        self.logger.info("已清除K线数据缓存")

    def get_cache_size(self) -> int:
        """获取缓存大小"""
        return len(self._kline_cache)

    def get_cache_keys(self) -> list:
        """获取所有缓存键"""
        return list(self._kline_cache.keys())
