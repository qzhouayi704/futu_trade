#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
账户管理服务
负责账户信息查询、资金查询和交易额度管理
"""

import logging
import hashlib
from typing import Dict, Any, Optional

# 富途交易API
try:
    from futu import OpenSecTradeContext, TrdEnv, SecurityFirm, TrdMarket
    from futu import RET_OK, RET_ERROR
    FUTU_TRADE_AVAILABLE = True
except ImportError:
    FUTU_TRADE_AVAILABLE = False
    OpenSecTradeContext = None
    TrdEnv = None
    SecurityFirm = None
    TrdMarket = None
    RET_OK = None
    RET_ERROR = None


class AccountManager:
    """账户管理器"""

    def __init__(self, trade_password: str = "910429"):
        """
        初始化账户管理器

        Args:
            trade_password: 交易密码
        """
        self.trade_client = None
        self.is_trade_connected = False
        self.is_unlocked = False
        self.trade_password = trade_password

    def connect_trade_api(self) -> Dict[str, Any]:
        """
        连接富途交易API

        Returns:
            连接结果字典
        """
        result = {
            'success': False,
            'message': '',
            'is_connected': False,
            'is_unlocked': False
        }

        if not FUTU_TRADE_AVAILABLE:
            result['message'] = "富途交易API不可用，请安装futu-api包"
            return result

        try:
            logging.info("正在连接富途交易API...")

            # 创建交易连接
            self.trade_client = OpenSecTradeContext(
                filter_trdmarket=TrdMarket.HK,
                host='127.0.0.1',
                port=11111,
                is_encrypt=None,
                security_firm=SecurityFirm.FUTUSECURITIES
            )

            # 测试连接
            ret, data = self.trade_client.get_acc_list()

            if ret == RET_OK:
                self.is_trade_connected = True
                result['is_connected'] = True

                logging.info(f"富途交易API连接成功，账户列表: {data}")

                # 自动解锁交易
                unlock_result = self.unlock_trade()
                result.update(unlock_result)

                if result['success']:
                    result['message'] = "富途交易API连接并解锁成功"
                else:
                    result['message'] = f"富途交易API连接成功，但解锁失败: {result['message']}"

            else:
                result['message'] = f"富途交易API连接失败: ret={ret}, data={data}"
                logging.error(result['message'])
                self.trade_client = None

        except Exception as e:
            logging.error(f"富途交易API连接异常: {e}")
            result['message'] = f"富途交易API连接异常: {str(e)}"
            self.trade_client = None

        return result

    def unlock_trade(self, password: Optional[str] = None) -> Dict[str, Any]:
        """
        解锁富途交易

        Args:
            password: 交易密码（可选，默认使用初始化时的密码）

        Returns:
            解锁结果字典
        """
        result = {
            'success': False,
            'message': '',
            'is_unlocked': False
        }

        if not self.trade_client:
            result['message'] = "交易API未连接"
            return result

        try:
            # 使用提供的密码或默认密码
            pwd = password if password else self.trade_password

            # 计算密码MD5
            password_md5 = hashlib.md5(pwd.encode('utf-8')).hexdigest()

            logging.info("正在解锁富途交易...")

            # 解锁交易
            ret, data = self.trade_client.unlock_trade(
                password=None,
                password_md5=password_md5,
                is_unlock=True
            )

            if ret == RET_OK:
                self.is_unlocked = True
                result.update({
                    'success': True,
                    'is_unlocked': True,
                    'message': '交易解锁成功'
                })
                logging.info("富途交易解锁成功")
            else:
                result['message'] = f"交易解锁失败: ret={ret}, data={data}"
                logging.error(result['message'])

        except Exception as e:
            logging.error(f"交易解锁异常: {e}")
            result['message'] = f"交易解锁异常: {str(e)}"

        return result

    def disconnect_trade_api(self):
        """断开富途交易API连接"""
        if self.trade_client:
            try:
                self.trade_client.close()
                logging.info("富途交易API连接已关闭")
            except Exception as e:
                logging.error(f"关闭富途交易API连接失败: {e}")
            finally:
                self.trade_client = None
                self.is_trade_connected = False
                self.is_unlocked = False

    def is_trade_ready(self) -> bool:
        """
        检查是否准备好进行交易

        Returns:
            是否准备好
        """
        return (FUTU_TRADE_AVAILABLE and
                self.trade_client is not None and
                self.is_trade_connected and
                self.is_unlocked)

    def get_trade_client(self):
        """
        获取交易客户端

        Returns:
            交易客户端实例
        """
        return self.trade_client

    def get_account_info(self) -> Dict[str, Any]:
        """
        获取账户信息

        Returns:
            包含账户列表的字典
        """
        result = {
            'success': False,
            'message': '',
            'accounts': []
        }

        if not self.is_trade_ready():
            result['message'] = "交易API未准备好"
            return result

        try:
            ret, data = self.trade_client.get_acc_list()

            if ret == RET_OK and data is not None:
                accounts = []
                for _, row in data.iterrows():
                    accounts.append({
                        'acc_id': row.get('acc_id', ''),
                        'trd_env': row.get('trd_env', ''),
                        'acc_type': row.get('acc_type', ''),
                        'card_num': row.get('card_num', ''),
                        'security_firm': row.get('security_firm', '')
                    })

                result.update({
                    'success': True,
                    'message': f"获取到 {len(accounts)} 个账户",
                    'accounts': accounts
                })
            else:
                result['message'] = f"获取账户信息失败: ret={ret}, data={data}"

        except Exception as e:
            logging.error(f"获取账户信息异常: {e}")
            result['message'] = f"获取账户信息异常: {str(e)}"

        return result

    def get_trade_status(self) -> Dict[str, Any]:
        """
        获取交易状态

        Returns:
            交易状态字典
        """
        return {
            'futu_trade_available': FUTU_TRADE_AVAILABLE,
            'is_connected': self.is_trade_connected,
            'is_unlocked': self.is_unlocked,
            'is_ready': self.is_trade_ready()
        }
