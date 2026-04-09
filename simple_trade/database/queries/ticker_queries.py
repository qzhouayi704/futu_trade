#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
逐笔成交数据查询服务
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class TickerQueries:
    """逐笔成交数据查询服务"""

    def __init__(self, conn_manager):
        self.conn_manager = conn_manager

    def get_ticker_data(
        self,
        stock_code: str,
        trade_date: Optional[str] = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """获取指定股票的逐笔数据

        Args:
            stock_code: 股票代码
            trade_date: 交易日期（YYYY-MM-DD），默认今天
            limit: 返回记录数限制

        Returns:
            逐笔数据列表
        """
        if trade_date is None:
            trade_date = datetime.now().strftime("%Y-%m-%d")

        with self.conn_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, stock_code, price, volume, turnover, direction,
                       timestamp, trade_date, created_at
                FROM ticker_data
                WHERE stock_code = ? AND trade_date = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (stock_code, trade_date, limit)
            )

            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_ticker_count(
        self,
        stock_code: str,
        trade_date: Optional[str] = None
    ) -> int:
        """获取指定股票的逐笔数据数量

        Args:
            stock_code: 股票代码
            trade_date: 交易日期（YYYY-MM-DD），默认今天

        Returns:
            记录数量
        """
        if trade_date is None:
            trade_date = datetime.now().strftime("%Y-%m-%d")

        with self.conn_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM ticker_data WHERE stock_code = ? AND trade_date = ?",
                (stock_code, trade_date)
            )
            return cursor.fetchone()[0]

    def get_ticker_time_range(
        self,
        stock_code: str,
        start_time: int,
        end_time: int,
        trade_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """获取指定时间范围的逐笔数据

        Args:
            stock_code: 股票代码
            start_time: 开始时间戳（毫秒）
            end_time: 结束时间戳（毫秒）
            trade_date: 交易日期（YYYY-MM-DD），默认今天

        Returns:
            逐笔数据列表
        """
        if trade_date is None:
            trade_date = datetime.now().strftime("%Y-%m-%d")

        with self.conn_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, stock_code, price, volume, turnover, direction,
                       timestamp, trade_date, created_at
                FROM ticker_data
                WHERE stock_code = ? AND trade_date = ?
                  AND timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC
                """,
                (stock_code, trade_date, start_time, end_time)
            )

            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_ticker_statistics(
        self,
        stock_code: str,
        trade_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """获取逐笔数据统计信息

        Args:
            stock_code: 股票代码
            trade_date: 交易日期（YYYY-MM-DD），默认今天

        Returns:
            统计信息字典
        """
        if trade_date is None:
            trade_date = datetime.now().strftime("%Y-%m-%d")

        with self.conn_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    COUNT(*) as total_count,
                    SUM(volume) as total_volume,
                    SUM(turnover) as total_turnover,
                    MIN(timestamp) as first_time,
                    MAX(timestamp) as last_time,
                    SUM(CASE WHEN direction = 'BUY' THEN 1 ELSE 0 END) as buy_count,
                    SUM(CASE WHEN direction = 'SELL' THEN 1 ELSE 0 END) as sell_count,
                    SUM(CASE WHEN direction = 'NEUTRAL' THEN 1 ELSE 0 END) as neutral_count
                FROM ticker_data
                WHERE stock_code = ? AND trade_date = ?
                """,
                (stock_code, trade_date)
            )

            row = cursor.fetchone()
            if row:
                return {
                    "total_count": row[0],
                    "total_volume": row[1] or 0,
                    "total_turnover": row[2] or 0,
                    "first_time": row[3],
                    "last_time": row[4],
                    "buy_count": row[5],
                    "sell_count": row[6],
                    "neutral_count": row[7],
                }
            return {}

    def cleanup_old_data(self, keep_days: int = 7) -> int:
        """清理超过指定天数的旧数据

        Args:
            keep_days: 保留最近 N 天的数据

        Returns:
            删除的记录数
        """
        cutoff_date = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d")

        with self.conn_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM ticker_data WHERE trade_date < ?",
                (cutoff_date,)
            )
            deleted_count = cursor.rowcount
            conn.commit()
            logger.info(f"清理了 {deleted_count} 条逐笔数据（{keep_days} 天前）")
            return deleted_count
