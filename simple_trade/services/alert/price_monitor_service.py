#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
价格监控服务（兼容层）

将原有的单一服务拆分为：
- MonitorTaskManager: 监控任务的 CRUD 管理
- PriceChecker: 价格检查执行逻辑

本模块作为兼容层，保持原有 PriceMonitorService 接口不变，
内部委托给 MonitorTaskManager 和 PriceChecker。
"""

from typing import Dict, List, Any, Optional

from .monitor_task_manager import MonitorTask, MonitorTaskManager
from .price_checker import PriceChecker
from ...database.core.db_manager import DatabaseManager
from ...config.config import Config
from ...core.models import StockInfo


class PriceMonitorService:
    """
    价格监控服务（兼容层）

    保持原有接口不变，内部委托给：
    - MonitorTaskManager: 任务管理
    - PriceChecker: 价格检查与交易执行
    """

    def __init__(self, db_manager: DatabaseManager, config: Config,
                 futu_trade_service=None):
        self._task_manager = MonitorTaskManager(db_manager, config)
        self._price_checker = PriceChecker(
            db_manager=db_manager,
            active_tasks=self._task_manager.active_tasks,
            futu_trade_service=futu_trade_service
        )

    # ==================== 任务管理（委托给 MonitorTaskManager） ====================

    def add_task(self, stock: StockInfo, direction: str,
                 target_price: float, quantity: int,
                 stop_loss_price: Optional[float] = None) -> Dict[str, Any]:
        """添加监控任务"""
        return self._task_manager.add_task(
            stock, direction,
            target_price, quantity, stop_loss_price
        )

    def cancel_task(self, task_id: int) -> Dict[str, Any]:
        """取消监控任务"""
        return self._task_manager.cancel_task(task_id)

    def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        """获取单个任务详情"""
        return self._task_manager.get_task(task_id)

    def get_all_tasks(self, status: Optional[str] = None,
                      limit: int = 50) -> List[Dict[str, Any]]:
        """获取所有监控任务"""
        return self._task_manager.get_all_tasks(status, limit)

    def get_active_tasks(self) -> List[Dict[str, Any]]:
        """获取活跃的监控任务"""
        return self._task_manager.get_active_tasks()

    def get_monitor_summary(self) -> Dict[str, Any]:
        """获取监控摘要"""
        return self._task_manager.get_monitor_summary()

    # ==================== 价格检查（委托给 PriceChecker） ====================

    def check_prices(self, quotes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """检查价格是否达到目标，触发交易"""
        return self._price_checker.check_prices(quotes)
