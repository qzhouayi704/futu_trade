#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
信号效果追踪器 - 追踪信号产生后的价格走势

追踪信号后 1 天、3 天、5 天的最高涨幅和最大回撤，
用于评估策略的实际准确率和盈利能力。

Requirements: 10.1, 10.2
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional


@dataclass
class TrackingRecord:
    """追踪记录数据类"""
    id: int
    signal_id: int
    stock_code: str
    signal_type: str
    signal_price: float
    strategy_id: Optional[str]
    day1_max_rise: Optional[float] = None
    day1_max_drop: Optional[float] = None
    day3_max_rise: Optional[float] = None
    day3_max_drop: Optional[float] = None
    day5_max_rise: Optional[float] = None
    day5_max_drop: Optional[float] = None
    tracking_status: str = 'active'
    created_at: str = ''
    updated_at: str = ''

    @classmethod
    def from_db_row(cls, row: tuple) -> 'TrackingRecord':
        """从数据库行构建追踪记录"""
        return cls(
            id=row[0], signal_id=row[1], stock_code=row[2],
            signal_type=row[3], signal_price=row[4], strategy_id=row[5],
            day1_max_rise=row[6], day1_max_drop=row[7],
            day3_max_rise=row[8], day3_max_drop=row[9],
            day5_max_rise=row[10], day5_max_drop=row[11],
            tracking_status=row[12], created_at=row[13], updated_at=row[14],
        )


@dataclass
class StrategyStats:
    """策略效果统计数据类"""
    strategy_id: Optional[str] = None
    total_signals: int = 0
    accuracy_1d: float = 0.0
    accuracy_3d: float = 0.0
    accuracy_5d: float = 0.0
    avg_return_1d: float = 0.0
    avg_return_3d: float = 0.0
    avg_return_5d: float = 0.0

    def to_dict(self) -> Dict:
        return {
            'strategy_id': self.strategy_id,
            'total_signals': self.total_signals,
            'accuracy_1d': round(self.accuracy_1d, 2),
            'accuracy_3d': round(self.accuracy_3d, 2),
            'accuracy_5d': round(self.accuracy_5d, 2),
            'avg_return_1d': round(self.avg_return_1d, 2),
            'avg_return_3d': round(self.avg_return_3d, 2),
            'avg_return_5d': round(self.avg_return_5d, 2),
        }


# 追踪的天数窗口配置
DAY_WINDOWS = [
    (1, 'day1_max_rise', 'day1_max_drop'),
    (3, 'day3_max_rise', 'day3_max_drop'),
    (5, 'day5_max_rise', 'day5_max_drop'),
]

# 默认目标涨幅（用于计算准确率）
DEFAULT_TARGET_RISE_PCT = 2.0


