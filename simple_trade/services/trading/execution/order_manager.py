#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
订单管理服务
负责订单的创建、查询、修改和撤销
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional, List

from ....database.core.db_manager import DatabaseManager
from ....core.models import StockInfo

# 富途交易API
try:
    from futu import TrdSide, OrderType, TimeInForce, TrdEnv
    from futu import RET_OK, RET_ERROR
    FUTU_TRADE_AVAILABLE = True
except ImportError:
    FUTU_TRADE_AVAILABLE = False
    TrdSide = None
    OrderType = None
    TimeInForce = None
    TrdEnv = None
    RET_OK = None
    RET_ERROR = None


class OrderManager:
    """订单管理器"""

    def __init__(self, db_manager: DatabaseManager, trade_client=None):
        """
        初始化订单管理器

        Args:
            db_manager: 数据库管理器
            trade_client: 富途交易客户端
        """
        self.db_manager = db_manager
        self.trade_client = trade_client
        self.trd_env = TrdEnv.REAL if TrdEnv else None  # 由 futu_trade_service 传入

        # 初始化数据库表
        self._init_trade_tables()

    def _init_trade_tables(self):
        """初始化交易相关的数据库表"""
        try:
            # 交易记录表
            self.db_manager.execute_update('''
                CREATE TABLE IF NOT EXISTS trade_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL,
                    stock_name TEXT,
                    trade_type TEXT NOT NULL,  -- BUY/SELL
                    price REAL NOT NULL,
                    quantity INTEGER NOT NULL,
                    order_id TEXT,
                    futu_order_id TEXT,
                    status TEXT DEFAULT 'PENDING',  -- PENDING/SUBMITTED/FILLED/CANCELLED/FAILED
                    amount REAL,
                    commission REAL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    executed_at TIMESTAMP,
                    error_msg TEXT,
                    signal_id INTEGER,
                    FOREIGN KEY (signal_id) REFERENCES trade_signals(id)
                )
            ''')

            # 创建索引
            self.db_manager.execute_update('''
                CREATE INDEX IF NOT EXISTS idx_trade_records_stock_code
                ON trade_records(stock_code)
            ''')

            self.db_manager.execute_update('''
                CREATE INDEX IF NOT EXISTS idx_trade_records_status
                ON trade_records(status)
            ''')

            self.db_manager.execute_update('''
                CREATE INDEX IF NOT EXISTS idx_trade_records_created_at
                ON trade_records(created_at)
            ''')

            logging.info("订单数据库表初始化完成")

        except Exception as e:
            logging.error(f"初始化订单数据库表失败: {e}")

    def set_trade_client(self, trade_client, trd_env=None):
        """设置富途交易客户端"""
        self.trade_client = trade_client
        if trd_env is not None:
            self.trd_env = trd_env

    def place_order(self, stock_code: str, trade_type: str, price: float,
                   quantity: int) -> Dict[str, Any]:
        """
        调用富途API下单

        Args:
            stock_code: 股票代码
            trade_type: 交易类型 (BUY/SELL)
            price: 价格（0 表示市价单）
            quantity: 数量

        Returns:
            包含下单结果的字典
        """
        result = {
            'success': False,
            'message': '',
            'futu_order_id': None
        }

        if not self.trade_client:
            result['message'] = "交易客户端未初始化"
            return result

        try:
            # 确定交易方向
            trd_side = TrdSide.BUY if trade_type == 'BUY' else TrdSide.SELL

            # price <= 0 视为市价单
            is_market = price <= 0
            order_type = OrderType.MARKET if is_market else OrderType.NORMAL
            order_price = 0.01 if is_market else price  # 市价单需要一个占位价格

            logging.info(
                f"[下单] {trade_type} {stock_code} x{quantity} "
                f"{'市价单' if is_market else f'限价单@{price}'}"
            )

            # 下单
            ret, data = self.trade_client.place_order(
                price=order_price,
                qty=quantity,
                code=stock_code,
                trd_side=trd_side,
                order_type=order_type,
                adjust_limit=0,
                trd_env=self.trd_env,
                acc_id=0,
                acc_index=0,
                remark="量化交易系统自动下单",
                time_in_force=TimeInForce.DAY,
                fill_outside_rth=False,
                aux_price=None,
                trail_type=None,
                trail_value=None,
                trail_spread=None
            )

            if ret == RET_OK and data is not None:
                # 提取订单ID
                if hasattr(data, 'iloc') and len(data) > 0:
                    order_info = data.iloc[0]
                    futu_order_id = order_info.get('order_id', '')

                    result.update({
                        'success': True,
                        'message': f"富途下单成功，订单ID: {futu_order_id}",
                        'futu_order_id': futu_order_id
                    })
                else:
                    result['message'] = "富途返回数据格式异常"
            else:
                result['message'] = f"富途下单失败: ret={ret}, data={data}"

        except Exception as e:
            logging.error(f"富途下单异常: {e}")
            result['message'] = f"富途下单异常: {str(e)}"

        return result

    def create_trade_record(self, stock: StockInfo,
                           trade_type: str, price: float, quantity: int,
                           amount: float, signal_id: Optional[int] = None) -> int:
        """
        创建交易记录

        Args:
            stock: 股票信息
            trade_type: 交易类型
            price: 价格
            quantity: 数量
            amount: 金额
            signal_id: 信号ID

        Returns:
            交易记录ID
        """
        try:
            record_id = self.db_manager.execute_insert('''
                INSERT INTO trade_records
                (stock_code, stock_name, trade_type, price, quantity, amount, signal_id, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING')
            ''', (stock.code, stock.name, trade_type, price, quantity, amount, signal_id))

            return record_id

        except Exception as e:
            logging.error(f"创建交易记录失败: {e}")
            raise

    def update_trade_record(self, trade_record_id: int, status: str,
                           futu_order_id: Optional[str] = None,
                           error_msg: Optional[str] = None):
        """
        更新交易记录

        Args:
            trade_record_id: 交易记录ID
            status: 状态
            futu_order_id: 富途订单ID
            error_msg: 错误信息
        """
        try:
            executed_at = datetime.now().isoformat() if status in ['SUBMITTED', 'FILLED'] else None

            self.db_manager.execute_update('''
                UPDATE trade_records
                SET status = ?, futu_order_id = ?, error_msg = ?, executed_at = ?
                WHERE id = ?
            ''', (status, futu_order_id, error_msg, executed_at, trade_record_id))

        except Exception as e:
            logging.error(f"更新交易记录失败: {e}")

    def get_trade_records(self, limit: int = 50, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取交易记录

        Args:
            limit: 返回记录数量限制
            status: 状态过滤

        Returns:
            交易记录列表
        """
        try:
            sql = '''
                SELECT id, stock_code, stock_name, trade_type, price, quantity,
                       amount, status, futu_order_id, created_at, executed_at, error_msg
                FROM trade_records
            '''
            params = []

            if status:
                sql += ' WHERE status = ?'
                params.append(status)

            sql += ' ORDER BY created_at DESC LIMIT ?'
            params.append(limit)

            records = self.db_manager.execute_query(sql, params)

            return [
                {
                    'id': record[0],
                    'stock_code': record[1],
                    'stock_name': record[2],
                    'trade_type': record[3],
                    'price': record[4],
                    'quantity': record[5],
                    'amount': record[6],
                    'status': record[7],
                    'futu_order_id': record[8],
                    'created_at': record[9],
                    'executed_at': record[10],
                    'error_msg': record[11]
                }
                for record in records
            ]

        except Exception as e:
            logging.error(f"获取交易记录失败: {e}")
            return []

    def get_orders(self, status_filter_list: Optional[List] = None) -> Dict[str, Any]:
        """
        获取订单信息

        Args:
            status_filter_list: 状态过滤列表

        Returns:
            包含订单列表的字典
        """
        result = {
            'success': False,
            'message': '',
            'orders': []
        }

        if not self.trade_client:
            result['message'] = "交易客户端未初始化"
            return result

        try:
            filter_list = status_filter_list if status_filter_list is not None else []
            query_result = self.trade_client.order_list_query(
                status_filter_list=filter_list,
                trd_env=self.trd_env
            )

            if query_result is None:
                result['message'] = "交易连接已断开(order_list_query返回None)"
                return result

            ret, data = query_result

            if ret == RET_OK and data is not None:
                orders = []
                for _, row in data.iterrows():
                    orders.append({
                        'order_id': row.get('order_id', ''),
                        'stock_code': row.get('code', ''),
                        'stock_name': row.get('stock_name', ''),
                        'trd_side': row.get('trd_side', ''),
                        'order_type': row.get('order_type', ''),
                        'order_status': row.get('order_status', ''),
                        'qty': row.get('qty', 0),
                        'price': row.get('price', 0),
                        'create_time': row.get('create_time', ''),
                        'updated_time': row.get('updated_time', ''),
                        'dealt_qty': row.get('dealt_qty', 0),
                        'dealt_avg_price': row.get('dealt_avg_price', 0)
                    })

                result.update({
                    'success': True,
                    'message': f"获取到 {len(orders)} 个订单",
                    'orders': orders
                })
            else:
                result['message'] = f"获取订单信息失败: ret={ret}, data={data}"

        except Exception as e:
            logging.error(f"获取订单信息异常: {e}")
            result['message'] = f"获取订单信息异常: {str(e)}"

        return result

    def get_history_deals(self, stock_code: str = '') -> Dict[str, Any]:
        """
        从富途API获取历史成交记录

        Args:
            stock_code: 股票代码（空字符串表示获取所有）

        Returns:
            包含成交记录列表的字典
        """
        result = {
            'success': False,
            'message': '',
            'deals': []
        }

        if not self.trade_client:
            result['message'] = "交易客户端未初始化"
            return result

        try:
            kwargs = {}
            if stock_code:
                kwargs['code'] = stock_code

            ret, data = self.trade_client.history_deal_list_query(**kwargs)

            if ret == RET_OK and data is not None:
                deals = []
                for _, row in data.iterrows():
                    deals.append({
                        'deal_id': str(row.get('deal_id', '')),
                        'order_id': str(row.get('order_id', '')),
                        'stock_code': row.get('code', ''),
                        'stock_name': row.get('stock_name', ''),
                        'trd_side': row.get('trd_side', ''),
                        'price': float(row.get('price', 0)),
                        'qty': int(row.get('qty', 0)),
                        'create_time': row.get('create_time', ''),
                        'counter_broker_id': row.get('counter_broker_id', ''),
                        'counter_broker_name': row.get('counter_broker_name', ''),
                    })

                result.update({
                    'success': True,
                    'message': f"获取到 {len(deals)} 条历史成交",
                    'deals': deals
                })
            else:
                result['message'] = f"获取历史成交失败: ret={ret}, data={data}"

        except Exception as e:
            logging.error(f"获取历史成交异常: {e}")
            result['message'] = f"获取历史成交异常: {str(e)}"

        return result
