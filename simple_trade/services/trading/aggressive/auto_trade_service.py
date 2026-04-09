#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动日内交易服务

基于价格位置策略的回测最优参数，实时监控行情并自动执行买卖。
支持多只股票同时交易，自动止损。
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, date

from simple_trade.core.validation.risk_checker import RiskChecker
from simple_trade.core.models import StockInfo
from .auto_trade_models import (
    AutoTradeTask, VALID_TRANSITIONS,
    calculate_targets, should_buy, check_sell_condition, is_valid_transition,
)


class AutoTradeService:
    """自动日内交易服务"""

    def __init__(self, container):
        """
        Args:
            container: ServiceContainer 实例
        """
        self.container = container
        self.tasks: Dict[str, AutoTradeTask] = {}  # stock_code -> task
        self.risk_checker = RiskChecker()
        self._restore_active_tasks()

    # ---- 持久化方法 ----

    def _get_db(self):
        """获取 db_manager，不可用时返回 None"""
        if self.container and hasattr(self.container, 'db_manager'):
            return self.container.db_manager
        return None

    def _persist_task(self, task: AutoTradeTask):
        """持久化任务到数据库（INSERT OR REPLACE）"""
        db = self._get_db()
        if not db:
            return
        try:
            db.execute_insert(
                """INSERT OR REPLACE INTO auto_trade_tasks
                   (stock_code, quantity, zone, buy_dip_pct, sell_rise_pct,
                    stop_loss_pct, prev_close, buy_target, sell_target, stop_price,
                    status, buy_price_actual, sell_price_actual, buy_date,
                    message, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (task.stock_code, task.quantity, task.zone,
                 task.buy_dip_pct, task.sell_rise_pct, task.stop_loss_pct,
                 task.prev_close, task.buy_target, task.sell_target, task.stop_price,
                 task.status, task.buy_price_actual, task.sell_price_actual,
                 task.buy_date.isoformat() if task.buy_date else None,
                 task.message, task.created_at, task.updated_at),
            )
        except Exception as e:
            logging.error(f"[自动交易] 持久化任务失败 {task.stock_code}: {e}")

    def _update_task_status(self, task: AutoTradeTask):
        """更新任务状态到数据库"""
        db = self._get_db()
        if not db:
            return
        try:
            db.execute_update(
                """UPDATE auto_trade_tasks
                   SET status=?, message=?, updated_at=?,
                       buy_price_actual=?, sell_price_actual=?, buy_date=?
                   WHERE stock_code=? AND status NOT IN ('completed','stop_loss','stopped')
                """,
                (task.status, task.message, task.updated_at,
                 task.buy_price_actual, task.sell_price_actual,
                 task.buy_date.isoformat() if task.buy_date else None,
                 task.stock_code),
            )
        except Exception as e:
            logging.error(f"[自动交易] 更新任务状态失败 {task.stock_code}: {e}")

    def _restore_active_tasks(self):
        """从数据库恢复活跃任务（waiting_buy / bought）"""
        db = self._get_db()
        if not db:
            return
        try:
            rows = db.execute_query(
                "SELECT * FROM auto_trade_tasks WHERE status IN ('waiting_buy', 'bought')"
            )
            for row in rows:
                task = self._row_to_task(row)
                if task.status == 'bought' and task.buy_price_actual > 0:
                    # 重新计算止损价，确保保护立即生效
                    task.stop_price = round(
                        task.buy_price_actual * (1 - task.stop_loss_pct / 100), 3
                    )
                self.tasks[task.stock_code] = task
            if rows:
                logging.info(f"[自动交易] 从数据库恢复了 {len(rows)} 个活跃任务")
        except Exception as e:
            logging.error(f"[自动交易] 恢复任务失败: {e}")

    @staticmethod
    def _row_to_task(row) -> AutoTradeTask:
        """将数据库行转换为 AutoTradeTask（跳过 __post_init__ 重算）"""
        task = object.__new__(AutoTradeTask)
        task.stock_code = row[1]
        task.quantity = row[2]
        task.zone = row[3]
        task.buy_dip_pct = row[4]
        task.sell_rise_pct = row[5]
        task.stop_loss_pct = row[6]
        task.prev_close = row[7]
        task.buy_target = row[8]
        task.sell_target = row[9]
        task.stop_price = row[10]
        task.status = row[11]
        task.buy_price_actual = row[12] or 0.0
        task.sell_price_actual = row[13] or 0.0
        # buy_date: TEXT -> date
        raw_date = row[14]
        if raw_date:
            task.buy_date = date.fromisoformat(raw_date)
        else:
            task.buy_date = None
        task.message = row[15] or ''
        task.created_at = row[16] or ''
        task.updated_at = row[17] or ''
        return task

    # ---- 业务方法 ----

    def start_auto_trade(
        self,
        stock_code: str,
        quantity: int,
        zone: str,
        buy_dip_pct: float,
        sell_rise_pct: float,
        stop_loss_pct: float,
        prev_close: float,
    ) -> Dict[str, Any]:
        """启动自动交易"""
        if stock_code in self.tasks and self.tasks[stock_code].status in ('waiting_buy', 'bought'):
            return {'success': False, 'message': f'{stock_code} 已有活跃的自动交易任务'}

        if quantity <= 0 or quantity % 100 != 0:
            return {'success': False, 'message': '交易数量必须是100的正整数倍'}

        if prev_close <= 0:
            return {'success': False, 'message': '前收盘价无效'}

        task = AutoTradeTask(
            stock_code=stock_code, quantity=quantity, zone=zone,
            buy_dip_pct=buy_dip_pct, sell_rise_pct=sell_rise_pct,
            stop_loss_pct=stop_loss_pct, prev_close=prev_close,
        )
        self.tasks[stock_code] = task
        self._persist_task(task)

        logging.info(
            f"[自动交易] 启动 {stock_code}: "
            f"买入目标={task.buy_target}, 卖出目标={task.sell_target}, "
            f"止损={task.stop_price}, 数量={quantity}"
        )
        return {'success': True, 'task': task.to_dict()}

    def stop_auto_trade(self, stock_code: str) -> Dict[str, Any]:
        """停止自动交易"""
        task = self.tasks.get(stock_code)
        if not task:
            return {'success': False, 'message': f'{stock_code} 没有自动交易任务'}
        if task.status in ('completed', 'stop_loss', 'stopped'):
            return {'success': False, 'message': f'{stock_code} 任务已结束'}

        task.status = 'stopped'
        task.updated_at = datetime.now().isoformat()
        task.message = '用户手动停止'
        self._update_task_status(task)

        logging.info(f"[自动交易] 停止 {stock_code}")
        return {'success': True, 'message': f'{stock_code} 自动交易已停止'}

    def on_price_update(self, stock_code: str, price: float) -> Optional[Dict[str, Any]]:
        """实时价格更新回调 — 核心交易逻辑"""
        task = self.tasks.get(stock_code)
        if not task:
            return None

        if task.status == 'waiting_buy':
            if should_buy(price, task.buy_target):
                return self._execute_buy(task, price)
        elif task.status == 'bought':
            sell_type = self._check_sell_via_risk(task, price)
            if sell_type:
                return self._execute_sell(task, price, sell_type)
        return None

    def _check_sell_via_risk(self, task: AutoTradeTask, price: float) -> Optional[str]:
        """
        委托 RiskChecker 进行止损判断，保留独立的止盈判断。
        止损优先：先检查风控条件，再检查止盈。
        """
        entry_date = task.buy_date or date.today()
        risk_result = self.risk_checker.check_risk(
            stock_code=task.stock_code,
            entry_price=task.buy_price_actual,
            current_price=price,
            entry_date=entry_date,
        )
        if risk_result.should_sell:
            return 'stop_loss'
        if price >= task.sell_target:
            return 'profit'
        return None

    def _get_stock_info(self, stock_code: str) -> StockInfo:
        """获取股票信息"""
        db_manager = self.container.db_manager
        stock_name = db_manager.stock_queries.get_stock_name(stock_code)
        return StockInfo(code=stock_code, name=stock_name or stock_code)

    def _execute_buy(self, task: AutoTradeTask, price: float) -> Dict[str, Any]:
        """执行买入"""
        result = {'action': 'buy', 'stock_code': task.stock_code, 'price': price}
        try:
            trade_service = self._get_trade_service()
            if trade_service:
                stock = self._get_stock_info(task.stock_code)
                trade_result = trade_service.execute_trade(
                    stock=stock, trade_type='BUY',
                    price=price, quantity=task.quantity,
                )
                result['trade_result'] = trade_result
                if trade_result.get('success'):
                    task.status = 'bought'
                    task.buy_price_actual = price
                    task.buy_date = date.today()
                    task.message = f'已买入 @ {price}'
                    logging.info(f"[自动交易] {task.stock_code} 买入成功 @ {price}")
                else:
                    task.message = f'买入失败: {trade_result.get("message", "")}'
                    logging.warning(f"[自动交易] {task.stock_code} 买入失败: {trade_result}")
            else:
                task.status = 'bought'
                task.buy_price_actual = price
                task.buy_date = date.today()
                task.message = f'已买入 @ {price}（模拟）'
        except Exception as e:
            logging.error(f"[自动交易] {task.stock_code} 买入异常: {e}")
            task.message = f'买入异常: {e}'

        task.updated_at = datetime.now().isoformat()
        self._update_task_status(task)
        return result

    def _execute_sell(self, task: AutoTradeTask, price: float, sell_type: str) -> Dict[str, Any]:
        """执行卖出"""
        result = {'action': 'sell', 'stock_code': task.stock_code, 'price': price, 'type': sell_type}
        try:
            trade_service = self._get_trade_service()
            label = '止损' if sell_type == 'stop_loss' else '止盈'
            if trade_service:
                stock = self._get_stock_info(task.stock_code)
                trade_result = trade_service.execute_trade(
                    stock=stock, trade_type='SELL',
                    price=price, quantity=task.quantity,
                )
                result['trade_result'] = trade_result
                if trade_result.get('success'):
                    task.status = 'stop_loss' if sell_type == 'stop_loss' else 'completed'
                    task.sell_price_actual = price
                    task.message = f'{label}卖出 @ {price}'
                    logging.info(f"[自动交易] {task.stock_code} {label}卖出 @ {price}")
                else:
                    task.message = f'卖出失败: {trade_result.get("message", "")}'
            else:
                task.status = 'stop_loss' if sell_type == 'stop_loss' else 'completed'
                task.sell_price_actual = price
                task.message = f'{label}卖出 @ {price}（模拟）'
        except Exception as e:
            logging.error(f"[自动交易] {task.stock_code} 卖出异常: {e}")
            task.message = f'卖出异常: {e}'

        task.updated_at = datetime.now().isoformat()
        self._update_task_status(task)
        return result

    def _get_trade_service(self):
        """获取交易服务"""
        if self.container and hasattr(self.container, 'futu_trade_service'):
            return self.container.futu_trade_service
        return None

    def get_all_status(self) -> List[Dict[str, Any]]:
        """获取所有自动交易任务状态"""
        return [task.to_dict() for task in self.tasks.values()]

    def get_task(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """获取单只股票的任务状态"""
        task = self.tasks.get(stock_code)
        return task.to_dict() if task else None