class SignalTracker:
    """信号效果追踪器"""

    def __init__(self, db_manager):
        self.db_manager = db_manager
        self._has_async = hasattr(db_manager, 'async_execute_query')

    def start_tracking(self, signal_id: int, stock_code: str,
                       signal_type: str, signal_price: float,
                       strategy_id: Optional[str] = None):
        """开始追踪一个新信号"""
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        try:
            self.db_manager.execute_insert(
                '''INSERT INTO signal_performance
                   (signal_id, stock_code, signal_type, signal_price,
                    strategy_id, tracking_status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'active', ?, ?)''',
                (signal_id, stock_code, signal_type, signal_price,
                 strategy_id, now, now)
            )
            logging.debug(f"开始追踪信号 {signal_id}: {stock_code} {signal_type}")
        except Exception as e:
            logging.error(f"开始追踪信号失败 {signal_id}: {e}")

    def update_tracking(self, quotes: List[Dict]):
        """根据最新报价更新所有活跃追踪"""
        if not quotes:
            return

        active_tracks = self._get_active_tracks()
        if not active_tracks:
            return

        # 构建报价查找表：stock_code -> quote
        quote_map = {q.get('code', ''): q for q in quotes}
        now = datetime.now()

        for track in active_tracks:
            quote = quote_map.get(track.stock_code)
            if not quote:
                continue
            self._update_single_track(track, quote, now)

    def get_strategy_stats(self, strategy_id: Optional[str] = None,
                           days: int = 30) -> List[StrategyStats]:
        """获取策略效果统计"""
        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')

        if strategy_id:
            query = '''SELECT strategy_id, day1_max_rise, day3_max_rise, day5_max_rise
                       FROM signal_performance
                       WHERE strategy_id = ? AND created_at >= ?
                         AND tracking_status = 'completed' '''
            rows = self.db_manager.execute_query(query, (strategy_id, cutoff))
        else:
            query = '''SELECT strategy_id, day1_max_rise, day3_max_rise, day5_max_rise
                       FROM signal_performance
                       WHERE created_at >= ? AND tracking_status = 'completed' '''
            rows = self.db_manager.execute_query(query, (cutoff,))

        return self._aggregate_stats(rows)

    # ---- 内部方法 ----

    def _get_active_tracks(self) -> List[TrackingRecord]:
        """获取所有活跃追踪记录"""
        rows = self.db_manager.execute_query(
            '''SELECT id, signal_id, stock_code, signal_type, signal_price,
                      strategy_id, day1_max_rise, day1_max_drop,
                      day3_max_rise, day3_max_drop, day5_max_rise, day5_max_drop,
                      tracking_status, created_at, updated_at
               FROM signal_performance WHERE tracking_status = 'active' '''
        )
        return [TrackingRecord.from_db_row(r) for r in rows]

    def _update_single_track(self, track: TrackingRecord,
                             quote: Dict, now: datetime):
        """更新单条追踪记录"""
        current_price = quote.get('last_price', 0)
        if current_price <= 0 or track.signal_price <= 0:
            return

        # 计算当前涨跌幅
        change_pct = (current_price - track.signal_price) / track.signal_price * 100

        # 解析信号创建时间，计算经过天数
        try:
            created = datetime.strptime(track.created_at.split('.')[0], '%Y-%m-%d %H:%M:%S')
        except (ValueError, AttributeError):
            return
        days_elapsed = (now - created).days

        # 更新各天数窗口的最高涨幅和最大回撤
        updates = {}
        for window_days, rise_field, drop_field in DAY_WINDOWS:
            if days_elapsed <= window_days:
                old_rise = getattr(track, rise_field)
                old_drop = getattr(track, drop_field)
                new_rise = max(change_pct, old_rise or 0)
                new_drop = min(change_pct, old_drop or 0)
                if new_rise != old_rise or new_drop != old_drop:
                    updates[rise_field] = new_rise
                    updates[drop_field] = new_drop

        # 超过 5 天标记为完成
        new_status = 'completed' if days_elapsed > 5 else 'active'
        if new_status != track.tracking_status:
            updates['tracking_status'] = new_status

        if not updates:
            return

        self._apply_updates(track.id, updates, now)

    def _apply_updates(self, track_id: int, updates: Dict, now: datetime):
        """将更新写入数据库"""
        set_clauses = []
        params = []
        for col, val in updates.items():
            set_clauses.append(f"{col} = ?")
            params.append(val)
        set_clauses.append("updated_at = ?")
        params.append(now.strftime('%Y-%m-%d %H:%M:%S'))
        params.append(track_id)

        sql = f"UPDATE signal_performance SET {', '.join(set_clauses)} WHERE id = ?"
        try:
            self.db_manager.execute_update(sql, tuple(params))
        except Exception as e:
            logging.error(f"更新追踪记录 {track_id} 失败: {e}")

    def _aggregate_stats(self, rows: List[tuple]) -> List[StrategyStats]:
        """聚合统计数据"""
        # 按 strategy_id 分组
        groups: Dict[Optional[str], List[tuple]] = {}
        for row in rows:
            sid = row[0]
            groups.setdefault(sid, []).append(row)

        results = []
        for sid, group_rows in groups.items():
            stats = StrategyStats(strategy_id=sid, total_signals=len(group_rows))

            rises_1d = [r[1] for r in group_rows if r[1] is not None]
            rises_3d = [r[2] for r in group_rows if r[2] is not None]
            rises_5d = [r[3] for r in group_rows if r[3] is not None]

            target = DEFAULT_TARGET_RISE_PCT

            if rises_1d:
                stats.accuracy_1d = sum(1 for v in rises_1d if v >= target) / len(rises_1d) * 100
                stats.avg_return_1d = sum(rises_1d) / len(rises_1d)
            if rises_3d:
                stats.accuracy_3d = sum(1 for v in rises_3d if v >= target) / len(rises_3d) * 100
                stats.avg_return_3d = sum(rises_3d) / len(rises_3d)
            if rises_5d:
                stats.accuracy_5d = sum(1 for v in rises_5d if v >= target) / len(rises_5d) * 100
                stats.avg_return_5d = sum(rises_5d) / len(rises_5d)

            results.append(stats)

        return results

    # ---- 异步方法（供 QuotePipeline 直接调用，避免 run_in_executor） ----

    async def async_update_tracking(self, quotes: List[Dict]):
        """异步版本：根据最新报价更新所有活跃追踪（批量写入）"""
        if not quotes or not self._has_async:
            # 无异步能力时回退到同步
            if quotes:
                self.update_tracking(quotes)
            return

        active_rows = await self.db_manager.async_execute_query(
            '''SELECT id, signal_id, stock_code, signal_type, signal_price,
                      strategy_id, day1_max_rise, day1_max_drop,
                      day3_max_rise, day3_max_drop, day5_max_rise, day5_max_drop,
                      tracking_status, created_at, updated_at
               FROM signal_performance WHERE tracking_status = 'active' '''
        )
        if not active_rows:
            return

        active_tracks = [TrackingRecord.from_db_row(r) for r in active_rows]
        quote_map = {q.get('code', ''): q for q in quotes}
        now = datetime.now()
        now_str = now.strftime('%Y-%m-%d %H:%M:%S')

        # 收集所有需要更新的 SQL 语句和参数（批量提交）
        pending_updates: list[tuple[str, tuple]] = []

        for track in active_tracks:
            quote = quote_map.get(track.stock_code)
            if not quote:
                continue
            update = self._compute_track_update(track, quote, now, now_str)
            if update:
                pending_updates.append(update)

        if not pending_updates:
            return

        # 单次提交所有更新到 write_queue（大幅减少队列竞争）
        def _batch_write():
            for sql, params in pending_updates:
                self.db_manager.execute_update(sql, params)

        try:
            future = self.db_manager.write_queue.submit(_batch_write)
            await asyncio.wait_for(
                asyncio.to_thread(future.result), timeout=30.0,
            )
        except Exception as e:
            logging.warning(
                f"批量更新追踪记录失败({len(pending_updates)}条): {e}"
            )

    def _compute_track_update(
        self, track: TrackingRecord, quote: Dict,
        now: datetime, now_str: str,
    ) -> Optional[tuple[str, tuple]]:
        """计算单条追踪记录的更新（纯计算，无 I/O）"""
        current_price = quote.get('last_price', 0)
        if current_price <= 0 or track.signal_price <= 0:
            return None

        change_pct = (current_price - track.signal_price) / track.signal_price * 100

        try:
            created = datetime.strptime(track.created_at.split('.')[0], '%Y-%m-%d %H:%M:%S')
        except (ValueError, AttributeError):
            return None
        days_elapsed = (now - created).days

        updates = {}
        for window_days, rise_field, drop_field in DAY_WINDOWS:
            if days_elapsed <= window_days:
                old_rise = getattr(track, rise_field)
                old_drop = getattr(track, drop_field)
                new_rise = max(change_pct, old_rise or 0)
                new_drop = min(change_pct, old_drop or 0)
                if new_rise != old_rise or new_drop != old_drop:
                    updates[rise_field] = new_rise
                    updates[drop_field] = new_drop

        new_status = 'completed' if days_elapsed > 5 else 'active'
        if new_status != track.tracking_status:
            updates['tracking_status'] = new_status

        if not updates:
            return None

        set_clauses = []
        params = []
        for col, val in updates.items():
            set_clauses.append(f"{col} = ?")
            params.append(val)
        set_clauses.append("updated_at = ?")
        params.append(now_str)
        params.append(track.id)

        sql = f"UPDATE signal_performance SET {', '.join(set_clauses)} WHERE id = ?"
        return (sql, tuple(params))
