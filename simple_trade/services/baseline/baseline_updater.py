#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
历史基准盘后更新服务

收盘后批量计算每只股票的统计基准（均值、标准差、百分位），
写入 market_baselines 表，供 BaselineService 实时查询。
"""

import logging
import statistics
from datetime import datetime, timedelta
from typing import List, Optional

logger = logging.getLogger("baseline")


class BaselineUpdater:
    """盘后历史基准更新器"""

    def __init__(self, db_manager):
        self._db = db_manager

    def update_all_for_stock(self, stock_code: str,
                             window_days: int = 20) -> int:
        """更新一只股票的所有指标基准

        Returns:
            成功更新的指标数
        """
        updated = 0
        for method in [
            self.update_avg_turnover_per_tick,
            self.update_net_inflow_ratio,
            self.update_big_order_ratio,
            self.update_volume_ratio,
        ]:
            try:
                if method(stock_code, window_days):
                    updated += 1
            except Exception as e:
                logger.warning(f"更新基准失败 {stock_code}/{method.__name__}: {e}")
        return updated

    def update_avg_turnover_per_tick(self, stock_code: str,
                                     window_days: int = 20) -> bool:
        """从 scalping_delta_history 计算每笔平均成交额分布（已停用：Scalping 已移除，表不再有新数据）"""
        cutoff = (datetime.now() - timedelta(days=window_days)).strftime('%Y-%m-%d')
        rows = self._db.execute_query("""
            SELECT delta, volume FROM scalping_delta_history
            WHERE stock_code = ? AND trade_date >= ?
        """, (stock_code, cutoff))
        if not rows or len(rows) < 3:
            return False
        # 用 |delta| 作为该周期的净成交量代理，volume 为总量
        # 每笔平均 ≈ volume（因为每条记录是一个周期的汇总）
        # 但更合理的是用 ticker_data 计算 —— 如果有的话
        values = [abs(r[0]) for r in rows if r[0]]
        if not values:
            return False
        return self._save_stats(stock_code, "avg_turnover_per_tick",
                                window_days, values)

    def update_net_inflow_ratio(self, stock_code: str,
                                window_days: int = 20) -> bool:
        """从 capital_flow_daily 计算净流入占比分布"""
        cutoff = (datetime.now() - timedelta(days=window_days)).strftime('%Y-%m-%d')
        rows = self._db.execute_query("""
            SELECT net_inflow_ratio FROM capital_flow_daily
            WHERE stock_code = ? AND date >= ?
            ORDER BY date DESC
        """, (stock_code, cutoff))
        if not rows or len(rows) < 3:
            return False
        values = [r[0] for r in rows if r[0] is not None]
        if not values:
            return False
        return self._save_stats(stock_code, "net_inflow_ratio",
                                window_days, values)

    def update_big_order_ratio(self, stock_code: str,
                               window_days: int = 20) -> bool:
        """从 scalping_delta_history 计算大单占比分布（已停用：Scalping 已移除，表不再有新数据）"""
        cutoff = (datetime.now() - timedelta(days=window_days)).strftime('%Y-%m-%d')
        rows = self._db.execute_query("""
            SELECT delta, volume FROM scalping_delta_history
            WHERE stock_code = ? AND trade_date >= ?
        """, (stock_code, cutoff))
        if not rows or len(rows) < 3:
            return False
        # 大单占比 = |delta| / volume（简化近似）
        values = []
        for r in rows:
            if r[1] and r[1] > 0:
                values.append(abs(r[0]) / r[1])
        if not values:
            return False
        return self._save_stats(stock_code, "big_order_ratio",
                                window_days, values)

    def update_volume_ratio(self, stock_code: str,
                            window_days: int = 20) -> bool:
        """从 kline_data 计算量比分布"""
        today = datetime.now().strftime('%Y-%m-%d')
        rows = self._db.execute_query("""
            SELECT volume FROM kline_data
            WHERE stock_code = ? AND date(time_key) < ?
            ORDER BY time_key DESC LIMIT ?
        """, (stock_code, today, window_days))
        if not rows or len(rows) < 5:
            return False
        volumes = [r[0] for r in rows if r[0] and r[0] > 0]
        if len(volumes) < 5:
            return False
        avg = sum(volumes) / len(volumes)
        if avg <= 0:
            return False
        # 量比 = 每日 volume / 均值
        ratios = [v / avg for v in volumes]
        return self._save_stats(stock_code, "volume_ratio",
                                window_days, ratios)

    def _save_stats(self, stock_code: str, metric_key: str,
                    window_days: int, values: List[float]) -> bool:
        """计算统计量并写入 DB"""
        if len(values) < 2:
            return False
        sorted_v = sorted(values)
        n = len(sorted_v)

        def percentile(pct: float) -> float:
            idx = pct / 100 * (n - 1)
            lo = int(idx)
            hi = min(lo + 1, n - 1)
            frac = idx - lo
            return sorted_v[lo] * (1 - frac) + sorted_v[hi] * frac

        mean_val = statistics.mean(values)
        stddev_val = statistics.stdev(values) if n >= 2 else 0.0

        try:
            self._db.execute_update("""
                INSERT OR REPLACE INTO market_baselines
                (stock_code, metric_key, window_days, mean, stddev,
                 p25, p50, p75, p90, sample_count, computed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                stock_code, metric_key, window_days,
                mean_val, stddev_val,
                percentile(25), percentile(50),
                percentile(75), percentile(90),
                n,
                datetime.now().isoformat(),
            ))
            return True
        except Exception as e:
            logger.warning(f"保存基准失败 {stock_code}/{metric_key}: {e}")
            return False
