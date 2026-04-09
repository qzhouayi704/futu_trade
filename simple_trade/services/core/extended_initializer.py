#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
扩展初始化服务
负责K线和热门股的初始化协调
"""

import logging
import time
from typing import Dict, Any, Callable
from ...database.core.db_manager import DatabaseManager
from ...api.futu_client import FutuClient
from ...config.config import Config


class ExtendedInitializer:
    """
    扩展初始化器

    职责：
    1. 协调K线数据初始化
    2. 协调热门股数据初始化
    """

    def __init__(self, db_manager: DatabaseManager, futu_client: FutuClient, config: Config = None, hot_stock_service=None):
        self.db_manager = db_manager
        self.futu_client = futu_client
        self.config = config
        self.logger = logging.getLogger(__name__)

        # 延迟初始化的服务
        self._kline_service = None
        self._hot_stock_service = hot_stock_service  # 从外部注入

    def _get_kline_service(self):
        """延迟获取K线服务实例"""
        if self._kline_service is None and self.config:
            from ..market_data.kline import KlineDataService
            self._kline_service = KlineDataService(
                self.db_manager,
                self.futu_client,
                self.config
            )
        return self._kline_service

    def _get_hot_stock_service(self):
        """延迟获取热门股服务实例"""
        # 如果已经从外部注入，直接返回
        if self._hot_stock_service is not None:
            return self._hot_stock_service

        # 否则创建新实例（向后兼容，但会警告）
        self.logger.warning("HotStockCoordinator 未从外部注入，正在创建临时实例（quote_service=None）")
        from ..market_data.hot_stock import HotStockCoordinator
        self._hot_stock_service = HotStockCoordinator(
            self.db_manager,
            self.futu_client,
            self.config,
            None
        )
        return self._hot_stock_service

    def initialize_kline(self, progress_callback: Callable = None) -> Dict[str, Any]:
        """初始化K线数据"""
        try:
            kline_service = self._get_kline_service()
            if not kline_service:
                return {'success': False, 'message': 'K线服务不可用（缺少配置）', 'errors': ['K线服务未初始化']}
            return kline_service.initialize_kline_for_all_stocks(progress_callback=progress_callback)
        except Exception as e:
            self.logger.error(f"K线初始化异常: {e}")
            return {'success': False, 'message': f'K线初始化异常: {str(e)}', 'errors': [str(e)]}

    def get_kline_progress(self) -> Dict[str, Any]:
        """获取K线初始化进度"""
        kline_service = self._get_kline_service()
        if kline_service:
            return kline_service.get_init_progress()
        return {
            'is_running': False,
            'total_stocks': 0,
            'processed_stocks': 0,
            'current_stock': '',
            'progress_percent': 0,
            'errors_count': 0
        }

    def initialize_hot_stocks(self, force_update: bool = False, progress_callback: Callable = None) -> Dict[str, Any]:
        """初始化热门股票数据"""
        try:
            hot_stock_service = self._get_hot_stock_service()
            if not hot_stock_service:
                return {'success': False, 'message': '热门股服务不可用', 'errors': ['热门股服务未初始化']}

            if not force_update and hot_stock_service.has_heat_data():
                status = hot_stock_service.get_heat_status()
                return {
                    'success': True,
                    'message': f'热门股数据已存在，共{status["hot_stock_count"]}只热门股',
                    'hot_count': status['hot_stock_count'],
                    'skipped': True
                }

            return hot_stock_service.analyze_hot_stocks(
                progress_callback=progress_callback,
                force_update=force_update
            )
        except Exception as e:
            self.logger.error(f"热门股初始化异常: {e}")
            return {'success': False, 'message': f'热门股初始化异常: {str(e)}', 'errors': [str(e)]}

    def get_hot_stock_status(self) -> Dict[str, Any]:
        """获取热门股状态"""
        hot_stock_service = self._get_hot_stock_service()
        if hot_stock_service:
            return hot_stock_service.get_heat_status()
        return {
            'has_data': False,
            'hot_stock_count': 0,
            'total_stock_count': 0,
            'last_update': None,
            'is_analyzing': False
        }

    def get_plate_overview(self):
        """获取板块概览"""
        hot_stock_service = self._get_hot_stock_service()
        if hot_stock_service:
            return hot_stock_service.get_plate_overview()
        return []

    def initialize_with_kline(
        self,
        base_initializer,
        force_refresh: bool = False,
        timeout_seconds: int = 600,
        progress_callback: Callable = None
    ) -> Dict[str, Any]:
        """完整初始化：板块股票 + K线数据"""
        result = {'success': False, 'message': '', 'plate_init': {}, 'kline_init': {}, 'total_time': 0, 'errors': []}
        start_time = time.time()

        try:
            # 初始化板块和股票
            self.logger.info("步骤1: 初始化板块和股票...")
            if progress_callback:
                progress_callback(0, 100, '', '正在初始化板块和股票数据...')

            plate_result = base_initializer.initialize(force_refresh=force_refresh, timeout_seconds=timeout_seconds)
            result['plate_init'] = plate_result

            if not plate_result['success']:
                result['message'] = f"板块初始化失败: {plate_result['message']}"
                result['errors'].extend(plate_result.get('errors', []))
                return result

            # 检查是否需要初始化K线
            auto_init_kline = getattr(self.config, 'auto_init_kline', True) if self.config else True

            if not auto_init_kline:
                result.update({
                    'success': True,
                    'message': f"初始化完成（K线初始化已禁用）: {plate_result['message']}",
                    'total_time': round(time.time() - start_time, 2)
                })
                return result

            # 初始化K线数据
            kline_service = self._get_kline_service()
            if not kline_service:
                result.update({
                    'success': True,
                    'message': f"初始化完成（K线服务不可用）: {plate_result['message']}",
                    'total_time': round(time.time() - start_time, 2)
                })
                return result

            if progress_callback:
                progress_callback(50, 100, '', '正在初始化K线数据...')

            kline_result = kline_service.initialize_kline_for_all_stocks(progress_callback=progress_callback)
            result['kline_init'] = kline_result

            if kline_result.get('errors'):
                result['errors'].extend(kline_result['errors'])

            result.update({
                'success': True,
                'message': (
                    f"完整初始化完成: "
                    f"板块{plate_result['plates_target']}个, "
                    f"股票{plate_result['stocks_unique']}只, "
                    f"K线{kline_result.get('kline_records', 0)}条"
                ),
                'total_time': round(time.time() - start_time, 2)
            })

        except Exception as e:
            self.logger.error(f"完整初始化异常: {e}")
            result.update({
                'success': False,
                'message': f'完整初始化异常: {str(e)}',
                'total_time': round(time.time() - start_time, 2)
            })
            result['errors'].append(str(e))

        return result
