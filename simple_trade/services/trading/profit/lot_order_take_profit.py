#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单笔订单止盈服务 - 创建/取消/查询止盈配置，市价卖出，订单成交检查"""

import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

from ....database.core.db_manager import DatabaseManager
from .lot_models import TakeProfitExecution


class LotOrderTakeProfitService:
    """单笔订单止盈服务"""

    ACTIVE_STATUSES = ('PENDING', 'TRIGGERED')

    def __init__(self, db_manager: DatabaseManager, futu_trade_service=None):
        self.db_manager = db_manager
        self.futu_trade_service = futu_trade_service

    def create_lot_take_profit(
        self, stock_code: str, deal_id: str,
        buy_price: float, quantity: int, take_profit_pct: float,
    ) -> Dict[str, Any]:
        """为单笔订单创建止盈配置"""
        if take_profit_pct <= 0:
            return {'success': False, 'message': '止盈点数必须大于 0'}

        trigger_price = round(buy_price * (1 + take_profit_pct / 100), 3)
        if trigger_price <= buy_price:
            return {'success': False, 'message': '止盈价格必须大于买入价格'}

        existing = self._get_active_config_by_deal_id(deal_id)
        if existing:
            return {
                'success': False,
                'message': f'该订单已有活跃的止盈配置 (ID: {existing["id"]})',
            }

        try:
            task_id = self._get_or_create_lot_task(stock_code)
            exec_id = self.db_manager.execute_insert(
                "INSERT INTO take_profit_executions "
                "(task_id, stock_code, lot_buy_price, lot_quantity, "
                "trigger_price, status, deal_id) "
                "VALUES (?, ?, ?, ?, ?, 'PENDING', ?)",
                (task_id, stock_code, buy_price, quantity, trigger_price, deal_id),
            )
            logging.info(
                f"[单笔止盈] 创建: {stock_code} deal={deal_id} "
                f"买入@{buy_price} 目标@{trigger_price} ({take_profit_pct}%)"
            )
            return {
                'success': True,
                'data': {
                    'id': exec_id, 'stock_code': stock_code,
                    'deal_id': deal_id, 'trigger_price': trigger_price,
                    'status': 'PENDING',
                },
                'message': '止盈配置创建成功',
            }
        except Exception as e:
            logging.error(f"[单笔止盈] 创建配置失败: {e}")
            return {'success': False, 'message': f'创建失败: {e}'}

    def cancel_lot_take_profit(self, execution_id: int) -> Dict[str, Any]:
        """取消单笔订单的止盈配置"""
        try:
            rows = self.db_manager.execute_query(
                "SELECT id, status FROM take_profit_executions WHERE id = ?",
                (execution_id,),
            )
            if not rows:
                return {'success': False, 'message': '止盈配置不存在'}
            if rows[0][1] not in self.ACTIVE_STATUSES:
                return {'success': False, 'message': f'当前状态 {rows[0][1]} 不可取消'}

            self.db_manager.execute_update(
                "UPDATE take_profit_executions "
                "SET status = 'CANCELLED', executed_at = ? WHERE id = ?",
                (datetime.now().isoformat(), execution_id),
            )
            logging.info(f"[单笔止盈] 取消配置 ID={execution_id}")
            return {'success': True, 'message': '止盈配置已取消'}
        except Exception as e:
            logging.error(f"[单笔止盈] 取消失败: {e}")
            return {'success': False, 'message': f'取消失败: {e}'}

    def get_lot_take_profit_configs(self, stock_code: str) -> List[Dict[str, Any]]:
        """获取某只股票的所有止盈配置"""
        try:
            rows = self.db_manager.execute_query(
                "SELECT id, task_id, stock_code, lot_buy_price, lot_quantity, "
                "trigger_price, sell_price, profit_amount, status, "
                "triggered_at, executed_at, error_msg, deal_id, order_id "
                "FROM take_profit_executions "
                "WHERE stock_code = ? AND deal_id IS NOT NULL "
                "ORDER BY id DESC",
                (stock_code,),
            )
            return [self._row_to_execution(r).to_dict() for r in rows]
        except Exception as e:
            logging.error(f"[单笔止盈] 获取配置失败: {e}")
            return []

    def get_lots_with_take_profit_status(
        self, stock_code: str, lots: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """给仓位列表附加止盈配置状态"""
        configs = self.get_lot_take_profit_configs(stock_code)
        config_map: Dict[str, Dict[str, Any]] = {}
        for cfg in configs:
            did = cfg.get('deal_id')
            if did and did not in config_map:
                config_map[did] = cfg

        result = []
        for lot in lots:
            lot_data = dict(lot)
            cfg = config_map.get(lot_data.get('deal_id'))
            if cfg:
                lot_data.update({
                    'take_profit_status': cfg['status'],
                    'take_profit_price': cfg['trigger_price'],
                    'take_profit_pct': self._calc_pct(cfg['lot_buy_price'], cfg['trigger_price']),
                    'execution_id': cfg['id'],
                })
            else:
                lot_data.update({
                    'take_profit_status': None, 'take_profit_price': None,
                    'take_profit_pct': None, 'execution_id': None,
                })
            result.append(lot_data)
        return result

    def execute_market_sell(
        self, execution_id: int, stock_code: str, quantity: int,
    ) -> Dict[str, Any]:
        """以即时市价单执行卖出。报单成功→TRIGGERED+记录order_id，报单失败→保持PENDING"""
        if not self.futu_trade_service or not self.futu_trade_service.is_trade_ready():
            return {'success': False, 'message': '交易服务未就绪'}

        try:
            order_result = self.futu_trade_service.order_manager.place_order(
                stock_code=stock_code, trade_type='SELL',
                price=0, quantity=quantity,
            )
            if order_result.get('success'):
                order_id = order_result.get('futu_order_id', '')
                self.db_manager.execute_update(
                    "UPDATE take_profit_executions "
                    "SET status = 'TRIGGERED', triggered_at = ?, order_id = ? "
                    "WHERE id = ?",
                    (datetime.now().isoformat(), str(order_id), execution_id),
                )
                logging.info(f"[单笔止盈] 报单成功: exec_id={execution_id} order={order_id}")
                return {'success': True, 'order_id': order_id, 'message': '市价卖出报单成功'}
            else:
                error_msg = order_result.get('message', '报单失败')
                self.db_manager.execute_update(
                    "UPDATE take_profit_executions SET error_msg = ? WHERE id = ?",
                    (error_msg, execution_id),
                )
                logging.warning(f"[单笔止盈] 报单失败: exec_id={execution_id} {error_msg}")
                return {'success': False, 'message': error_msg}
        except Exception as e:
            logging.error(f"[单笔止盈] 执行卖出异常: {e}")
            return {'success': False, 'message': f'执行异常: {e}'}

    def check_prices(self, quotes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """检查实时报价是否触发单笔订单止盈卖出（市价单）。

        仅处理 deal_id IS NOT NULL 的 PENDING 记录，与分仓止盈互不干扰。

        Args:
            quotes: 实时报价列表，每项含 code 和 last_price

        Returns:
            触发的卖出动作列表
        """
        if not quotes:
            return []

        triggered = []
        quotes_map = {q['code']: q for q in quotes if 'code' in q}

        try:
            rows = self.db_manager.execute_query(
                "SELECT id, stock_code, lot_buy_price, lot_quantity, trigger_price "
                "FROM take_profit_executions "
                "WHERE status = 'PENDING' AND deal_id IS NOT NULL "
                "ORDER BY stock_code, lot_buy_price ASC"
            )
            if not rows:
                return []

            for exec_id, stock_code, buy_price, quantity, trigger_price in rows:
                quote = quotes_map.get(stock_code)
                if not quote:
                    continue
                price = quote.get('last_price', 0)
                if price <= 0 or price < trigger_price:
                    continue

                # 使用市价单执行卖出
                result = self.execute_market_sell(exec_id, stock_code, quantity)
                triggered.append({
                    'action': 'lot_order_take_profit_sell',
                    'stock_code': stock_code,
                    'buy_price': buy_price,
                    'trigger_price': trigger_price,
                    'current_price': price,
                    'quantity': quantity,
                    'success': result.get('success', False),
                    'order_id': result.get('order_id'),
                    'error': result.get('message') if not result.get('success') else None,
                })
                if result.get('success'):
                    logging.info(
                        f"[单笔止盈] 触发: {stock_code} exec={exec_id} "
                        f"当前价{price} >= 目标价{trigger_price}"
                    )

        except Exception as e:
            logging.error(f"[单笔止盈] 检查价格触发异常: {e}", exc_info=True)

        return triggered

    def check_triggered_orders(self) -> None:
        """检查所有 TRIGGERED 订单的成交情况：完全成交→EXECUTED，未成交/超时→FAILED"""
        try:
            rows = self.db_manager.execute_query(
                "SELECT id, stock_code, lot_buy_price, lot_quantity, "
                "order_id, triggered_at "
                "FROM take_profit_executions "
                "WHERE status = 'TRIGGERED' AND order_id IS NOT NULL "
                "AND deal_id IS NOT NULL"
            )
            if not rows or not self.futu_trade_service:
                return

            orders_result = self.futu_trade_service.get_orders()
            if not orders_result.get('success'):
                return

            order_map = {str(o['order_id']): o for o in orders_result.get('orders', [])}
            for exec_id, stock_code, buy_price, qty, order_id, _ in rows:
                order_info = order_map.get(str(order_id))
                if order_info:
                    self._process_order_status(exec_id, stock_code, buy_price, qty, order_info)
        except Exception as e:
            logging.error(f"[单笔止盈] 检查已触发订单失败: {e}")

    # ==================== 内部方法 ====================

    def _process_order_status(
        self, exec_id: int, stock_code: str,
        buy_price: float, qty: int, order_info: Dict[str, Any],
    ) -> None:
        """处理单个已触发订单的成交状态"""
        order_status = str(order_info.get('order_status', ''))
        now = datetime.now().isoformat()

        if order_status in ('FILLED_ALL', '全部成交'):
            dealt_price = float(order_info.get('dealt_avg_price', 0))
            dealt_qty = int(order_info.get('dealt_qty', qty))
            profit = round((dealt_price - buy_price) * dealt_qty, 2)
            self.db_manager.execute_update(
                "UPDATE take_profit_executions "
                "SET status = 'EXECUTED', sell_price = ?, profit_amount = ?, "
                "executed_at = ? WHERE id = ?",
                (dealt_price, profit, now, exec_id),
            )
            logging.info(f"[单笔止盈] 成交: {stock_code} exec={exec_id} @{dealt_price} 盈利{profit}")
        elif order_status in ('FAILED', 'CANCELLED_ALL', 'CANCELLED_PART', '失败', '全部撤单', '部分成交'):
            dealt_qty = int(order_info.get('dealt_qty', 0))
            error_msg = f"订单状态: {order_status}, 已成交: {dealt_qty}/{qty}"
            self.db_manager.execute_update(
                "UPDATE take_profit_executions "
                "SET status = 'FAILED', error_msg = ?, executed_at = ? WHERE id = ?",
                (error_msg, now, exec_id),
            )
            logging.warning(f"[单笔止盈] 未完全成交: {stock_code} exec={exec_id} {error_msg}")

    def _get_active_config_by_deal_id(self, deal_id: str) -> Optional[Dict[str, Any]]:
        """查询 deal_id 是否已有活跃的止盈配置"""
        rows = self.db_manager.execute_query(
            "SELECT id, status FROM take_profit_executions "
            "WHERE deal_id = ? AND status IN ('PENDING', 'TRIGGERED')",
            (deal_id,),
        )
        return {'id': rows[0][0], 'status': rows[0][1]} if rows else None

    def _get_or_create_lot_task(self, stock_code: str) -> int:
        """获取或创建单笔订单止盈的专用任务记录"""
        rows = self.db_manager.execute_query(
            "SELECT id FROM take_profit_tasks "
            "WHERE stock_code = ? AND status = 'ACTIVE'",
            (stock_code,),
        )
        if rows:
            return rows[0][0]
        stock_name = self.db_manager.stock_queries.get_stock_name(stock_code)
        return self.db_manager.execute_insert(
            "INSERT INTO take_profit_tasks "
            "(stock_code, stock_name, take_profit_pct, status, total_lots, sold_lots) "
            "VALUES (?, ?, 0, 'ACTIVE', 0, 0)",
            (stock_code, stock_name),
        )

    @staticmethod
    def _calc_pct(buy_price: float, trigger_price: float) -> float:
        """计算止盈百分比"""
        if buy_price <= 0:
            return 0.0
        return round((trigger_price - buy_price) / buy_price * 100, 2)

    @staticmethod
    def _row_to_execution(row: tuple) -> TakeProfitExecution:
        """将数据库行转换为 TakeProfitExecution 对象"""
        return TakeProfitExecution(
            id=row[0], task_id=row[1], stock_code=row[2],
            lot_buy_price=row[3], lot_quantity=row[4],
            trigger_price=row[5], sell_price=row[6],
            profit_amount=row[7], status=row[8],
            triggered_at=row[9], executed_at=row[10],
            error_msg=row[11], deal_id=row[12], order_id=row[13],
        )
