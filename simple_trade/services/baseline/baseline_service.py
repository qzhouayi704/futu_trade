#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
历史基准查询服务

从 market_baselines 表读取统计基准，为大单判定、资金流向等模块
提供动态阈值。冷启动期（样本不足）自动降级到 fallback 固定值。
"""

import logging
import time
from typing import Dict, Optional, Tuple

logger = logging.getLogger("baseline")


class BaselineService:
    """历史基准查询服务（只读 + 内存缓存）"""

    MIN_SAMPLES = 10        # 冷启动最小样本数
    CACHE_TTL = 300         # 内存缓存 5 分钟

    def __init__(self, db_manager):
        self._db = db_manager
        # 缓存: {(stock_code, metric_key, window_days): (value_dict, expire_ts)}
        self._cache: Dict[Tuple, Tuple[dict, float]] = {}

    def get_threshold(
        self,
        stock_code: str,
        metric_key: str,
        percentile: str = "p75",
        window_days: int = 20,
        fallback: float = None,
    ) -> float:
        """获取动态阈值

        Args:
            stock_code: 股票代码
            metric_key: 指标名 (avg_turnover_per_tick / net_inflow_ratio / ...)
            percentile: 目标百分位 (p25 / p50 / p75 / p90 / mean)
            window_days: 统计窗口天数
            fallback: 冷启动降级值（原有固定值）

        Returns:
            动态阈值，冷启动时返回 fallback
        """
        cache_key = (stock_code, metric_key, window_days)
        now = time.time()

        # 检查内存缓存
        cached = self._cache.get(cache_key)
        if cached and cached[1] > now:
            row = cached[0]
            if row and row.get("sample_count", 0) >= self.MIN_SAMPLES:
                val = row.get(percentile)
                if val is not None:
                    return val
            return fallback if fallback is not None else 0.0

        # 查询 DB
        row = self._query_baseline(stock_code, metric_key, window_days)
        self._cache[cache_key] = (row, now + self.CACHE_TTL)

        if row and row.get("sample_count", 0) >= self.MIN_SAMPLES:
            val = row.get(percentile)
            if val is not None:
                return val

        return fallback if fallback is not None else 0.0

    def get_tiers(
        self,
        stock_code: str,
        metric_key: str = "avg_turnover_per_tick",
        window_days: int = 20,
        fallback_large: float = 100_000.0,
    ) -> Tuple[float, float, float]:
        """获取大单三级阈值 (super_large, large, medium)

        基于 p75 作为 large 基准，上下按比例推算。
        """
        large = self.get_threshold(
            stock_code, metric_key, "p75",
            window_days=window_days,
            fallback=fallback_large,
        )
        return large * 10, large, large * 0.2

    def _query_baseline(self, stock_code: str, metric_key: str,
                        window_days: int) -> Optional[dict]:
        """从 DB 查询最新基准"""
        if not self._db:
            return None
        try:
            rows = self._db.execute_query("""
                SELECT mean, stddev, p25, p50, p75, p90, sample_count
                FROM market_baselines
                WHERE stock_code = ? AND metric_key = ? AND window_days = ?
                LIMIT 1
            """, (stock_code, metric_key, window_days))
            if rows and len(rows) > 0:
                r = rows[0]
                return {
                    "mean": r[0],
                    "stddev": r[1],
                    "p25": r[2],
                    "p50": r[3],
                    "p75": r[4],
                    "p90": r[5],
                    "sample_count": r[6] or 0,
                }
        except Exception as e:
            logger.debug(f"查询 baseline 失败 {stock_code}/{metric_key}: {e}")
        return None
