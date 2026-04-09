#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易信号查询服务
负责交易信号的插入和今日信号查询操作
"""

import logging
from typing import Optional, List
from ..core.connection_manager import ConnectionManager
from ..core.base_queries import BaseQueries
from ...core.models import TradeSignal


class TradeQueries(BaseQueries):
    """交易信号查询服务"""

    def __init__(self, conn_manager: ConnectionManager):
        """初始化交易信号查询服务

        Args:
            conn_manager: 连接管理器实例
        """
        super().__init__(conn_manager)

    def get_today_signals(self, limit: int = 50, strategy_id: str = None) -> List[TradeSignal]:
        """获取今日信号（实时信号用）

        只返回当天的交易信号，按创建时间倒序排列
        同一只股票同一类型同一策略的信号只返回最新一条（去重）

        Args:
            limit: 最大返回记录数
            strategy_id: 策略ID过滤（None表示所有策略，'all'表示显式请求所有策略）

        Returns:
            TradeSignal 实例列表

        Note:
            created_at 存储的已经是本地时间，不需要再用 'localtime' 转换
        """
        try:
            # 使用子查询按 stock_id + signal_type + strategy_id 分组，取每组最新的一条
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
                    WHERE DATE(ts.created_at) = DATE('now', 'localtime')
                      AND COALESCE(ts.strategy_id, '') = ?
                      AND ts.id IN (
                          SELECT MAX(id)
                          FROM trade_signals
                          WHERE DATE(created_at) = DATE('now', 'localtime')
                            AND COALESCE(strategy_id, '') = ?
                          GROUP BY stock_id, signal_type
                      )
                    ORDER BY ts.created_at DESC
                    LIMIT ?
                '''
                rows = self.execute_query(query, (strategy_id, strategy_id, limit))
            else:
                # 获取所有策略的信号
                query = '''
                    SELECT ts.id, ts.stock_id, ts.signal_type, ts.signal_price,
                           ts.target_price, ts.stop_loss_price, ts.condition_text,
                           ts.is_executed, ts.executed_time, ts.created_at,
                           s.code, s.name, ts.strategy_id, ts.strategy_name
                    FROM trade_signals ts
                    JOIN stocks s ON ts.stock_id = s.id
                    WHERE DATE(ts.created_at) = DATE('now', 'localtime')
                      AND ts.id IN (
                          SELECT MAX(id)
                          FROM trade_signals
                          WHERE DATE(created_at) = DATE('now', 'localtime')
                          GROUP BY stock_id, signal_type, COALESCE(strategy_id, '')
                      )
                    ORDER BY ts.created_at DESC
                    LIMIT ?
                '''
                rows = self.execute_query(query, (limit,))
            return [TradeSignal.from_db_row_with_stock(row) for row in rows]
        except Exception as e:
            logging.error(f"获取今日信号失败: {e}")
            return []

    def insert_trade_signal_with_dedup(self, stock_id: int, signal_type: str, signal_price: float,
                                       condition_text: str, target_price: Optional[float] = None,
                                       stop_loss_price: Optional[float] = None,
                                       strategy_id: Optional[str] = None,
                                       strategy_name: Optional[str] = None) -> int:
        """插入交易信号（带去重）

        同一只股票同一天同一类型同一策略的信号只保留一条（更新最新的）

        Args:
            stock_id: 股票ID
            signal_type: 信号类型 (BUY/SELL)
            signal_price: 信号价格
            condition_text: 条件说明
            target_price: 目标价格
            stop_loss_price: 止损价格
            strategy_id: 策略ID（如 'trend_reversal', 'aggressive'）
            strategy_name: 策略显示名称（如 '高抛低吸策略'）

        Returns:
            信号ID（新插入或更新的）

        Note:
            created_at 存储的已经是本地时间，不需要再用 'localtime' 转换
        """
        try:
            # 先检查今天是否已有相同股票相同类型相同策略的信号
            # 注意：created_at 已经是本地时间格式，DATE() 不需要 'localtime' 修饰符
            check_query = '''
                SELECT id FROM trade_signals
                WHERE stock_id = ? AND signal_type = ? AND COALESCE(strategy_id, '') = ?
                  AND DATE(created_at) = DATE('now', 'localtime')
            '''
            existing = self.execute_query(check_query, (stock_id, signal_type, strategy_id or ''))

            if existing:
                # 已存在，更新
                signal_id = existing[0][0]
                update_query = '''
                    UPDATE trade_signals
                    SET signal_price = ?, condition_text = ?, target_price = ?,
                        stop_loss_price = ?, strategy_id = ?, strategy_name = ?,
                        created_at = datetime('now', 'localtime')
                    WHERE id = ?
                '''
                self.execute_update(update_query, (signal_price, condition_text, target_price,
                                                   stop_loss_price, strategy_id, strategy_name, signal_id))
                logging.debug(f"更新已存在信号: stock_id={stock_id}, type={signal_type}, strategy={strategy_id}, id={signal_id}")
                return signal_id
            else:
                # 不存在，插入新记录
                insert_query = '''
                    INSERT INTO trade_signals (stock_id, signal_type, signal_price, condition_text,
                                             target_price, stop_loss_price, strategy_id, strategy_name, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
                '''
                signal_id = self.execute_insert(insert_query, (stock_id, signal_type, signal_price,
                                                                condition_text, target_price, stop_loss_price,
                                                                strategy_id, strategy_name))
                logging.debug(f"插入新信号: stock_id={stock_id}, type={signal_type}, strategy={strategy_id}, id={signal_id}")
                return signal_id
        except Exception as e:
            logging.error(f"插入/更新信号失败: {e}")
            return -1

    def get_tp_order_to_deal_map(self, stock_code: str) -> dict:
        """查询某只股票已执行的止盈记录，返回 order_id -> deal_id 的映射。

        仅返回 status 为 EXECUTED 或 TRIGGERED 且 order_id 和 deal_id 均非空的记录。
        查询失败时返回空字典并记录 warning 日志。

        Args:
            stock_code: 股票代码

        Returns:
            {order_id: deal_id} 字典
        """
        try:
            rows = self.execute_query(
                """
                SELECT order_id, deal_id
                FROM take_profit_executions
                WHERE stock_code = ?
                  AND status IN ('EXECUTED', 'TRIGGERED')
                  AND order_id IS NOT NULL AND order_id != ''
                  AND deal_id IS NOT NULL AND deal_id != ''
                """,
                (stock_code,),
            )
            return {row[0]: row[1] for row in rows}
        except Exception as e:
            logging.warning("查询止盈映射失败 stock_code=%s: %s", stock_code, e)
            return {}



    def insert_trade_signal(self, stock_id: int, signal_type: str, signal_price: float,
                          condition_text: str, target_price: Optional[float] = None,
                          stop_loss_price: Optional[float] = None,
                          strategy_id: Optional[str] = None,
                          strategy_name: Optional[str] = None) -> bool:
        """插入交易信号

        Args:
            stock_id: 股票ID
            signal_type: 信号类型 (BUY/SELL)
            signal_price: 信号价格
            condition_text: 条件说明
            target_price: 目标价格
            stop_loss_price: 止损价格
            strategy_id: 策略ID
            strategy_name: 策略显示名称

        Returns:
            是否插入成功
        """
        query = '''
            INSERT INTO trade_signals (stock_id, signal_type, signal_price, condition_text,
                                     target_price, stop_loss_price, strategy_id, strategy_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        '''
        rows = self.execute_update(query, (stock_id, signal_type, signal_price, condition_text,
                                          target_price, stop_loss_price, strategy_id, strategy_name))
        return rows >= 0

    def get_tp_order_to_deal_map(self, stock_code: str) -> dict:
        """查询某只股票已执行的止盈记录，返回 order_id -> deal_id 的映射。

        仅返回 status 为 EXECUTED 或 TRIGGERED 且 order_id 和 deal_id 均非空的记录。

        Args:
            stock_code: 股票代码

        Returns:
            {order_id: deal_id} 字典
        """
        try:
            rows = self.execute_query(
                """
                SELECT order_id, deal_id
                FROM take_profit_executions
                WHERE stock_code = ?
                  AND status IN ('EXECUTED', 'TRIGGERED')
                  AND order_id IS NOT NULL AND order_id != ''
                  AND deal_id IS NOT NULL AND deal_id != ''
                """,
                (stock_code,),
            )
            return {row[0]: row[1] for row in rows}
        except Exception as e:
            logging.warning("查询止盈映射失败 stock_code=%s: %s", stock_code, e)
            return {}
