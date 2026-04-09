#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票池服务 - 协调器
整合查询服务和管理服务，提供统一的股票池接口
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from ...database.core.db_manager import DatabaseManager
from ...config.config import Config
from ...api.futu_client import FutuClient
from ...core.state import get_state_manager
from .stock_pool_query import StockPoolQueryService
from .stock_pool_manager import StockPoolManagerService


# ==================== 兼容函数（代理到 StateManager）====================

def get_global_stock_pool():
    """获取全局股票池数据"""
    return get_state_manager().get_stock_pool()


def set_global_stock_pool(plates, stocks):
    """设置全局股票池数据"""
    get_state_manager().set_stock_pool(plates, stocks)


def get_active_stocks_from_pool(limit: int = None):
    """从全局股票池获取活跃股票

    Returns:
        List[Tuple]: 股票数据列表，格式为 (id, code, name, market, plate_name)
    """
    return get_state_manager().get_active_stocks(limit)


def get_initialization_progress():
    """获取初始化进度状态"""
    return get_state_manager().get_init_progress()


def update_initialization_progress(current_step: int = None, current_action: str = None,
                                 total_steps: int = None, error: str = None):
    """更新初始化进度"""
    get_state_manager().update_init_progress(
        step=current_step,
        action=current_action,
        total=total_steps,
        error=error
    )


def start_initialization():
    """开始初始化，重置进度状态"""
    get_state_manager().start_init_progress(total_steps=10)


def finish_initialization(success: bool = True, error_message: str = None):
    """完成初始化，更新最终状态"""
    get_state_manager().finish_init_progress(success=success, error=error_message)


def refresh_global_stock_pool_from_db(db_manager: DatabaseManager):
    """从数据库刷新全局股票池数据 - 兼容函数"""
    query_service = StockPoolQueryService(db_manager)
    query_service.refresh_from_database()


def clear_stock_pool_database(db_manager: DatabaseManager):
    """清空股票池数据库 - 兼容函数"""
    from ...api.futu_client import FutuClient
    futu_client = FutuClient()
    manager_service = StockPoolManagerService(db_manager, futu_client)
    result = manager_service.clear_database()

    if result['success']:
        # 重置状态管理器中的股票池数据
        state_manager = get_state_manager()
        state_manager.set_stock_pool([], [])


