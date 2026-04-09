#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票活跃度查询服务
负责股票活跃度检查相关的查询操作
"""

import logging
from typing import List, Dict, Any
from ..core.connection_manager import ConnectionManager
from ..core.base_queries import BaseQueries


class StockActivityQueries(BaseQueries):
    """股票活跃度查询服务"""

    def __init__(self, conn_manager: ConnectionManager):
        """初始化股票活跃度查询服务

        Args:
            conn_manager: 连接管理器实例
        """
        super().__init__(conn_manager)

    def get_daily_active_stocks(self, check_date: str, market: str = None) -> List[str]:
        """获取当天活跃股票代码列表

        Args:
            check_date: 检查日期 (YYYY-MM-DD)
            market: 市场代码 (HK/US)，None表示所有市场

        Returns:
            活跃股票代码列表
        """
        try:
            if market:
                result = self.execute_query('''
                    SELECT stock_code FROM daily_active_stocks
                    WHERE check_date = ? AND market = ? AND is_active = 1
                ''', (check_date, market))
            else:
                result = self.execute_query('''
                    SELECT stock_code FROM daily_active_stocks
                    WHERE check_date = ? AND is_active = 1
                ''', (check_date,))
            return [row[0] for row in result] if result else []
        except Exception as e:
            logging.error(f"获取每日活跃股票失败: {e}")
            return []

    def get_daily_checked_stocks(self, check_date: str) -> Dict[str, Dict[str, Any]]:
        """获取当天已检查的股票及其活跃状态

        Args:
            check_date: 检查日期 (YYYY-MM-DD)

        Returns:
            股票代码 -> {'is_active': bool, 'activity_score': float} 的映射
            activity_score=-1 表示"检查失败"状态
        """
        try:
            result = self.execute_query('''
                SELECT stock_code, is_active, activity_score FROM daily_active_stocks
                WHERE check_date = ?
            ''', (check_date,))
            return {
                row[0]: {'is_active': bool(row[1]), 'activity_score': row[2]}
                for row in result
            } if result else {}
        except Exception as e:
            logging.error(f"获取每日已检查股票失败: {e}")
            return {}

    def get_daily_checked_stocks_with_expiry(self, check_date: str, expire_minutes: int = 10) -> Dict[str, Dict[str, Any]]:
        """获取当天已检查且未过期的股票及其活跃状态

        在原有 check_date 过滤基础上，增加 created_at 时间过滤，
        仅返回 created_at 在 expire_minutes 分钟以内的缓存记录。

        Args:
            check_date: 检查日期 (YYYY-MM-DD)
            expire_minutes: 缓存过期时间（分钟），默认 10 分钟

        Returns:
            股票代码 -> {'is_active': bool, 'activity_score': float, 'created_at': str} 的映射
            仅包含未过期的缓存记录；activity_score=-1 表示"检查失败"状态
        """
        try:
            # 确保 expire_minutes 为正整数，防止 SQL 注入
            expire_minutes = max(1, int(expire_minutes))
            time_offset = f'-{expire_minutes} minutes'

            result = self.execute_query('''
                SELECT stock_code, is_active, activity_score, created_at
                FROM daily_active_stocks
                WHERE check_date = ?
                  AND created_at >= datetime('now', 'localtime', ?)
            ''', (check_date, time_offset))
            return {
                row[0]: {
                    'is_active': bool(row[1]),
                    'activity_score': row[2],
                    'created_at': row[3]
                }
                for row in result
            } if result else {}
        except Exception as e:
            logging.error(f"获取未过期的每日已检查股票失败: {e}")
            return {}



    def save_daily_activity_result(self, check_date: str, stock_code: str, market: str,
                                    is_active: bool, activity_score: float = 0,
                                    turnover_rate: float = 0, turnover_amount: float = 0) -> bool:
        """保存当天活跃度检查结果

        Args:
            check_date: 检查日期 (YYYY-MM-DD)
            stock_code: 股票代码
            market: 市场代码 (HK/US)
            is_active: 是否活跃
            activity_score: 活跃度评分
            turnover_rate: 换手率
            turnover_amount: 成交额

        Returns:
            是否保存成功
        """
        try:
            rows = self.execute_update('''
                INSERT OR REPLACE INTO daily_active_stocks
                (check_date, stock_code, market, is_active, activity_score, turnover_rate, turnover_amount)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (check_date, stock_code, market, 1 if is_active else 0,
                  activity_score, turnover_rate, turnover_amount))
            return rows >= 0
        except Exception as e:
            logging.error(f"保存每日活跃度结果失败: {e}")
            return False

    def save_daily_activity_batch(self, check_date: str, results: List[Dict]) -> int:
        """批量保存当天活跃度检查结果

        Args:
            check_date: 检查日期 (YYYY-MM-DD)
            results: 结果列表，每项包含 stock_code, market, is_active 等字段

        Returns:
            保存成功的记录数
        """
        try:
            params_list = [
                (check_date, r['stock_code'], r.get('market', 'HK'),
                 1 if r.get('is_active', False) else 0,
                 r.get('activity_score', 0),
                 r.get('turnover_rate', 0),
                 r.get('turnover_amount', 0))
                for r in results
            ]

            with self.conn_manager.lock:
                with self.conn_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.executemany('''
                        INSERT OR REPLACE INTO daily_active_stocks
                        (check_date, stock_code, market, is_active, activity_score, turnover_rate, turnover_amount)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', params_list)
                    conn.commit()
                    return cursor.rowcount if cursor.rowcount >= 0 else 0
        except Exception as e:
            logging.error(f"批量保存每日活跃度结果失败: {e}")
            return 0

    def clear_old_activity_records(self, days_to_keep: int = 7) -> int:
        """清理过期的活跃度记录

        Args:
            days_to_keep: 保留的天数（默认7天）

        Returns:
            删除的记录数
        """
        try:
            time_offset = f'-{days_to_keep} days'
            rows = self.execute_update('''
                DELETE FROM daily_active_stocks
                WHERE check_date < date('now', 'localtime', ?)
            ''', (time_offset,))

            if rows > 0:
                logging.info(f"清理了 {rows} 条过期活跃度记录")
            return rows if rows >= 0 else 0
        except Exception as e:
            logging.error(f"清理过期活跃度记录失败: {e}")
            return 0

    def clear_daily_activity_records(self, check_date: str) -> int:
        """清空指定日期的活跃度筛选记录

        Args:
            check_date: 检查日期 (YYYY-MM-DD)

        Returns:
            删除的记录数
        """
        try:
            rows = self.execute_update('''
                DELETE FROM daily_active_stocks
                WHERE check_date = ?
            ''', (check_date,))

            if rows > 0:
                logging.info(f"清空了 {check_date} 的 {rows} 条活跃度记录")
            return rows if rows >= 0 else 0
        except Exception as e:
            logging.error(f"清空活跃度记录失败: {e}")
            return 0

    def get_daily_activity_stats(self, check_date: str) -> Dict[str, Any]:
        """获取指定日期的活跃度统计信息

        Args:
            check_date: 检查日期 (YYYY-MM-DD)

        Returns:
            统计信息字典
        """
        try:
            result = self.execute_query('''
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) as active_count,
                    market
                FROM daily_active_stocks
                WHERE check_date = ?
                GROUP BY market
            ''', (check_date,))

            stats = {
                'check_date': check_date,
                'total': 0,
                'active_count': 0,
                'by_market': {}
            }

            for row in result:
                total, active, market = row
                stats['total'] += total
                stats['active_count'] += active
                stats['by_market'][market] = {
                    'total': total,
                    'active_count': active
                }

            return stats
        except Exception as e:
            logging.error(f"获取每日活跃度统计失败: {e}")
            return {'check_date': check_date, 'total': 0, 'active_count': 0, 'by_market': {}}
