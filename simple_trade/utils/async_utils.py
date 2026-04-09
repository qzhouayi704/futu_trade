#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
异步工具函数

提供统一的超时保护和任务管理，解决系统中 run_in_executor 无超时保护
和 fire-and-forget create_task 导致的稳定性问题。
"""

import asyncio
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# 默认超时值（秒）
DEFAULT_EXECUTOR_TIMEOUT = 10.0
DEFAULT_DB_TIMEOUT = 5.0
DEFAULT_AI_TIMEOUT = 30.0
DEFAULT_TRADE_TIMEOUT = 15.0


async def safe_run_in_executor(
    func: Callable,
    *args,
    timeout: float = DEFAULT_EXECUTOR_TIMEOUT,
    label: str = "",
) -> Any:
    """在线程池中执行同步函数，带超时保护。

    Args:
        func: 要执行的同步函数
        *args: 传递给 func 的参数
        timeout: 超时秒数，默认 10s
        label: 日志标签（用于超时告警）

    Returns:
        func 的返回值

    Raises:
        asyncio.TimeoutError: 超时时抛出（由调用方决定如何处理）
    """
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, func, *args),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        tag = f" [{label}]" if label else ""
        logger.warning(f"run_in_executor 超时{tag}（{timeout}s）")
        raise


async def safe_run_in_executor_quiet(
    func: Callable,
    *args,
    timeout: float = DEFAULT_EXECUTOR_TIMEOUT,
    label: str = "",
    default: Any = None,
) -> Any:
    """在线程池中执行同步函数，超时时返回默认值（不抛异常）。

    适用于非关键路径，超时时静默返回默认值。

    Args:
        func: 要执行的同步函数
        *args: 传递给 func 的参数
        timeout: 超时秒数
        label: 日志标签
        default: 超时或异常时的默认返回值

    Returns:
        func 的返回值，或超时/异常时的 default
    """
    try:
        return await safe_run_in_executor(func, *args, timeout=timeout, label=label)
    except asyncio.TimeoutError:
        return default
    except Exception as e:
        tag = f" [{label}]" if label else ""
        logger.error(f"run_in_executor 异常{tag}: {e}")
        return default


# ==================== Task 管理 ====================

# 全局后台任务集合（防止 GC 回收）
_background_tasks: set[asyncio.Task] = set()


def safe_create_task(
    coro,
    *,
    name: Optional[str] = None,
) -> asyncio.Task:
    """创建 asyncio Task 并自动追踪生命周期。

    - 保存引用防止 GC 回收
    - 完成时自动清理引用
    - 异常时自动记录日志

    Args:
        coro: 协程对象
        name: 任务名称（用于日志）

    Returns:
        创建的 asyncio.Task
    """
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)

    def _on_done(t: asyncio.Task):
        _background_tasks.discard(t)
        task_name = t.get_name() or "unnamed"
        if t.cancelled():
            logger.debug(f"后台任务已取消: {task_name}")
        elif t.exception():
            logger.error(
                f"后台任务异常退出: {task_name}",
                exc_info=t.exception(),
            )

    task.add_done_callback(_on_done)
    return task