class StockPoolService:
    """股票池服务 - 协调器，整合查询和管理功能"""

    def __init__(self, db_manager: DatabaseManager, futu_client: FutuClient, config: Config):
        self.db_manager = db_manager
        self.futu_client = futu_client
        self.config = config
        self.state_manager = get_state_manager()
        self.logger = logging.getLogger(__name__)

        # 初始化子服务
        self.query_service = StockPoolQueryService(db_manager)
        self.manager_service = StockPoolManagerService(db_manager, futu_client)

    # ==================== 初始化相关 ====================

    def init_stock_pool(self, force_refresh: bool = False) -> Dict[str, Any]:
        """股票池初始化"""

        pool = self.state_manager.get_stock_pool()
        if not force_refresh and pool['initialized']:
            return {
                'success': True,
                'message': '使用已有股票池数据',
                'plates_count': len(pool['plates']),
                'stocks_count': len(pool['stocks'])
            }

        try:
            self.logger.info("开始初始化股票池...")

            if force_refresh:
                self.logger.info("强制刷新模式，清空现有数据库...")
                self.manager_service.clear_database()
                self.state_manager.set_stock_pool([], [])

            # 从数据库加载数据
            self.query_service.refresh_from_database()
            pool = self.state_manager.get_stock_pool()

            if pool['initialized'] and len(pool['stocks']) > 0 and not force_refresh:
                self.logger.info(f"从数据库加载股票池完成: {len(pool['plates'])}个板块，{len(pool['stocks'])}只股票")
                return {
                    'success': True,
                    'message': '从数据库加载股票池完成',
                    'plates_count': len(pool['plates']),
                    'stocks_count': len(pool['stocks'])
                }

            # 使用 DataInitializer
            self.logger.info("使用DataInitializer进行初始化...")
            from .data_initializer import DataInitializer
            data_initializer = DataInitializer(self.db_manager, self.futu_client)

            init_result = data_initializer.initialize(force_refresh=force_refresh)

            if init_result['success']:
                self.query_service.refresh_from_database()
                pool = self.state_manager.get_stock_pool()

                return {
                    'success': True,
                    'message': f'股票池初始化成功: {init_result["message"]}',
                    'plates_count': len(pool['plates']),
                    'stocks_count': len(pool['stocks'])
                }
            else:
                # 使用默认数据
                default_result = self.manager_service.init_with_default_data()
                if default_result['success']:
                    self.query_service.refresh_from_database()
                    pool = self.state_manager.get_stock_pool()
                    return {
                        'success': True,
                        'message': '使用默认数据初始化完成',
                        'plates_count': len(pool['plates']),
                        'stocks_count': len(pool['stocks'])
                    }
                else:
                    return {
                        'success': False,
                        'message': f'初始化失败: {init_result.get("message", "未知错误")}',
                        'plates_count': 0,
                        'stocks_count': 0
                    }

        except Exception as e:
            self.logger.error(f"股票池初始化失败: {e}")
            self.state_manager.finish_init_progress(success=False, error=str(e))
            return {
                'success': False,
                'message': f'初始化失败: {str(e)}',
                'plates_count': 0,
                'stocks_count': 0
            }

    def refresh_stock_pool(self) -> Dict[str, Any]:
        """增量更新股票池数据（不删除现有数据）"""
        try:
            self.logger.info("开始增量更新股票池...")

            # 使用 DataInitializer，但不强制刷新
            from .data_initializer import DataInitializer
            data_initializer = DataInitializer(self.db_manager, self.futu_client)

            # force_refresh=False 确保不会清空数据
            init_result = data_initializer.initialize(force_refresh=False)

            if init_result['success']:
                self.query_service.refresh_from_database()
                pool = self.state_manager.get_stock_pool()

                return {
                    'success': True,
                    'message': f'数据更新成功: {init_result["message"]}',
                    'plates_added': init_result.get('plates_target', 0),
                    'stocks_added': init_result.get('stocks_unique', 0),
                    'plates_count': len(pool['plates']),
                    'stocks_count': len(pool['stocks'])
                }
            else:
                return {
                    'success': False,
                    'message': f'更新失败: {init_result.get("message", "未知错误")}'
                }

        except Exception as e:
            self.logger.error(f"股票池更新失败: {e}")
            return {
                'success': False,
                'message': f'更新失败: {str(e)}'
            }

    # ==================== 查询相关（代理到查询服务）====================

    def get_stock_pool(self) -> Dict[str, Any]:
        """获取股票池数据"""
        return self.query_service.get_stock_pool()

    def get_active_stocks(self, limit: int = None) -> List[Tuple]:
        """获取活跃股票"""
        return self.query_service.get_active_stocks(limit)

    def get_plates(self, is_target: bool = None, is_enabled: bool = None) -> List[Dict[str, Any]]:
        """查询板块列表"""
        return self.query_service.get_plates(is_target, is_enabled)

    def get_plate_by_id(self, plate_id: int) -> Optional[Dict[str, Any]]:
        """根据ID查询板块"""
        return self.query_service.get_plate_by_id(plate_id)

    def get_plate_by_code(self, plate_code: str) -> Optional[Dict[str, Any]]:
        """根据代码查询板块"""
        return self.query_service.get_plate_by_code(plate_code)

    def get_stocks_by_plate(self, plate_id: int) -> List[Dict[str, Any]]:
        """查询板块的股票"""
        return self.query_service.get_stocks_by_plate(plate_id)

    def get_stock_by_id(self, stock_id: int) -> Optional[Dict[str, Any]]:
        """根据ID查询股票"""
        return self.query_service.get_stock_by_id(stock_id)

    def get_stock_by_code(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """根据代码查询股票"""
        return self.query_service.get_stock_by_code(stock_code)

    def get_all_target_stocks(self) -> List[Dict[str, Any]]:
        """获取所有目标股票"""
        return self.query_service.get_all_target_stocks()

    # ==================== 管理相关（代理到管理服务）====================

    def add_plate(self, plate_code: str) -> Dict[str, Any]:
        """添加板块"""
        result = self.manager_service.add_plate(plate_code)
        if result['success']:
            self.query_service.refresh_from_database()
        return result

    def remove_plate(self, plate_id: int) -> Dict[str, Any]:
        """删除板块"""
        result = self.manager_service.remove_plate(plate_id)
        if result['success']:
            self.query_service.refresh_from_database()
        return result

    def add_stocks(self, stock_codes: List[str], plate_id: int = None) -> Dict[str, Any]:
        """添加股票"""
        result = self.manager_service.add_stocks(stock_codes, plate_id)
        if result['success']:
            self.query_service.refresh_from_database()
        return result

    def remove_stock(self, stock_id: int) -> Dict[str, Any]:
        """删除股票"""
        result = self.manager_service.remove_stock(stock_id)
        if result['success']:
            self.query_service.refresh_from_database()
        return result

    def clear_database(self) -> Dict[str, Any]:
        """清空数据库"""
        result = self.manager_service.clear_database()
        if result['success']:
            self.state_manager.set_stock_pool([], [])
        return result
