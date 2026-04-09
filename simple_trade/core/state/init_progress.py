#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
初始化进度管理器

从 StateManager 提取的初始化进度领域状态，
负责管理系统初始化过程中的进度追踪。
"""

import logging
import threading
from datetime import datetime
from typing import Dict, Any, Optional


class InitProgress:
    """初始化进度管理器 - 管理系统初始化进度"""

    def __init__(self):
        self._lock = threading.RLock()
        self._init_progress: Dict[str, Any] = {
            'is_running': False,
            'current_step': 0,
            'total_steps': 0,
            'current_action': '',
            'progress_percentage': 0,
            'completed': False,
            'error': None,
            'start_time': None,
            'end_time': None
        }

    def get_init_progress(self) -> Dict[str, Any]:
        """获取初始化进度"""
        with self._lock:
            return self._init_progress.copy()

    def start_init_progress(self, total_steps: int = 0):
        """开始初始化进度"""
        with self._lock:
            self._init_progress.update({
                'is_running': True,
                'current_step': 0,
                'total_steps': total_steps,
                'current_action': '准备初始化...',
                'progress_percentage': 0,
                'completed': False,
                'error': None,
                'start_time': datetime.now().isoformat(),
                'end_time': None
            })

    def update_init_progress(
        self,
        step: Optional[int] = None,
        action: Optional[str] = None,
        total: Optional[int] = None,
        error: Optional[str] = None
    ):
        """更新初始化进度"""
        with self._lock:
            if step is not None:
                self._init_progress['current_step'] = step
            if action is not None:
                self._init_progress['current_action'] = action
            if total is not None:
                self._init_progress['total_steps'] = total
            if error is not None:
                self._init_progress['error'] = error

            # 计算进度百分比
            if self._init_progress['total_steps'] > 0:
                self._init_progress['progress_percentage'] = min(100, int(
                    (self._init_progress['current_step'] /
                     self._init_progress['total_steps']) * 100
                ))

        if action:
            logging.info(
                f"初始化进度: {self._init_progress['progress_percentage']}% - {action}"
            )

    def finish_init_progress(self, success: bool = True, error: Optional[str] = None):
        """完成初始化进度"""
        with self._lock:
            self._init_progress.update({
                'is_running': False,
                'completed': True,
                'progress_percentage': (
                    100 if success
                    else self._init_progress['progress_percentage']
                ),
                'end_time': datetime.now().isoformat(),
                'error': error if not success else None,
                'current_action': (
                    '初始化完成' if success
                    else f'初始化失败: {error}'
                )
            })

    def reset(self):
        """重置初始化进度状态"""
        with self._lock:
            self._init_progress = {
                'is_running': False,
                'current_step': 0,
                'total_steps': 0,
                'current_action': '',
                'progress_percentage': 0,
                'completed': False,
                'error': None,
                'start_time': None,
                'end_time': None
            }
