#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易信号历史查询服务
负责历史交易信号的查询操作
"""

import logging
from typing import Optional, List
from ..core.connection_manager import ConnectionManager
from ..core.base_queries import BaseQueries
from ...core.models import TradeSignal


class TradeHistoryQueries(BaseQueries):
    """交易信号历史查询服务"""

    def __init__(self, conn_manager: ConnectionManager):
        """初始化交易信号历史查询服务

        Args:
            conn_manager: 连接管理器实例
        """
        super().__init__(conn_manager)

    def get_recent_trade_signals(self, hours: int = 24, limit: int = None) -> List[TradeSignal]:
        """获取最近的交易信号

        注意：使用参数化查询替代字符串格式化，避免SQL注入
        返回字段顺序与 get_today_signals() 一致，方便 API 层统一处理

        返回格式：TradeSignal 实例（14 个字段）

        Args:
            hours: 查询最近多少小时的信号
            limit: 限制返回数量，None表示不限制

        Returns:
            TradeSignal 实例列表
        """
        # 计算时间偏移（使用参数而非字符串格式化）
        time_offset = f'-{hours} hours'

        # 使用显式字段列表，与 get_today_signals() 保持一致
        base_query = '''
            SELECT ts.id, ts.stock_id, ts.signal_type, ts.signal_price,
                   ts.target_price, ts.stop_loss_price, ts.condition_text,
                   ts.is_executed, ts.executed_time, ts.created_at,
                   s.code, s.name, ts.strategy_id, ts.strategy_name
            FROM trade_signals ts
            JOIN stocks s ON ts.stock_id = s.id
            WHERE ts.created_at >= datetime('now', ?)
            ORDER BY ts.created_at DESC
        '''

        if limit is None:
            rows = self.execute_query(base_query, (time_offset,))
        else:
            query = base_query + ' LIMIT ?'
            rows = self.execute_query(query, (time_offset, limit))
        return [TradeSignal.from_db_row_with_stock(row) for row in rows]

    def get_history_signals(self, days: int = 30, limit: int = 100, strategy_id: str = None) -> List[TradeSignal]:
        """获取历史信号（今日以前的信号）

        只返回今日以前的交易信号，按创建时间倒序排列
        用于"信号历史"展示

        Args:
            days: 查询天数范围（默认30天）
            limit: 最大返回记录数
            strategy_id: 策略ID过滤（None表示所有策略，'all'表示显式请求所有策略）

        Returns:
            TradeSignal 实例列表

        Note:
            created_at 存储的已经是本地时间，不需要再用 'localtime' 转换
        """
        try:
            time_offset = f'-{days} days'

            # 注意：created_at 已经是本地时间格式，DATE() 不需要 'localtime' 修饰符
            if strategy_id and strategy_id != 'all':
                # 按策略过滤
                query = '''
                    SELECT ts.id, ts.stock_id, ts.signal_type, ts.signal_price,
                           ts.target_price, ts.stop_loss_price, ts.condition_text,
                           ts.is_executed, ts.executed_time, ts.created_at,
                           s.code, s.name, ts.strategy_id, ts.strategy_name
                    FROM trade_signals ts
                    JOIN stocks s ON ts.stock_id = s.id
                    WHERE DATE(ts.created_at) < DATE('now', 'localtime')
                      AND ts.created_at >= datetime('now', ?)
                      AND COALESCE(ts.strategy_id, '') = ?
                    ORDER BY ts.created_at DESC
                    LIMIT ?
                '''
                rows = self.execute_query(query, (time_offset, strategy_id, limit))
            else:
                # 获取所有策略的信号
                query = '''
                    SELECT ts.id, ts.stock_id, ts.signal_type, ts.signal_price,
                           ts.target_price, ts.stop_loss_price, ts.condition_text,
                           ts.is_executed, ts.executed_time, ts.created_at,
                           s.code, s.name, ts.strategy_id, ts.strategy_name
                    FROM trade_signals ts
                    JOIN stocks s ON ts.stock_id = s.id
                    WHERE DATE(ts.created_at) < DATE('now', 'localtime')
                      AND ts.created_at >= datetime('now', ?)
                    ORDER BY ts.created_at DESC
                    LIMIT ?
                '''
                rows = self.execute_query(query, (time_offset, limit))
            return [TradeSignal.from_db_row_with_stock(row) for row in rows]
        except Exception as e:
            logging.error(f"获取历史信号失败: {e}")
            return []

    def check_recent_signals(self, stock_id: int, hours: int = 1) -> int:
        """检查指定股票最近是否有信号

        Args:
            stock_id: 股票ID
            hours: 查询最近多少小时

        Returns:
            信号数量
        """
        time_offset = f'-{hours} hours'
        query = '''
            SELECT COUNT(*) FROM trade_signals
            WHERE stock_id = ? AND created_at >= datetime('now', ?)
        '''
        result = self.execute_query(query, (stock_id, time_offset))
        return result[0][0] if result else 0

    def cleanup_old_signals(self, days: int = 7) -> int:
        """清理旧的交易信号

        Args:
            days: 保留的天数

        Returns:
            删除的记录数
        """
        try:
            time_offset = f'-{days} days'
            query = '''
                DELETE FROM trade_signals
                WHERE created_at < datetime('now', ?)
            '''
            deleted_count = self.execute_update(query, (time_offset,))

            if deleted_count >= 0:
                logging.info(f"清理了 {deleted_count} 条旧交易信号")
            return deleted_count if deleted_count >= 0 else 0

        except Exception as e:
            logging.error(f"清理旧信号失败: {e}")
            return 0
