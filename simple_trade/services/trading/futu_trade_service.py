#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
富途交易执行服务（协调器）
负责协调订单管理、持仓管理和账户管理
"""

import logging
import os
from typing import Dict, Any, Optional, List

from datetime import date, datetime

from ...database.core.db_manager import DatabaseManager
from ...config.config import Config
from ...core.validation.risk_checker import RiskChecker, RiskConfig
from ...core.models import StockInfo
from . import OrderManager, PositionManager, AccountManager, TradeConfirmer


class FutuTradeService:
    """富途交易执行服务（协调器）"""

    def __init__(self, db_manager: DatabaseManager, config: Config):
        """
        初始化富途交易服务

        Args:
            db_manager: 数据库管理器
            config: 配置对象
        """
        self.db_manager = db_manager
        self.config = config

        # 从环境变量读取交易密码
        trade_password = os.environ.get('FUTU_TRADE_PASSWORD')
        if not trade_password:
            raise ValueError(
                "环境变量 FUTU_TRADE_PASSWORD 未设置。"
                "请在 .env 文件中配置交易密码。"
            )

        # 初始化子服务
        self.account_manager = AccountManager(trade_password=trade_password)
        self.order_manager = OrderManager(db_manager)
        self.position_manager = PositionManager(db_manager)

        # 初始化风控检查器
        self.risk_checker = RiskChecker()

        # 交易确认器（可选，由外部注入）
        self.trade_confirmer: Optional[TradeConfirmer] = None
        # 已确认的信号 ID 集合（异步确认完成后由调用方标记）
        self._confirmed_signals: set = set()

    def set_trade_confirmer(self, confirmer: TradeConfirmer):
        """注入交易确认器"""
        self.trade_confirmer = confirmer

    def mark_signal_confirmed(self, signal_id: int):
        """标记信号已通过确认，允许执行交易"""
        self._confirmed_signals.add(signal_id)

    def needs_confirmation(self, signal_id: Optional[int] = None) -> bool:
        """
        检查交易是否需要人工确认

        Returns:
            True 表示需要确认（有 confirmer 且非自动确认模式且信号未被确认）
        """
        if not self.trade_confirmer:
            return False
        if self.trade_confirmer.auto_confirm:
            return False
        if signal_id and signal_id in self._confirmed_signals:
            return False
        return True

    def connect_trade_api(self) -> Dict[str, Any]:
        """
        连接富途交易API

        Returns:
            连接结果字典
        """
        result = self.account_manager.connect_trade_api()

        # 如果连接成功，将交易客户端和环境传递给其他管理器
        if result['is_connected']:
            trade_client = self.account_manager.get_trade_client()
            trd_env = self.account_manager.trd_env
            self.order_manager.set_trade_client(trade_client, trd_env)
            self.position_manager.set_trade_client(trade_client, trd_env)

        return result

    def unlock_trade(self, password: Optional[str] = None) -> Dict[str, Any]:
        """
        解锁富途交易

        Args:
            password: 交易密码（可选）

        Returns:
            解锁结果字典
        """
        return self.account_manager.unlock_trade(password)

    def disconnect_trade_api(self):
        """断开富途交易API连接"""
        self.account_manager.disconnect_trade_api()

        # 清除其他管理器的交易客户端引用
        self.order_manager.set_trade_client(None)
        self.position_manager.set_trade_client(None)

    def is_trade_ready(self) -> bool:
        """
        检查是否准备好进行交易

        Returns:
            是否准备好
        """
        return self.account_manager.is_trade_ready()

    def execute_trade(self, stock: StockInfo, trade_type: str, price: float,
                     quantity: int, signal_id: Optional[int] = None) -> Dict[str, Any]:
        """
        执行交易

        Args:
            stock: 股票信息
            trade_type: 交易类型 (BUY/SELL)
            price: 价格
            quantity: 数量
            signal_id: 信号ID（可选）

        Returns:
            交易结果字典
        """
        result = {
            'success': False,
            'message': '',
            'trade_record_id': None,
            'order_id': None,
            'futu_order_id': None
        }

        # 验证参数
        if not stock.code or trade_type not in ['BUY', 'SELL']:
            result['message'] = "无效的交易参数"
            return result

        if price <= 0 or quantity <= 0 or quantity % 100 != 0:
            result['message'] = "无效的价格或数量（数量必须是100的倍数）"
            return result

        # 检查交易准备状态
        if not self.is_trade_ready():
            # 尝试重新连接和解锁
            connect_result = self.connect_trade_api()
            if not connect_result['success']:
                result['message'] = f"交易API未准备好: {connect_result['message']}"
                return result

        # 风控检查
        risk_result = self._check_trade_risk(stock.code, trade_type, price)
        if risk_result and risk_result.should_sell and trade_type == 'BUY':
            # 买入时风控触发卖出信号，说明该股票风险较高
            if risk_result.urgency >= 8:
                # 高紧急度（止损/目标止盈）→ 拒绝交易
                result['message'] = f'风控拒绝: {risk_result.reason}'
                return result
            else:
                # 中低紧急度 → 记录警告并继续
                logging.warning(f'风控警告: {risk_result.reason}')

        try:
            # 交易确认检查：如果需要确认但信号未被确认，返回等待确认状态
            if self.needs_confirmation(signal_id):
                result['message'] = '交易需要人工确认'
                result['needs_confirmation'] = True
                result['signal_id'] = signal_id
                return result

            # 信号已确认，从已确认集合中移除
            self._confirmed_signals.discard(signal_id)

            # 计算交易金额
            amount = price * quantity

            # 记录交易到数据库（状态为PENDING）
            trade_record_id = self.order_manager.create_trade_record(
                stock=stock,
                trade_type=trade_type,
                price=price,
                quantity=quantity,
                amount=amount,
                signal_id=signal_id
            )

            result['trade_record_id'] = trade_record_id

            # 执行富途下单
            order_result = self.order_manager.place_order(
                stock_code=stock.code,
                trade_type=trade_type,
                price=price,
                quantity=quantity
            )

            if order_result['success']:
                # 更新交易记录状态
                self.order_manager.update_trade_record(
                    trade_record_id=trade_record_id,
                    status='SUBMITTED',
                    futu_order_id=order_result['futu_order_id']
                )

                result.update({
                    'success': True,
                    'message': f"交易提交成功: {trade_type} {stock.code} {quantity}股 @ ${price:.2f}",
                    'futu_order_id': order_result['futu_order_id']
                })

                logging.info(f"交易提交成功: {trade_type} {stock.code} {quantity}股 @ ${price:.2f}")

            else:
                # 更新交易记录状态为失败
                self.order_manager.update_trade_record(
                    trade_record_id=trade_record_id,
                    status='FAILED',
                    error_msg=order_result['message']
                )

                result['message'] = f"交易提交失败: {order_result['message']}"

        except Exception as e:
            logging.error(f"执行交易异常: {e}")
            result['message'] = f"执行交易异常: {str(e)}"

            # 如果有交易记录，更新为失败状态
            if result['trade_record_id']:
                try:
                    self.order_manager.update_trade_record(
                        trade_record_id=result['trade_record_id'],
                        status='FAILED',
                        error_msg=str(e)
                    )
                except Exception as update_e:
                    logging.error(f"更新交易记录失败: {update_e}")

        return result

    def _check_trade_risk(self, stock_code: str, trade_type: str,
                          price: float) -> Optional['RiskCheckResult']:
        """
        执行交易前的风控检查

        Args:
            stock_code: 股票代码
            trade_type: 交易类型 (BUY/SELL)
            price: 当前价格

        Returns:
            风控检查结果，无持仓数据时返回 None
        """
        try:
            entry_price = self._get_entry_price(stock_code)
            entry_date = self._get_entry_date(stock_code)

            if entry_price <= 0 or entry_date is None:
                # 无历史持仓数据，跳过风控检查
                return None

            return self.risk_checker.check_risk(
                stock_code=stock_code,
                entry_price=entry_price,
                current_price=price,
                entry_date=entry_date,
            )
        except Exception as e:
            logging.error(f"风控检查异常: {e}")
            return None

    def _get_entry_price(self, stock_code: str) -> float:
        """
        获取股票的最近买入价格

        Args:
            stock_code: 股票代码

        Returns:
            买入价格，未找到时返回 0
        """
        try:
            result = self.db_manager.execute_query(
                "SELECT price FROM trade_records "
                "WHERE stock_code = ? AND trade_type = 'BUY' AND status = 'FILLED' "
                "ORDER BY created_at DESC LIMIT 1",
                (stock_code,)
            )
            return float(result[0][0]) if result else 0.0
        except Exception as e:
            logging.error(f"获取买入价格失败: {e}")
            return 0.0

    def _get_entry_date(self, stock_code: str) -> Optional[date]:
        """
        获取股票的最近买入日期

        Args:
            stock_code: 股票代码

        Returns:
            买入日期，未找到时返回 None
        """
        try:
            result = self.db_manager.execute_query(
                "SELECT created_at FROM trade_records "
                "WHERE stock_code = ? AND trade_type = 'BUY' AND status = 'FILLED' "
                "ORDER BY created_at DESC LIMIT 1",
                (stock_code,)
            )
            if result and result[0][0]:
                date_str = str(result[0][0]).split(' ')[0].split('T')[0]
                return datetime.strptime(date_str, '%Y-%m-%d').date()
            return None
        except Exception as e:
            logging.error(f"获取买入日期失败: {e}")
            return None

    def get_trade_records(self, limit: int = 50, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取交易记录

        Args:
            limit: 返回记录数量限制
            status: 状态过滤

        Returns:
            交易记录列表
        """
        return self.order_manager.get_trade_records(limit, status)

    def get_account_info(self) -> Dict[str, Any]:
        """
        获取账户信息

        Returns:
            包含账户列表的字典
        """
        return self.account_manager.get_account_info()

    def get_positions(self) -> Dict[str, Any]:
        """
        获取持仓信息

        Returns:
            包含持仓列表的字典
        """
        # 如果交易API未准备好，尝试自动连接
        if not self.is_trade_ready():
            connect_result = self.connect_trade_api()
            if not connect_result['success']:
                return {
                    'success': False,
                    'message': f"交易API连接失败: {connect_result['message']}",
                    'positions': []
                }

        # 获取持仓
        result = self.position_manager.get_positions()

        # 自动同步持仓股票到监控股票池
        if result['success'] and result['positions']:
            sync_result = self.position_manager.sync_positions_to_stock_pool(result['positions'])
            if sync_result['success']:
                logging.info(f"持仓同步: {sync_result['message']}")
            else:
                logging.warning(f"持仓同步警告: {sync_result['message']}")

        return result

    def get_orders(self, status_filter_list: Optional[List] = None) -> Dict[str, Any]:
        """
        获取订单信息

        Args:
            status_filter_list: 状态过滤列表

        Returns:
            包含订单列表的字典
        """
        # 如果交易API未准备好，尝试自动连接
        if not self.is_trade_ready():
            connect_result = self.connect_trade_api()
            if not connect_result['success']:
                return {
                    'success': False,
                    'message': f'交易API未就绪: {connect_result["message"]}',
                    'orders': []
                }

        result = self.order_manager.get_orders(status_filter_list)

        # order_list_query 瞬态失败时，先验证连接是否真正断开
        if not result['success'] and 'NoneType' in result.get('message', ''):
            try:
                verify = self.account_manager.trade_client.get_acc_list()
                if verify is not None and verify[0] == 0:  # RET_OK == 0
                    # 连接存活，属于瞬态错误，不标记断开
                    logging.warning(
                        f"order_list_query 瞬态失败（连接仍存活）: {result['message']}"
                    )
                else:
                    raise ValueError("验证调用返回异常")
            except Exception:
                # 连接确认断开，重连后重试
                logging.warning("确认交易连接已断开，尝试重连...")
                self.account_manager.is_trade_connected = False
                self.account_manager.is_unlocked = False
                connect_result = self.connect_trade_api()
                if connect_result['success']:
                    result = self.order_manager.get_orders(status_filter_list)

        return result

    def get_trade_status(self) -> Dict[str, Any]:
        """
        获取交易状态

        Returns:
            交易状态字典
        """
        return self.account_manager.get_trade_status()

    def sync_positions_to_stock_pool(self, positions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        将持仓股票同步到监控股票池

        Args:
            positions: 持仓列表

        Returns:
            同步结果字典
        """
        return self.position_manager.sync_positions_to_stock_pool(positions)
