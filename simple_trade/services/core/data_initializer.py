#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据初始化服务 - 精简版
协调板块和股票的初始化流程
"""

import logging
import time
from typing import Dict, Any, List, Callable
from ...database.core.db_manager import DatabaseManager
from ...api.futu_client import FutuClient
from ...config.config import Config
from ..market_data.plate.plate_initializer import PlateInitializerService
from .stock_initializer import StockInitializerService
from ..core import DefaultDataProvider
from .extended_initializer import ExtendedInitializer
from .initialization_helper import InitializationHelper


class DataInitializer:
    """
    数据初始化器 - 协调器模式

    职责：
    1. 协调板块和股票初始化流程
    2. 管理数据库表结构
    3. 检查和维护初始化状态
    4. 提供查询接口（委托给子服务）
    """

    def __init__(self, db_manager: DatabaseManager, futu_client: FutuClient, config: Config = None):
        self.db_manager = db_manager
        self.futu_client = futu_client
        self.config = config
        self.logger = logging.getLogger(__name__)

        # 注入子服务
        self.plate_service = PlateInitializerService(db_manager, futu_client)
        self.stock_service = StockInitializerService(db_manager, futu_client)
        self.default_provider = DefaultDataProvider(db_manager)
        self.extended_initializer = ExtendedInitializer(db_manager, futu_client, config)
        self.helper = InitializationHelper(db_manager)

    def initialize(self, force_refresh: bool = False, timeout_seconds: int = 600) -> Dict[str, Any]:
        """
        统一的数据初始化入口

        Args:
            force_refresh: 是否强制刷新数据
            timeout_seconds: 超时时间（秒）

        Returns:
            Dict: 初始化结果
        """
        start_time = time.time()
        self.logger.info(f"开始数据初始化... (超时限制: {timeout_seconds}秒, 强制刷新: {force_refresh})")

        result = self.helper.create_result_template()

        def check_timeout(step_name: str):
            elapsed = time.time() - start_time
            result['step_times'][step_name] = round(elapsed, 2)
            if elapsed > timeout_seconds:
                self.helper.handle_timeout(result, step_name, elapsed, timeout_seconds)
                raise TimeoutError()

        try:
            # 步骤1: 确保数据库表存在
            check_timeout('开始检查')
            if not self.helper.ensure_tables_exist():
                result['message'] = '数据库表创建失败'
                result['errors'].append('数据库表创建失败')
                return result
            check_timeout('数据库表检查完成')

            # 步骤2: 检查现有数据
            existing_data = self.helper.check_existing_data()
            check_timeout('现有数据检查完成')

            if not force_refresh and existing_data['has_data']:
                return self.helper.create_skip_result(existing_data, start_time)

            # 步骤3: 执行初始化
            if self.futu_client.is_available():
                check_timeout('开始从富途API初始化')
                init_result = self._initialize_from_futu()
                result.update(init_result)
                check_timeout('富途API初始化完成')
            else:
                check_timeout('开始默认数据初始化')
                init_result = self.default_provider.initialize_default_data(self.stock_service)
                result.update(init_result)
                check_timeout('默认数据初始化完成')

            # 步骤4: 更新最后初始化时间
            if result['success']:
                self.helper.update_last_init_time()
                check_timeout('更新初始化时间完成')

            result['total_time'] = round(time.time() - start_time, 2)
            self.logger.info(f"数据初始化完成 ({result['total_time']}s): {result['message']}")

        except TimeoutError:
            pass
        except Exception as e:
            self.logger.error(f"数据初始化异常: {e}")
            result.update({
                'success': False,
                'message': f'数据初始化异常: {str(e)}',
                'total_time': round(time.time() - start_time, 2)
            })
            result['errors'].append(str(e))

        return result

    def _initialize_from_futu(self) -> Dict[str, Any]:
        """从富途API初始化数据"""
        result = {
            'success': False,
            'message': '',
            'plates_total': 0,
            'plates_target': 0,
            'stocks_total': 0,
            'stocks_unique': 0,
            'errors': []
        }

        try:
            self.logger.info("从富途API获取数据...")

            # 获取并匹配所有市场的板块
            all_plates, target_plates = self.plate_service.fetch_and_match_all_markets()
            result['plates_total'] = len(all_plates)
            result['plates_target'] = len(target_plates)

            if not target_plates:
                result['message'] = '未匹配到任何目标板块'
                result['errors'].append('未匹配到目标板块')
                return result

            # 保存目标板块
            self.logger.info("保存目标板块到数据库...")
            saved_plates = self.plate_service.save_plates(target_plates)

            # 获取股票
            self.logger.info("获取目标板块股票...")
            all_stocks, stock_plate_map, total_count = self.stock_service.fetch_stocks_for_plates(saved_plates)

            result['stocks_total'] = total_count
            result['stocks_unique'] = len(all_stocks)

            # 保存股票和关联
            self.logger.info(f"保存 {len(all_stocks)} 只去重后的股票...")
            self.stock_service.save_stocks_with_relations(all_stocks, stock_plate_map)

            result.update({
                'success': True,
                'message': (
                    f'初始化成功: {result["plates_total"]}个板块, '
                    f'{result["plates_target"]}个目标板块, '
                    f'{result["stocks_unique"]}只股票(去重)'
                )
            })

        except Exception as e:
            self.logger.error(f"富途API初始化失败: {e}")
            result.update({
                'success': False,
                'message': f'富途API初始化失败: {str(e)}'
            })
            result['errors'].append(str(e))

        return result

    # ==================== 查询接口（委托给子服务） ====================

    def get_initialization_status(self) -> Dict[str, Any]:
        """获取初始化状态"""
        try:
            status = self.helper.check_existing_data()
            status['is_initialized'] = status['has_data']
            return status
        except Exception as e:
            self.logger.error(f"获取初始化状态失败: {e}")
            return {'is_initialized': False, 'error': str(e)}

    def get_target_stocks(self, distinct: bool = True) -> List[Dict[str, Any]]:
        """获取目标板块的股票列表（委托给stock_service）"""
        return self.stock_service.get_target_stocks(distinct)

    def get_stock_plates(self, stock_code: str) -> List[Dict[str, Any]]:
        """获取股票所属的所有板块（委托给stock_service）"""
        return self.stock_service.get_stock_plates(stock_code)

    # ==================== K线和热门股初始化（委托给ExtendedInitializer） ====================

    def initialize_with_kline(
        self,
        force_refresh: bool = False,
        timeout_seconds: int = 600,
        progress_callback: Callable = None
    ) -> Dict[str, Any]:
        """完整初始化：板块股票 + K线数据（委托给ExtendedInitializer）"""
        return self.extended_initializer.initialize_with_kline(
            self, force_refresh, timeout_seconds, progress_callback
        )

    def initialize_kline_only(self, progress_callback: Callable = None) -> Dict[str, Any]:
        """仅初始化K线数据（委托给ExtendedInitializer）"""
        return self.extended_initializer.initialize_kline(progress_callback)

    def get_kline_init_progress(self) -> Dict[str, Any]:
        """获取K线初始化进度（委托给ExtendedInitializer）"""
        return self.extended_initializer.get_kline_progress()

    def initialize_hot_stocks(self, force_update: bool = False, progress_callback: Callable = None) -> Dict[str, Any]:
        """初始化热门股票数据（委托给ExtendedInitializer）"""
        return self.extended_initializer.initialize_hot_stocks(force_update, progress_callback)

    def get_hot_stock_status(self) -> Dict[str, Any]:
        """获取热门股状态（委托给ExtendedInitializer）"""
        return self.extended_initializer.get_hot_stock_status()

    def get_plate_overview(self) -> List[Dict[str, Any]]:
        """获取板块概览（委托给ExtendedInitializer）"""
        return self.extended_initializer.get_plate_overview()

