#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
盘后优选 — 次日表现追踪器

每天K线更新后自动运行：
1. 读取前一个交易日的优选推荐
2. 对每只推荐股查询次日K线表现
3. 计算盈亏、最大收益、最大回撤
4. 持久化到 overnight_performance 表
5. 定期输出统计报告（各分数段胜率、各模式胜率）
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

logger = logging.getLogger("overnight_tracker")


class OvernightTracker:
    """盘后优选次日表现追踪"""

    def __init__(self, db_manager):
        self.db = db_manager
        self._ensure_table()

    def _ensure_table(self):
        """确保追踪表存在"""
        self.db.execute_update("""
            CREATE TABLE IF NOT EXISTS overnight_performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                screen_date TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                stock_name TEXT DEFAULT '',
                category TEXT DEFAULT '',
                total_score REAL DEFAULT 0,
                verdict TEXT DEFAULT '',
                screen_price REAL DEFAULT 0,
                next_open REAL DEFAULT 0,
                next_close REAL DEFAULT 0,
                next_high REAL DEFAULT 0,
                next_low REAL DEFAULT 0,
                next_change_pct REAL DEFAULT 0,
                open_to_close_pct REAL DEFAULT 0,
                max_gain_pct REAL DEFAULT 0,
                max_loss_pct REAL DEFAULT 0,
                next_date TEXT DEFAULT '',
                tracked_at TEXT DEFAULT '',
                UNIQUE(screen_date, stock_code)
            )
        """)

    def track_previous_screen(self, screen_date: Optional[str] = None) -> Dict[str, Any]:
        """追踪指定日期的优选结果在次日的表现

        Args:
            screen_date: 优选日期，默认自动查找最近一个有推荐的日期

        Returns:
            追踪结果摘要
        """
        # 1. 获取优选结果
        if screen_date:
            rows = self.db.execute_query(
                "SELECT screen_date, candidates_json FROM overnight_screen_results "
                "WHERE screen_date = ?", (screen_date,)
            )
        else:
            rows = self.db.execute_query(
                "SELECT screen_date, candidates_json FROM overnight_screen_results "
                "ORDER BY screen_date DESC LIMIT 1"
            )

        if not rows:
            return {"success": False, "message": "无优选结果可追踪"}

        s_date = rows[0][0]
        candidates = json.loads(rows[0][1])

        # 2. 检查是否已追踪过
        existing = self.db.execute_query(
            "SELECT COUNT(*) FROM overnight_performance WHERE screen_date = ?",
            (s_date,)
        )
        if existing and existing[0][0] > 0:
            return {"success": False, "message": f"{s_date} 已追踪过",
                    "screen_date": s_date, "tracked_count": existing[0][0]}

        # 3. 查找次日K线日期
        next_date = self._find_next_trading_date(s_date)
        if not next_date:
            return {"success": False, "message": f"{s_date} 无次日K线数据（可能还未收盘）",
                    "screen_date": s_date}

        # 4. 逐股追踪
        tracked = 0
        win = 0
        total_pnl = 0.0

        for cand in candidates:
            code = cand.get('stock_code', '')
            if not code:
                continue

            screen_price = cand.get('key_metrics', {}).get('last_price', 0)
            if not screen_price:
                screen_price = cand.get('key_metrics', {}).get('prev_close_price', 0)

            # 读取次日K线
            kline = self.db.execute_query(
                "SELECT open_price, close_price, high_price, low_price "
                "FROM kline_data WHERE stock_code = ? AND time_key = ?",
                (code, next_date)
            )
            if not kline or not kline[0][0]:
                continue

            next_open, next_close, next_high, next_low = kline[0]

            # 计算表现指标
            if screen_price > 0:
                next_change = (next_close - screen_price) / screen_price * 100
                open_to_close = (next_close - next_open) / next_open * 100 if next_open > 0 else 0
                max_gain = (next_high - screen_price) / screen_price * 100
                max_loss = (next_low - screen_price) / screen_price * 100
            else:
                next_change = open_to_close = max_gain = max_loss = 0

            # 写入
            self.db.execute_update(
                "INSERT OR REPLACE INTO overnight_performance "
                "(screen_date, stock_code, stock_name, category, total_score, verdict, "
                "screen_price, next_open, next_close, next_high, next_low, "
                "next_change_pct, open_to_close_pct, max_gain_pct, max_loss_pct, "
                "next_date, tracked_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (s_date, code, cand.get('stock_name', ''),
                 cand.get('category', ''), cand.get('total_score', 0),
                 cand.get('verdict', ''), round(screen_price, 4),
                 round(next_open, 4), round(next_close, 4),
                 round(next_high, 4), round(next_low, 4),
                 round(next_change, 2), round(open_to_close, 2),
                 round(max_gain, 2), round(max_loss, 2),
                 next_date, datetime.now().isoformat())
            )
            tracked += 1
            total_pnl += next_change
            if next_change > 0:
                win += 1

        win_rate = (win / tracked * 100) if tracked > 0 else 0
        avg_pnl = (total_pnl / tracked) if tracked > 0 else 0

        logger.info(
            f"[优选追踪] {s_date} → {next_date}: "
            f"追踪{tracked}只, 胜率{win_rate:.1f}%, 均盈{avg_pnl:+.2f}%"
        )

        return {
            "success": True,
            "screen_date": s_date,
            "next_date": next_date,
            "tracked_count": tracked,
            "win_count": win,
            "win_rate": round(win_rate, 1),
            "avg_pnl": round(avg_pnl, 2),
            "total_pnl": round(total_pnl, 2),
        }

    def get_performance_stats(self, days: int = 30) -> Dict[str, Any]:
        """获取评分表现统计

        Returns:
            各分数段、各模式的胜率和盈亏统计
        """
        rows = self.db.execute_query(
            "SELECT category, total_score, next_change_pct, max_gain_pct, max_loss_pct, "
            "screen_date, stock_code, stock_name, verdict "
            "FROM overnight_performance "
            "ORDER BY screen_date DESC LIMIT ?",
            (days * 30,)  # 每天最多30只推荐
        )
        if not rows:
            return {"total_records": 0, "message": "暂无追踪数据"}

        # 按模式分组
        by_category: Dict[str, list] = {}
        # 按分数段分组
        by_score_band: Dict[str, list] = {}
        all_records = []

        for r in rows:
            cat, score, pnl, max_g, max_l, s_date, code, name, verdict = r
            record = {
                "category": cat, "score": score, "pnl": pnl,
                "max_gain": max_g, "max_loss": max_l,
                "date": s_date, "code": code, "name": name, "verdict": verdict,
            }
            all_records.append(record)

            # 按模式
            by_category.setdefault(cat, []).append(record)

            # 按分数段（每10分一段）
            band = f"{int(score // 10) * 10}-{int(score // 10) * 10 + 9}"
            by_score_band.setdefault(band, []).append(record)

        def _calc_stats(records: list) -> dict:
            if not records:
                return {}
            wins = sum(1 for r in records if r['pnl'] > 0)
            total = len(records)
            pnls = [r['pnl'] for r in records]
            gains = [r['max_gain'] for r in records]
            losses = [r['max_loss'] for r in records]
            return {
                "count": total,
                "win_rate": round(wins / total * 100, 1),
                "avg_pnl": round(sum(pnls) / total, 2),
                "max_single_gain": round(max(gains), 2) if gains else 0,
                "max_single_loss": round(min(losses), 2) if losses else 0,
                "total_pnl": round(sum(pnls), 2),
            }

        return {
            "total_records": len(all_records),
            "overall": _calc_stats(all_records),
            "by_category": {k: _calc_stats(v) for k, v in sorted(by_category.items())},
            "by_score_band": {k: _calc_stats(v) for k, v in sorted(by_score_band.items())},
        }

    def get_recent_performance(self, limit: int = 5) -> List[Dict[str, Any]]:
        """获取最近N个交易日的追踪汇总"""
        rows = self.db.execute_query(
            "SELECT screen_date, "
            "COUNT(*) as cnt, "
            "SUM(CASE WHEN next_change_pct > 0 THEN 1 ELSE 0 END) as wins, "
            "ROUND(AVG(next_change_pct), 2) as avg_pnl, "
            "ROUND(MAX(next_change_pct), 2) as best, "
            "ROUND(MIN(next_change_pct), 2) as worst "
            "FROM overnight_performance "
            "GROUP BY screen_date "
            "ORDER BY screen_date DESC LIMIT ?",
            (limit,)
        )
        if not rows:
            return []

        return [
            {
                "date": r[0], "count": r[1], "wins": r[2],
                "win_rate": round(r[2] / r[1] * 100, 1) if r[1] > 0 else 0,
                "avg_pnl": r[3], "best": r[4], "worst": r[5],
            }
            for r in rows
        ]

    def _find_next_trading_date(self, date_str: str) -> Optional[str]:
        """查找指定日期之后最近的有K线数据的交易日"""
        rows = self.db.execute_query(
            "SELECT DISTINCT time_key FROM kline_data "
            "WHERE time_key > ? ORDER BY time_key ASC LIMIT 1",
            (date_str,)
        )
        return rows[0][0] if rows else None
