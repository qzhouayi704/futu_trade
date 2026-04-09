#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分仓止盈服务（协调器）

组合 LotTaskManager 和 LotPriceMonitor，提供统一接口
"""

import logging
import threading
from typing import Dict, List, Any, Optional

from ....database.core.db_manager import DatabaseManager
from .lot_models import PositionLot
from .lot_task_manager import LotTaskManager
from .lot_price_monitor import LotPriceMonitor


class LotTakeProfitService:
    """分仓止盈服务（协调器）"""

    def __init__(self, db_manager: DatabaseManager, futu_trade_service=None):
        self.db_manager = db_manager
        self.futu_trade_service = futu_trade_service
        self._lock = threading.Lock()

        # 初始化子模块
        self.task_manager = LotTaskManager(db_manager, futu_trade_service)
        self.price_monitor = LotPriceMonitor(db_manager, futu_trade_service)

        # 加载活跃任务
        self._active_tasks = self.task_manager.load_active_tasks()
        logging.info("分仓止盈服务初始化完成")

    # ==================== 仓位还原（委托给 task_manager） ====================

    def get_position_lots(self, stock_code: str) -> List[PositionLot]:
        """从富途API历史成交记录还原各仓位（FIFO算法）"""
        return self.task_manager.get_position_lots(stock_code)

    # ==================== 任务管理（委托给 task_manager） ====================

    def create_task(self, stock_code: str, take_profit_pct: float) -> Dict[str, Any]:
        """创建分仓止盈任务"""
        with self._lock:
            result = self.task_manager.create_task(stock_code, take_profit_pct, self._active_tasks)
            if result.get('success') and 'task_obj' in result:
                self._active_tasks[stock_code] = result['task_obj']
                result.pop('task_obj')  # 移除内部对象，只返回字典
            return result

    def cancel_task(self, stock_code: str) -> Dict[str, Any]:
        """取消止盈任务"""
        task = self._active_tasks.get(stock_code)
        if not task:
            return {'success': False, 'message': f'{stock_code} 没有活跃的止盈任务'}

        with self._lock:
            result = self.task_manager.cancel_task(task)
            if result.get('success'):
                self._active_tasks.pop(stock_code, None)
            return result

    def get_task_detail(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """获取任务详情（含执行记录）"""
        return self.task_manager.get_task_detail(stock_code)

    def get_all_tasks(self) -> List[Dict[str, Any]]:
        """获取所有止盈任务"""
        return self.task_manager.get_all_tasks()

    # ==================== 价格监控（委托给 price_monitor） ====================

    def check_prices(self, quotes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """检查实时报价是否触发止盈卖出"""
        return self.price_monitor.check_prices(quotes, self._active_tasks)
