#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
订阅版本管理服务

职责：
1. 计算股票池版本标识
2. 检查订阅状态和版本变更
3. 管理订阅初始化流程
"""

import logging
import hashlib
from datetime import datetime
from typing import Dict, Any


class SubscriptionVersionService:
    """
    订阅版本管理服务

    负责管理股票池版本和订阅状态
    """

    def __init__(self, db_manager):
        """
        初始化订阅版本管理服务

        Args:
            db_manager: 数据库管理器
        """
        self.db_manager = db_manager
        self.logger = logging.getLogger(__name__)

        # 当前订阅状态
        self.current_version = None
        self.is_initialized = False

    def calculate_stock_pool_version(self) -> str:
        """计算当前股票池的版本标识

        Returns:
            str: 版本哈希值（16位）
        """
        try:
            # 获取所有目标板块和活跃股票的组合信息
            # 包含 is_enabled 字段，这样禁用板块时版本会变化
            rows = self.db_manager.execute_query('''
                SELECT p.plate_code, p.is_target, p.is_enabled, s.code
                FROM plates p
                LEFT JOIN stock_plates sp ON p.id = sp.plate_id
                LEFT JOIN stocks s ON sp.stock_id = s.id
                ORDER BY p.plate_code, s.code
            ''')

            # 构建版本字符串，包含 is_enabled 状态
            version_data = []
            for row in rows:
                plate_code = row[0]
                is_target = row[1]
                is_enabled = row[2]
                stock_code = row[3] if row[3] else ''
                version_data.append(f"{plate_code}:{is_target}:{is_enabled}:{stock_code}")

            # 计算哈希值作为版本标识
            version_string = '|'.join(version_data)
            version_hash = hashlib.md5(version_string.encode('utf-8')).hexdigest()[:16]

            self.logger.debug(f"计算股票池版本: {version_hash}")
            return version_hash

        except Exception as e:
            self.logger.error(f"计算股票池版本失败: {e}")
            # 使用时间戳作为备用版本
            return datetime.now().strftime('%Y%m%d%H%M%S')

    def check_subscription_status(self) -> Dict[str, Any]:
        """检查订阅状态和股票池变更

        Returns:
            Dict: 订阅状态信息
        """
        status = {
            'subscription_valid': False,
            'version_changed': False,
            'current_version': '',
            'subscribed_version': '',
            'need_restart': False,
            'message': ''
        }

        try:
            # 计算当前股票池版本
            current_version = self.calculate_stock_pool_version()
            status['current_version'] = current_version
            status['subscribed_version'] = self.current_version or ''

            # 检查是否已初始化订阅
            if not self.is_initialized:
                status.update({
                    'subscription_valid': False,
                    'need_restart': True,
                    'message': '订阅未初始化，需要重启系统'
                })
                return status

            # 检查版本是否变化
            if self.current_version != current_version:
                status.update({
                    'subscription_valid': False,
                    'version_changed': True,
                    'need_restart': True,
                    'message': (
                        f'��票池已变更（{self.current_version} → {current_version}），'
                        f'建议重启系统以更新订阅'
                    )
                })

                # 设置需要重新订阅的标记
                self.set_resubscribe_flag(True)

                self.logger.warning(
                    f"检测到股票池变更: {self.current_version} → {current_version}"
                )
            else:
                status.update({
                    'subscription_valid': True,
                    'version_changed': False,
                    'need_restart': False,
                    'message': '订阅状态正常'
                })

        except Exception as e:
            self.logger.error(f"检查订阅状态失败: {e}")
            status.update({
                'subscription_valid': False,
                'message': f'检查订阅状态异常: {str(e)}'
            })

        return status

    def mark_initialized(self, version: str, subscribed_count: int):
        """标记订阅已初始化

        Args:
            version: 订阅的版本
            subscribed_count: 订阅的股票数量
        """
        self.current_version = version
        self.is_initialized = True
        self.save_subscription_version(version)

        self.logger.info(
            f"订阅初始化完成: {subscribed_count}只股票，版本: {version}"
        )

    def save_subscription_version(self, version: str):
        """保存订阅版本到数据库

        Args:
            version: 版本标识
        """
        try:
            self.db_manager.system_queries.set_system_config(
                'subscription_version',
                version,
                '当前订阅的股票池版本'
            )
            self.logger.debug(f"保存订阅版本: {version}")
        except Exception as e:
            self.logger.error(f"保存订阅版本失败: {e}")

    def set_resubscribe_flag(self, need_resubscribe: bool):
        """设置重新订阅标记

        Args:
            need_resubscribe: 是否需要重新订阅
        """
        try:
            self.db_manager.system_queries.set_system_config(
                'need_resubscribe',
                'true' if need_resubscribe else 'false',
                '是否需要重新订阅股票'
            )
            self.logger.debug(f"设置重新订阅标记: {need_resubscribe}")
        except Exception as e:
            self.logger.error(f"设置重新订阅标记失败: {e}")

    def get_resubscribe_flag(self) -> bool:
        """获取重新订阅标记

        Returns:
            bool: 是否需要重新订阅
        """
        try:
            flag = self.db_manager.system_queries.get_system_config('need_resubscribe')
            return flag == 'true'
        except Exception as e:
            self.logger.error(f"获取重新订阅标记失败: {e}")
            return False

    def should_reinitialize(self) -> bool:
        """检查是否需要重新初始化订阅

        Returns:
            bool: 是否需要重新初始化
        """
        if not self.is_initialized:
            return True

        current_version = self.calculate_stock_pool_version()
        return self.current_version != current_version
