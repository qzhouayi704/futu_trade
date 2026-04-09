#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
监控任务管理器

职责：
- 监控任务的 CRUD 操作（创建、取消、查询）
- 监控任务数据库表初始化
- 活跃任务缓存管理
- 监控摘要统计
"""

import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

from ...database.core.db_manager import DatabaseManager
from ...config.config import Config
from ...core.models import StockInfo


@dataclass
class MonitorTask:
    """监控任务"""
    id: int
    stock_code: str
    stock_name: str
    direction: str  # BUY / SELL
    target_price: float
    quantity: int
    stop_loss_price: Optional[float]
    status: str  # ACTIVE / TRIGGERED / EXECUTED / CANCELLED / FAILED
    triggered_at: Optional[str]
    executed_at: Optional[str]
    created_at: str
    error_msg: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'direction': self.direction,
            'target_price': self.target_price,
            'quantity': self.quantity,
            'stop_loss_price': self.stop_loss_price,
            'status': self.status,
            'triggered_at': self.triggered_at,
            'executed_at': self.executed_at,
            'created_at': self.created_at,
            'error_msg': self.error_msg
        }


class MonitorTaskManager:
    """
    监控任务管理器

    功能：
    1. 管理监控任务（添加、删除、查询）
    2. 维护活跃任务缓存
    3. 提供监控摘要统计
    """

    def __init__(self, db_manager: DatabaseManager, config: Config):
        self.db_manager = db_manager
        self.config = config

        # 初始化数据库表
        self._init_monitor_tables()

        # 活跃任务缓存
        self._active_tasks: Dict[int, MonitorTask] = {}
        self._load_active_tasks()

        logging.info("监控任务管理器初始化完成")

    @property
    def active_tasks(self) -> Dict[int, MonitorTask]:
        """获取活跃任务缓存（供 PriceChecker 使用）"""
        return self._active_tasks

    def _init_monitor_tables(self):
        """初始化监控任务数据库表"""
        try:
            self.db_manager.execute_update('''
                CREATE TABLE IF NOT EXISTS monitor_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL,
                    stock_name TEXT,
                    direction TEXT NOT NULL,
                    target_price REAL NOT NULL,
                    quantity INTEGER NOT NULL,
                    stop_loss_price REAL,
                    status TEXT DEFAULT 'ACTIVE',
                    triggered_at TIMESTAMP,
                    executed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    error_msg TEXT
                )
            ''')

            self.db_manager.execute_update(
                'CREATE INDEX IF NOT EXISTS idx_monitor_tasks_status ON monitor_tasks(status)')
            self.db_manager.execute_update(
                'CREATE INDEX IF NOT EXISTS idx_monitor_tasks_stock_code ON monitor_tasks(stock_code)')

            logging.info("监控任务数据库表初始化完成")

        except Exception as e:
            logging.error(f"初始化监控任务数据库表失败: {e}")

    def _load_active_tasks(self):
        """加载活跃的监控任务"""
        try:
            rows = self.db_manager.execute_query('''
                SELECT id, stock_code, stock_name, direction, target_price,
                       quantity, stop_loss_price, status, triggered_at,
                       executed_at, created_at, error_msg
                FROM monitor_tasks
                WHERE status = 'ACTIVE'
            ''')

            self._active_tasks = {}
            for row in rows:
                task = MonitorTask(
                    id=row[0], stock_code=row[1], stock_name=row[2],
                    direction=row[3], target_price=row[4], quantity=row[5],
                    stop_loss_price=row[6], status=row[7], triggered_at=row[8],
                    executed_at=row[9], created_at=row[10], error_msg=row[11]
                )
                self._active_tasks[task.id] = task

            logging.info(f"加载了 {len(self._active_tasks)} 个活跃监控任务")

        except Exception as e:
            logging.error(f"加载活跃监控任务失败: {e}")

    def add_task(self, stock: StockInfo, direction: str,
                 target_price: float, quantity: int,
                 stop_loss_price: Optional[float] = None) -> Dict[str, Any]:
        """添加监控任务"""
        result = {'success': False, 'message': '', 'task_id': None}

        if not stock.code or direction not in ['BUY', 'SELL']:
            result['message'] = "无效的股票代码或交易方向"
            return result

        if target_price <= 0:
            result['message'] = "目标价格必须大于0"
            return result

        if quantity <= 0 or quantity % 100 != 0:
            result['message'] = "数量必须是100的正整数倍"
            return result

        try:
            task_id = self.db_manager.execute_insert('''
                INSERT INTO monitor_tasks
                (stock_code, stock_name, direction, target_price, quantity, stop_loss_price, status)
                VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE')
            ''', (stock.code, stock.name, direction,
                  target_price, quantity, stop_loss_price))

            task = MonitorTask(
                id=task_id, stock_code=stock.code,
                stock_name=stock.name, direction=direction,
                target_price=target_price, quantity=quantity,
                stop_loss_price=stop_loss_price, status='ACTIVE',
                triggered_at=None, executed_at=None,
                created_at=datetime.now().isoformat()
            )
            self._active_tasks[task_id] = task

            result.update({
                'success': True,
                'message': f"监控任务添加成功: {direction} {stock.code} @ {target_price}",
                'task_id': task_id,
                'task': task.to_dict()
            })

            logging.info(f"添加监控任务: {direction} {stock.code} @ {target_price}, 数量: {quantity}")

        except Exception as e:
            logging.error(f"添加监控任务失败: {e}")
            result['message'] = f"添加失败: {str(e)}"

        return result

    def cancel_task(self, task_id: int) -> Dict[str, Any]:
        """取消监控任务"""
        result = {'success': False, 'message': ''}

        try:
            if task_id not in self._active_tasks:
                result['message'] = "任务不存在或已不是活跃状态"
                return result

            self.db_manager.execute_update('''
                UPDATE monitor_tasks SET status = 'CANCELLED' WHERE id = ?
            ''', (task_id,))

            task = self._active_tasks.pop(task_id, None)

            result.update({
                'success': True,
                'message': f"监控任务已取消: {task.stock_code if task else task_id}"
            })

            logging.info(f"取消监控任务: {task_id}")

        except Exception as e:
            logging.error(f"取消监控任务失败: {e}")
            result['message'] = f"取消失败: {str(e)}"

        return result

    @staticmethod
    def _row_to_dict(row) -> Dict[str, Any]:
        """将数据库行转换为字典"""
        return {
            'id': row[0], 'stock_code': row[1],
            'stock_name': row[2], 'direction': row[3],
            'target_price': row[4], 'quantity': row[5],
            'stop_loss_price': row[6], 'status': row[7],
            'triggered_at': row[8], 'executed_at': row[9],
            'created_at': row[10], 'error_msg': row[11]
        }

    def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        """获取单个任务详情"""
        try:
            rows = self.db_manager.execute_query('''
                SELECT id, stock_code, stock_name, direction, target_price,
                       quantity, stop_loss_price, status, triggered_at,
                       executed_at, created_at, error_msg
                FROM monitor_tasks WHERE id = ?
            ''', (task_id,))
            return self._row_to_dict(rows[0]) if rows else None
        except Exception as e:
            logging.error(f"获取监控任务失败: {e}")
            return None

    def get_all_tasks(self, status: Optional[str] = None,
                      limit: int = 50) -> List[Dict[str, Any]]:
        """获取所有监控任务"""
        try:
            if status:
                rows = self.db_manager.execute_query('''
                    SELECT id, stock_code, stock_name, direction, target_price,
                           quantity, stop_loss_price, status, triggered_at,
                           executed_at, created_at, error_msg
                    FROM monitor_tasks WHERE status = ?
                    ORDER BY created_at DESC LIMIT ?
                ''', (status, limit))
            else:
                rows = self.db_manager.execute_query('''
                    SELECT id, stock_code, stock_name, direction, target_price,
                           quantity, stop_loss_price, status, triggered_at,
                           executed_at, created_at, error_msg
                    FROM monitor_tasks
                    ORDER BY created_at DESC LIMIT ?
                ''', (limit,))
            return [self._row_to_dict(row) for row in rows]

        except Exception as e:
            logging.error(f"获取监控任务列表失败: {e}")
            return []

    def get_active_tasks(self) -> List[Dict[str, Any]]:
        """获取活跃的监控任务"""
        return [task.to_dict() for task in self._active_tasks.values()]

    def get_monitor_summary(self) -> Dict[str, Any]:
        """获取监控摘要"""
        try:
            stats = self.db_manager.execute_query('''
                SELECT status, COUNT(*) FROM monitor_tasks GROUP BY status
            ''')

            status_counts = {row[0]: row[1] for row in stats}

            return {
                'active': status_counts.get('ACTIVE', 0),
                'triggered': status_counts.get('TRIGGERED', 0),
                'executed': status_counts.get('EXECUTED', 0),
                'cancelled': status_counts.get('CANCELLED', 0),
                'failed': status_counts.get('FAILED', 0),
                'total': sum(status_counts.values()),
                'active_tasks': self.get_active_tasks()
            }

        except Exception as e:
            logging.error(f"获取监控摘要失败: {e}")
            return {
                'active': 0, 'triggered': 0, 'executed': 0,
                'cancelled': 0, 'failed': 0, 'total': 0,
                'active_tasks': []
            }
