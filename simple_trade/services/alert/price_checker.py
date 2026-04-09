#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
价格检查执行器

职责：
- 实时检测价格是否达到监控任务的目标
- 达到目标价格时触发交易执行
- 管理触发后的任务状态更新
"""

import logging
from datetime import datetime
from typing import Dict, List, Any

from .monitor_task_manager import MonitorTask
from ...database.core.db_manager import DatabaseManager
from ...core.models import StockInfo


class PriceChecker:
    """
    价格检查执行器

    功能：
    1. 对比实时报价与监控任务的目标价格
    2. 判断买入/卖出触发条件（含止损）
    3. 触发后调用交易服务执行交易
    """

    def __init__(self, db_manager: DatabaseManager,
                 active_tasks: Dict[int, MonitorTask],
                 futu_trade_service=None):
        self.db_manager = db_manager
        self._active_tasks = active_tasks
        self.futu_trade_service = futu_trade_service

    def check_prices(self, quotes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        检查价格是否达到目标，触发交易

        Args:
            quotes: 实时报价数据列表

        Returns:
            触发的任务列表
        """
        triggered_tasks = []

        if not self._active_tasks:
            return triggered_tasks

        quotes_map = {q['code']: q for q in quotes if 'code' in q}

        for task_id, task in list(self._active_tasks.items()):
            try:
                quote = quotes_map.get(task.stock_code)
                if not quote:
                    continue

                current_price = quote.get('last_price', 0)
                if current_price <= 0:
                    continue

                triggered, trigger_reason = self._check_trigger(task, current_price)

                if triggered:
                    trade_result = self._execute_trade(task, current_price)

                    triggered_tasks.append({
                        'task': task.to_dict(),
                        'trigger_reason': trigger_reason,
                        'current_price': current_price,
                        'trade_result': trade_result
                    })

                    logging.info(
                        f"监控任务触发: {task.direction} {task.stock_code}"
                        f" - {trigger_reason}"
                    )

            except Exception as e:
                logging.error(f"检查监控任务 {task_id} 失败: {e}")

        return triggered_tasks

    def _check_trigger(self, task: MonitorTask,
                       current_price: float) -> tuple:
        """
        检查单个任务是否触发

        Returns:
            (是否触发, 触发原因)
        """
        if task.direction == 'BUY':
            if current_price <= task.target_price:
                return True, (
                    f"当前价格 {current_price:.2f} <= "
                    f"目标价格 {task.target_price:.2f}"
                )
            if (task.stop_loss_price
                    and current_price >= task.stop_loss_price):
                return True, (
                    f"触发止损: 当前价格 {current_price:.2f} >= "
                    f"止损价格 {task.stop_loss_price:.2f}"
                )

        elif task.direction == 'SELL':
            if current_price >= task.target_price:
                return True, (
                    f"当前价格 {current_price:.2f} >= "
                    f"目标价格 {task.target_price:.2f}"
                )
            if (task.stop_loss_price
                    and current_price <= task.stop_loss_price):
                return True, (
                    f"触发止损: 当前价格 {current_price:.2f} <= "
                    f"止损价格 {task.stop_loss_price:.2f}"
                )

        return False, ''

    def _execute_trade(self, task: MonitorTask,
                       current_price: float) -> Dict[str, Any]:
        """执行交易"""
        result = {'success': False, 'message': ''}

        try:
            # 更新任务状态为已触发
            self.db_manager.execute_update('''
                UPDATE monitor_tasks
                SET status = 'TRIGGERED', triggered_at = ?
                WHERE id = ?
            ''', (datetime.now().isoformat(), task.id))

            # 调用交易服务执行真实交易
            if (self.futu_trade_service
                    and self.futu_trade_service.is_trade_ready()):
                # 创建 StockInfo 对象
                stock = StockInfo(
                    code=task.stock_code,
                    name=task.stock_name
                )

                trade_result = self.futu_trade_service.execute_trade(
                    stock=stock,
                    trade_type=task.direction,
                    price=current_price,
                    quantity=task.quantity
                )

                if trade_result['success']:
                    self.db_manager.execute_update('''
                        UPDATE monitor_tasks
                        SET status = 'EXECUTED', executed_at = ?
                        WHERE id = ?
                    ''', (datetime.now().isoformat(), task.id))

                    result.update({
                        'success': True,
                        'message': (
                            f"交易执行成功: {task.direction} "
                            f"{task.stock_code} @ {current_price}"
                        ),
                        'trade_result': trade_result
                    })
                else:
                    self._mark_task_failed(task.id, trade_result['message'])
                    result['message'] = f"交易执行失败: {trade_result['message']}"
            else:
                self._mark_task_failed(task.id, "交易服务未准备好")
                result['message'] = "交易服务未准备好"

            # 从活跃任务缓存中移除
            self._active_tasks.pop(task.id, None)

        except Exception as e:
            logging.error(f"执行监控任务交易失败: {e}")
            result['message'] = f"执行异常: {str(e)}"

            try:
                self._mark_task_failed(task.id, str(e))
                self._active_tasks.pop(task.id, None)
            except Exception:
                pass

        return result

    def _mark_task_failed(self, task_id: int, error_msg: str):
        """标记任务为失败状态"""
        self.db_manager.execute_update('''
            UPDATE monitor_tasks
            SET status = 'FAILED', error_msg = ?
            WHERE id = ?
        ''', (error_msg, task_id))
