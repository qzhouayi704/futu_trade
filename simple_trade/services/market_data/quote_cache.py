#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全局报价缓存服务

职责：
1. 活跃度筛选阶段缓存全量股票报价快照
2. 运行时接收已订阅股票的实时报价更新
3. 为板块热度计算等消费方提供统一的报价查询接口

数据生命周期：
- 启动时：活跃度筛选获取全部股票报价 → 批量写入缓存
- 运行中：每5秒已订阅股票报价 → 增量更新缓存
- 消费方：板块强势度计算、激进策略 → 从缓存读取
"""

import logging
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional


class QuoteCache:
    """全局报价缓存 - 线程安全"""

    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}  # {stock_code: quote_data}
        self._lock = threading.RLock()
        self._init_time: Optional[str] = None
        self._last_update_time: Optional[str] = None
        self._snapshot_count = 0  # 启动快照数量
        self._realtime_update_count = 0  # 实时更新计数
        self.logger = logging.getLogger(__name__)

    def bulk_update_from_dataframe(self, quote_df) -> int:
        """从 pandas DataFrame 批量写入缓存（活跃度筛选阶段使用）

        Args:
            quote_df: 富途API返回的报价DataFrame

        Returns:
            成功缓存的股票数量
        """
        if quote_df is None or quote_df.empty:
            return 0

        count = 0
        now = datetime.now().isoformat()
        with self._lock:
            for _, row in quote_df.iterrows():
                try:
                    code = row.get('code', '')
                    if not code:
                        continue

                    self._cache[code] = {
                        'code': code,
                        'name': str(row.get('name', '')),
                        'last_price': float(row.get('last_price', 0)),
                        'prev_close': float(row.get('prev_close_price', 0)),
                        'change_percent': self._calc_change_pct(
                            float(row.get('last_price', 0)),
                            float(row.get('prev_close_price', 0))
                        ),
                        'high_price': float(row.get('high_price', 0)),
                        'low_price': float(row.get('low_price', 0)),
                        'open_price': float(row.get('open_price', 0)),
                        'volume': int(row.get('volume', 0)),
                        'turnover': float(row.get('turnover', 0)),
                        'turnover_rate': float(row.get('turnover_rate', 0) or 0),
                        'amplitude': float(row.get('amplitude', 0) or 0),
                        'cached_at': now,
                        'source': 'snapshot',
                    }
                    count += 1
                except Exception as e:
                    self.logger.debug(f"缓存报价失败: {row.get('code', '?')}: {e}")

            if not self._init_time:
                self._init_time = now
            self._snapshot_count += count
            self._last_update_time = now

        if count > 0:
            self.logger.info(f"【报价缓存】批量写入 {count} 只股票，缓存总量: {len(self._cache)}")

        return count

    def update_from_quotes(self, quotes: List[Dict[str, Any]]) -> int:
        """从实时报价列表更新缓存（运行时使用）

        Args:
            quotes: 报价字典列表，格式与 QuotePipeline 输出一致

        Returns:
            更新的股票数量
        """
        if not quotes:
            return 0

        count = 0
        now = datetime.now().isoformat()
        with self._lock:
            for quote in quotes:
                code = quote.get('code', '')
                if not code:
                    continue

                existing = self._cache.get(code, {})
                existing.update({
                    'code': code,
                    'name': quote.get('name', existing.get('name', '')),
                    'last_price': quote.get('last_price', 0),
                    'prev_close': quote.get('prev_close', existing.get('prev_close', 0)),
                    'change_percent': quote.get('change_percent', 0),
                    'high_price': quote.get('high_price', 0),
                    'low_price': quote.get('low_price', 0),
                    'open_price': quote.get('open_price', 0),
                    'volume': quote.get('volume', 0),
                    'turnover': quote.get('turnover', 0),
                    'turnover_rate': quote.get('turnover_rate', existing.get('turnover_rate', 0)),
                    'amplitude': quote.get('amplitude', existing.get('amplitude', 0)),
                    'cached_at': now,
                    'source': 'realtime',
                })
                self._cache[code] = existing
                count += 1

            self._realtime_update_count += count
            self._last_update_time = now

        return count

    def get_quotes_for_codes(self, stock_codes: List[str]) -> Dict[str, Dict[str, Any]]:
        """获取指定股票的缓存报价

        Args:
            stock_codes: 股票代码列表

        Returns:
            {stock_code: quote_data} 字典
        """
        with self._lock:
            return {
                code: dict(self._cache[code])
                for code in stock_codes
                if code in self._cache
            }

    def get_all_quotes(self) -> Dict[str, Dict[str, Any]]:
        """获取所有缓存报价"""
        with self._lock:
            return {code: dict(data) for code, data in self._cache.items()}

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        with self._lock:
            realtime_count = sum(
                1 for v in self._cache.values() if v.get('source') == 'realtime'
            )
            return {
                'total_cached': len(self._cache),
                'snapshot_count': self._snapshot_count,
                'realtime_count': realtime_count,
                'realtime_update_count': self._realtime_update_count,
                'init_time': self._init_time,
                'last_update_time': self._last_update_time,
            }

    @staticmethod
    def _calc_change_pct(last_price: float, prev_close: float) -> float:
        if prev_close > 0:
            return round(((last_price - prev_close) / prev_close) * 100, 2)
        return 0.0
