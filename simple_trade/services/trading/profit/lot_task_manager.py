#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分仓任务管理器

负责止盈任务的创建、取消、查询和仓位还原
"""

import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

from ....database.core.db_manager import DatabaseManager
from .lot_models import PositionLot, TakeProfitTask


class LotTaskManager:
    """分仓任务管理器"""

    def __init__(self, db_manager: DatabaseManager, futu_trade_service=None):
        self.db_manager = db_manager
        self.futu_trade_service = futu_trade_service
        self._init_tables()

    def _init_tables(self):
        """确保数据库表存在"""
        try:
            self.db_manager.execute_update('''
                CREATE TABLE IF NOT EXISTS take_profit_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL,
                    stock_name TEXT,
                    take_profit_pct REAL NOT NULL,
                    status TEXT DEFAULT 'ACTIVE',
                    total_lots INTEGER DEFAULT 0,
                    sold_lots INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            self.db_manager.execute_update('''
                CREATE TABLE IF NOT EXISTS take_profit_executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    stock_code TEXT NOT NULL,
                    lot_buy_price REAL NOT NULL,
                    lot_quantity INTEGER NOT NULL,
                    trigger_price REAL NOT NULL,
                    sell_price REAL,
                    profit_amount REAL,
                    status TEXT DEFAULT 'PENDING',
                    triggered_at TIMESTAMP,
                    executed_at TIMESTAMP,
                    error_msg TEXT,
                    FOREIGN KEY (task_id) REFERENCES take_profit_tasks(id)
                )
            ''')
        except Exception as e:
            logging.error(f"初始化止盈表失败: {e}")

    def load_active_tasks(self) -> Dict[str, TakeProfitTask]:
        """从数据库加载活跃的止盈任务"""
        tasks = {}
        try:
            rows = self.db_manager.execute_query(
                "SELECT id, stock_code, stock_name, take_profit_pct, status, "
                "total_lots, sold_lots, created_at, updated_at "
                "FROM take_profit_tasks WHERE status = 'ACTIVE'"
            )
            for row in rows:
                task = TakeProfitTask(
                    id=row[0], stock_code=row[1], stock_name=row[2],
                    take_profit_pct=row[3], status=row[4],
                    total_lots=row[5], sold_lots=row[6],
                    created_at=row[7], updated_at=row[8] or '',
                )
                tasks[task.stock_code] = task
            logging.info(f"加载了 {len(tasks)} 个活跃止盈任务")
        except Exception as e:
            logging.error(f"加载止盈任务失败: {e}")
        return tasks

    # ==================== 仓位还原 ====================

    def get_position_lots(self, stock_code: str) -> List[PositionLot]:
        """
        从富途API历史成交记录还原各仓位（FIFO算法）。

        Returns:
            remaining_qty > 0 的仓位列表
        """
        if not self.futu_trade_service:
            logging.warning("交易服务未初始化，无法获取历史成交")
            return []

        order_mgr = self.futu_trade_service.order_manager
        deal_result = order_mgr.get_history_deals(stock_code)

        if not deal_result['success']:
            logging.warning(f"获取 {stock_code} 历史成交失败: {deal_result['message']}")
            return []

        deals = deal_result['deals']
        # 按时间排序
        deals.sort(key=lambda d: d.get('create_time', ''))
        return self._restore_lots_fifo(deals, stock_code)

    @staticmethod
    def _deduct_fifo(lots: List[PositionLot], sell_qty: int) -> None:
        """按 FIFO 顺序从仓位列表中扣减卖出数量（原地修改）"""
        for lot in lots:
            if sell_qty <= 0:
                break
            if lot.remaining_qty > 0:
                deduct = min(lot.remaining_qty, sell_qty)
                lot.remaining_qty -= deduct
                sell_qty -= deduct

    def _restore_lots_fifo(self, deals: List[Dict], stock_code: str) -> List[PositionLot]:
        """FIFO + 止盈精确匹配方式还原仓位

        对于每笔卖出成交：
        1. 查找 tp_map 中是否有该卖出 order_id 对应的买入 deal_id
        2. 如果有，优先从对应买入仓位抵消
        3. 如果没有或对应仓位不足，按 FIFO 从最早仓位开始抵消
        """
        lots: List[PositionLot] = []
        tp_map = self.db_manager.trade_queries.get_tp_order_to_deal_map(stock_code)

        for deal in deals:
            if deal.get('stock_code', '') != stock_code:
                continue

            trd_side = deal.get('trd_side', '')
            qty = int(deal.get('qty', 0))
            price = float(deal.get('price', 0))

            if trd_side == 'BUY':
                lots.append(PositionLot(
                    deal_id=deal.get('deal_id', ''),
                    stock_code=stock_code,
                    buy_price=price,
                    quantity=qty,
                    remaining_qty=qty,
                    deal_time=deal.get('create_time', ''),
                ))
            elif trd_side == 'SELL':
                sell_qty = qty
                order_id = deal.get('order_id', '')

                # 止盈精确匹配：优先从映射指定的买入仓位扣减
                if order_id and order_id in tp_map:
                    target_deal_id = tp_map[order_id]
                    for lot in lots:
                        if lot.deal_id == target_deal_id and lot.remaining_qty > 0:
                            deduct = min(lot.remaining_qty, sell_qty)
                            lot.remaining_qty -= deduct
                            sell_qty -= deduct
                            break

                # 剩余部分（或无映射）按 FIFO 扣减
                if sell_qty > 0:
                    LotTaskManager._deduct_fifo(lots, sell_qty)

        return [lot for lot in lots if lot.remaining_qty > 0]

    # ==================== 任务管理 ====================

    def create_task(self, stock_code: str, take_profit_pct: float,
                    active_tasks: Dict[str, TakeProfitTask]) -> Dict[str, Any]:
        """创建分仓止盈任务"""
        if stock_code in active_tasks:
            return {'success': False, 'message': f'{stock_code} 已有活跃的止盈任务'}

        if take_profit_pct <= 0 or take_profit_pct > 100:
            return {'success': False, 'message': '止盈百分比必须在 0-100 之间'}

        # 获取仓位
        lots = self.get_position_lots(stock_code)
        if not lots:
            return {'success': False, 'message': f'{stock_code} 没有可用的持仓仓位'}

        # 计算每个仓位的止盈触发价
        for lot in lots:
            lot.trigger_price = round(lot.buy_price * (1 + take_profit_pct / 100), 3)

        # 获取股票名称
        stock_name = self.db_manager.stock_queries.get_stock_name(stock_code)

        try:
            # 写入任务表
            task_id = self.db_manager.execute_insert(
                "INSERT INTO take_profit_tasks "
                "(stock_code, stock_name, take_profit_pct, status, total_lots, sold_lots) "
                "VALUES (?, ?, ?, 'ACTIVE', ?, 0)",
                (stock_code, stock_name, take_profit_pct, len(lots))
            )

            # 写入执行记录（每个仓位一条），按低成本优先排序
            lots_sorted = sorted(lots, key=lambda l: l.buy_price)
            for lot in lots_sorted:
                self.db_manager.execute_insert(
                    "INSERT INTO take_profit_executions "
                    "(task_id, stock_code, lot_buy_price, lot_quantity, trigger_price, status) "
                    "VALUES (?, ?, ?, ?, ?, 'PENDING')",
                    (task_id, stock_code, lot.buy_price, lot.remaining_qty, lot.trigger_price)
                )

            # 创建任务对象
            task = TakeProfitTask(
                id=task_id, stock_code=stock_code, stock_name=stock_name,
                take_profit_pct=take_profit_pct, status='ACTIVE',
                total_lots=len(lots), sold_lots=0,
                created_at=datetime.now().isoformat(), lots=lots_sorted,
            )

            logging.info(f"[止盈] 创建任务: {stock_code}, {len(lots)}个仓位, 止盈{take_profit_pct}%")
            return {'success': True, 'task': task.to_dict(), 'task_obj': task}

        except Exception as e:
            logging.error(f"创建止盈任务失败: {e}")
            return {'success': False, 'message': f'创建失败: {e}'}

    def cancel_task(self, task: TakeProfitTask) -> Dict[str, Any]:
        """取消止盈任务"""
        try:
            now = datetime.now().isoformat()
            self.db_manager.execute_update(
                "UPDATE take_profit_tasks SET status = 'CANCELLED', updated_at = ? WHERE id = ?",
                (now, task.id)
            )
            self.db_manager.execute_update(
                "UPDATE take_profit_executions SET status = 'CANCELLED' "
                "WHERE task_id = ? AND status = 'PENDING'",
                (task.id,)
            )
            logging.info(f"[止盈] 取消任务: {task.stock_code}")
            return {'success': True, 'message': f'{task.stock_code} 止盈任务已取消'}
        except Exception as e:
            logging.error(f"取消止盈任务失败: {e}")
            return {'success': False, 'message': f'取消失败: {e}'}

    def get_task_detail(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """获取任务详情（含执行记录）"""
        try:
            rows = self.db_manager.execute_query(
                "SELECT id, stock_code, stock_name, take_profit_pct, status, "
                "total_lots, sold_lots, created_at, updated_at "
                "FROM take_profit_tasks WHERE stock_code = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (stock_code,)
            )
            if not rows:
                return None

            row = rows[0]
            task_id = row[0]

            # 获取执行记录
            from .lot_models import TakeProfitExecution
            exec_rows = self.db_manager.execute_query(
                "SELECT id, task_id, stock_code, lot_buy_price, lot_quantity, "
                "trigger_price, sell_price, profit_amount, status, "
                "triggered_at, executed_at, error_msg "
                "FROM take_profit_executions WHERE task_id = ? "
                "ORDER BY lot_buy_price ASC",
                (task_id,)
            )

            executions = [
                TakeProfitExecution(
                    id=r[0], task_id=r[1], stock_code=r[2],
                    lot_buy_price=r[3], lot_quantity=r[4], trigger_price=r[5],
                    sell_price=r[6], profit_amount=r[7], status=r[8],
                    triggered_at=r[9], executed_at=r[10], error_msg=r[11],
                ).to_dict()
                for r in exec_rows
            ]

            return {
                'id': task_id, 'stock_code': row[1], 'stock_name': row[2],
                'take_profit_pct': row[3], 'status': row[4],
                'total_lots': row[5], 'sold_lots': row[6],
                'created_at': row[7], 'updated_at': row[8],
                'executions': executions,
            }
        except Exception as e:
            logging.error(f"获取止盈任务详情失败: {e}")
            return None

    def get_all_tasks(self) -> List[Dict[str, Any]]:
        """获取所有止盈任务"""
        try:
            rows = self.db_manager.execute_query(
                "SELECT id, stock_code, stock_name, take_profit_pct, status, "
                "total_lots, sold_lots, created_at, updated_at "
                "FROM take_profit_tasks ORDER BY created_at DESC LIMIT 50"
            )
            return [
                {
                    'id': r[0], 'stock_code': r[1], 'stock_name': r[2],
                    'take_profit_pct': r[3], 'status': r[4],
                    'total_lots': r[5], 'sold_lots': r[6],
                    'created_at': r[7], 'updated_at': r[8],
                }
                for r in rows
            ]
        except Exception as e:
            logging.error(f"获取止盈任务列表失败: {e}")
            return []
