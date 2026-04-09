#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
初始化辅助工具
提供初始化流程中的通用辅助方法
"""

import logging
import time
from typing import Dict, Any
from datetime import datetime
from ...database.core.db_manager import DatabaseManager
from ...database.models import DatabaseSchema


class InitializationHelper:
    """
    初始化辅助工具类

    职责：
    1. 创建结果模板
    2. 处理超时逻辑
    3. 创建跳过结果
    4. 确保数据库表存在
    5. 检查现有数据
    6. 更新初始化时间
    """

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def create_result_template() -> Dict[str, Any]:
        """创建结果模板"""
        return {
            'success': False,
            'message': '',
            'plates_total': 0,
            'plates_target': 0,
            'stocks_total': 0,
            'stocks_unique': 0,
            'errors': [],
            'step_times': {},
            'total_time': 0,
            'timeout': False
        }

    def handle_timeout(self, result: Dict, step_name: str, elapsed: float, timeout_seconds: int):
        """处理超时"""
        error_msg = f"步骤 '{step_name}' 超时 ({elapsed:.1f}s > {timeout_seconds}s)"
        self.logger.error(error_msg)
        result.update({
            'success': False,
            'message': error_msg,
            'timeout': True,
            'total_time': round(elapsed, 2)
        })
        result['errors'].append(error_msg)

    def create_skip_result(self, existing_data: Dict, start_time: float) -> Dict[str, Any]:
        """创建跳过初始化的结果"""
        self.logger.info(
            f"发现现有数据，跳过初始化: "
            f"{existing_data['plates_count']}个板块, "
            f"{existing_data['stocks_count']}只股票"
        )
        return {
            'success': True,
            'message': '使用现有数据，跳过初始化',
            'plates_total': existing_data['plates_count'],
            'plates_target': existing_data['target_plates_count'],
            'stocks_total': existing_data['stocks_count'],
            'stocks_unique': existing_data['stocks_count'],
            'errors': [],
            'step_times': {},
            'total_time': round(time.time() - start_time, 2),
            'timeout': False
        }

    def ensure_tables_exist(self) -> bool:
        """确保所有数据库表和索引存在"""
        try:
            self.logger.info("检查并创建数据库表...")
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                for table_sql in DatabaseSchema.get_all_tables():
                    cursor.execute(table_sql)
                for index_sql in DatabaseSchema.get_all_indexes():
                    cursor.execute(index_sql)
                conn.commit()
            self.logger.info("数据库表和索引检查完成")
            return True
        except Exception as e:
            self.logger.error(f"创建数据库表失败: {e}")
            return False

    def check_existing_data(self) -> Dict[str, Any]:
        """检查现有数据状态"""
        data_info = {
            'has_data': False,
            'plates_count': 0,
            'target_plates_count': 0,
            'stocks_count': 0,
            'stock_plate_relations': 0,
            'last_init_time': None
        }

        try:
            plates_result = self.db_manager.execute_query('SELECT COUNT(*) FROM plates')
            data_info['plates_count'] = plates_result[0][0] if plates_result else 0

            target_result = self.db_manager.execute_query('SELECT COUNT(*) FROM plates WHERE is_target = 1')
            data_info['target_plates_count'] = target_result[0][0] if target_result else 0

            stocks_result = self.db_manager.execute_query('SELECT COUNT(*) FROM stocks')
            data_info['stocks_count'] = stocks_result[0][0] if stocks_result else 0

            relations_result = self.db_manager.execute_query('SELECT COUNT(*) FROM stock_plates')
            data_info['stock_plate_relations'] = relations_result[0][0] if relations_result else 0

            last_init = self.db_manager.system_queries.get_system_config('last_data_init')
            if last_init:
                data_info['last_init_time'] = last_init

            data_info['has_data'] = (
                data_info['plates_count'] > 0 and
                data_info['target_plates_count'] > 0 and
                data_info['stocks_count'] > 0 and
                data_info['stock_plate_relations'] > 0
            )

            self.logger.info(
                f"现有数据检查: 板块{data_info['plates_count']}, "
                f"目标板块{data_info['target_plates_count']}, "
                f"股票{data_info['stocks_count']}, "
                f"关联{data_info['stock_plate_relations']}"
            )

        except Exception as e:
            self.logger.error(f"检查现有数据失败: {e}")

        return data_info

    def update_last_init_time(self):
        """更新最后初始化时间"""
        try:
            current_time = datetime.now().isoformat()
            self.db_manager.system_queries.set_system_config(
                'last_data_init',
                current_time,
                '最后一次数据初始化时间'
            )
            self.logger.info(f"更新最后初始化时间: {current_time}")
        except Exception as e:
            self.logger.error(f"更新最后初始化时间失败: {e}")
