#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分仓价格监控器

负责实时价格监控和止盈卖出执行
"""

import logging
import threading
from datetime import datetime
from typing import Dict, List, Any

from ....database.core.db_manager import DatabaseManager
from ....core.models import StockInfo
from .lot_models import TakeProfitTask


class LotPriceMonitor:
    """分仓价格监控器"""

    def __init__(self, db_manager: DatabaseManager, futu_trade_service=None):
        self.db_manager = db_manager
        self.futu_trade_service = futu_trade_service
        self._lock = threading.Lock()

    def check_prices(self, quotes: List[Dict[str, Any]],
                     active_tasks: Dict[str, TakeProfitTask]) -> List[Dict[str, Any]]:
        """
        检查实时报价是否触发止盈卖出。

        Args:
            quotes: 实时报价列表，每项含 code 和 last_price
            active_tasks: 活跃的止盈任务字典

        Returns:
            触发的卖出动作列表
        """
        if not active_tasks:
            return []

        triggered = []
        quotes_map = {q['code']: q for q in quotes if 'code' in q}

        with self._lock:
            for stock_code, task in list(active_tasks.items()):
                quote = quotes_map.get(stock_code)
                if not quote:
                    continue

                price = quote.get('last_price', 0)
                if price <= 0:
                    continue

                results = self._check_task_executions(task, price, active_tasks)
                triggered.extend(results)

        return triggered

    def _check_task_executions(self, task: TakeProfitTask,
                               current_price: float,
                               active_tasks: Dict[str, TakeProfitTask]) -> List[Dict[str, Any]]:
        """检查单个任务的所有待执行仓位"""
        results = []

        try:
            # 获取该任务的 PENDING 执行记录（已按低成本排序存储）
            # 排除 deal_id IS NOT NULL 的记录，这些由 LotOrderTakeProfitService 处理
            exec_rows = self.db_manager.execute_query(
                "SELECT id, lot_buy_price, lot_quantity, trigger_price "
                "FROM take_profit_executions "
                "WHERE task_id = ? AND status = 'PENDING' "
                "AND (deal_id IS NULL OR deal_id = '') "
                "ORDER BY lot_buy_price ASC",
                (task.id,)
            )

            for row in exec_rows:
                exec_id, buy_price, quantity, trigger_price = row
                if current_price >= trigger_price:
                    result = self._execute_lot_sell(
                        task, exec_id, task.stock_code,
                        buy_price, quantity, current_price
                    )
                    results.append(result)

            # 检查是否所有仓位都已完成
            pending = self.db_manager.execute_query(
                "SELECT COUNT(*) FROM take_profit_executions "
                "WHERE task_id = ? AND status = 'PENDING'",
                (task.id,)
            )
            if pending and pending[0][0] == 0:
                self._complete_task(task, active_tasks)

        except Exception as e:
            logging.error(f"[止盈] 检查 {task.stock_code} 执行记录失败: {e}")

        return results

    def _execute_lot_sell(self, task: TakeProfitTask, exec_id: int,
                          stock_code: str, buy_price: float,
                          quantity: int, price: float) -> Dict[str, Any]:
        """执行单个仓位的止盈卖出"""
        now = datetime.now().isoformat()
        result = {'action': 'take_profit_sell', 'stock_code': stock_code,
                  'buy_price': buy_price, 'sell_price': price, 'quantity': quantity}

        try:
            # 更新状态为已触发
            self.db_manager.execute_update(
                "UPDATE take_profit_executions SET status = 'TRIGGERED', triggered_at = ? WHERE id = ?",
                (now, exec_id)
            )

            # 执行卖出
            if self.futu_trade_service and self.futu_trade_service.is_trade_ready():
                # 获取股票名称
                stock_name = self.db_manager.stock_queries.get_stock_name(stock_code)
                stock = StockInfo(code=stock_code, name=stock_name or stock_code)

                trade_result = self.futu_trade_service.execute_trade(
                    stock=stock, trade_type='SELL',
                    price=price, quantity=quantity,
                )

                if trade_result.get('success'):
                    profit = (price - buy_price) * quantity
                    self.db_manager.execute_update(
                        "UPDATE take_profit_executions "
                        "SET status='EXECUTED', sell_price=?, profit_amount=?, executed_at=? "
                        "WHERE id=?",
                        (price, profit, now, exec_id)
                    )
                    # 更新任务已卖出数
                    self.db_manager.execute_update(
                        "UPDATE take_profit_tasks SET sold_lots = sold_lots + 1, updated_at = ? WHERE id = ?",
                        (now, task.id)
                    )
                    task.sold_lots += 1
                    result['success'] = True
                    result['profit'] = profit
                    logging.info(f"[止盈] {stock_code} 卖出成功: 买入@{buy_price} 卖出@{price} 盈利{profit:.2f}")
                else:
                    self.db_manager.execute_update(
                        "UPDATE take_profit_executions SET status='FAILED', error_msg=? WHERE id=?",
                        (trade_result.get('message', ''), exec_id)
                    )
                    result['success'] = False
                    result['error'] = trade_result.get('message', '')
            else:
                self.db_manager.execute_update(
                    "UPDATE take_profit_executions SET status='FAILED', error_msg='交易服务未就绪' WHERE id=?",
                    (exec_id,)
                )
                result['success'] = False
                result['error'] = '交易服务未就绪'

        except Exception as e:
            logging.error(f"[止盈] 执行卖出异常: {e}")
            result['success'] = False
            result['error'] = str(e)

        return result

    def _complete_task(self, task: TakeProfitTask,
                       active_tasks: Dict[str, TakeProfitTask]):
        """标记任务为已完成"""
        now = datetime.now().isoformat()
        self.db_manager.execute_update(
            "UPDATE take_profit_tasks SET status = 'COMPLETED', updated_at = ? WHERE id = ?",
            (now, task.id)
        )
        active_tasks.pop(task.stock_code, None)
        logging.info(f"[止盈] 任务完成: {task.stock_code}")
