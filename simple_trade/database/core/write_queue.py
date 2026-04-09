#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库写入队列
将所有 SQLite 写操作序列化到单一 Worker 线程，彻底消除 "database is locked" 错误
"""

import queue
import logging
import threading
from concurrent.futures import Future
from typing import Any, Callable


class DatabaseWriteQueue:
    """数据库写入队列 — 所有写操作由单一线程顺序执行

    设计要点：
    - 任何线程可调用 submit() 提交写任务，立即获得 Future
    - 内部 daemon 线程从队列中顺序消费，保证 SQLite 同一时刻只有一个写入者
    - 调用方通过 future.result(timeout) 同步等待执行结果
    """

    _SENTINEL = object()  # 关闭信号

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._worker = threading.Thread(
            target=self._process_loop,
            name="db-write-worker",
            daemon=True,
        )
        self._running = False

    def start(self):
        """启动 Worker 线程（由 ConnectionManager 在初始化时调用）"""
        if not self._running:
            self._running = True
            self._worker.start()
            logging.debug("数据库写入队列已启动")

    def submit(self, fn: Callable, *args: Any, **kwargs: Any) -> Future:
        """提交写任务到队列

        Args:
            fn: 要执行的写操作函数
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            Future 对象，调用方可通过 .result(timeout) 获取返回值

        Raises:
            RuntimeError: 队列未启动或已关闭
        """
        if not self._running:
            raise RuntimeError("写入队列未启动")

        future: Future = Future()
        self._queue.put((fn, args, kwargs, future))
        return future

    def shutdown(self, timeout: float = 10.0):
        """优雅关闭 Worker 线程

        Args:
            timeout: 等待 Worker 线程退出的超时秒数
        """
        if not self._running:
            return

        self._running = False
        self._queue.put(self._SENTINEL)

        if self._worker.is_alive():
            self._worker.join(timeout=timeout)
            if self._worker.is_alive():
                logging.warning("数据库写入队列 Worker 未能在超时内退出")

        logging.debug("数据库写入队列已关闭")

    def _process_loop(self):
        """Worker 线程主循环 — 顺序消费队列中的写任务"""
        logging.debug("数据库写入队列 Worker 已启动")

        while True:
            try:
                item = self._queue.get()

                # 收到关闭信号
                if item is self._SENTINEL:
                    break

                fn, args, kwargs, future = item

                # 如果 Future 已被取消，跳过执行
                if future.cancelled():
                    continue

                try:
                    result = fn(*args, **kwargs)
                    future.set_result(result)
                except Exception as e:
                    future.set_exception(e)

            except Exception as e:
                logging.error(f"写入队列处理异常: {e}", exc_info=True)

        logging.debug("数据库写入队列 Worker 已退出")

    @property
    def pending_count(self) -> int:
        """队列中等待执行的任务数"""
        return self._queue.qsize()

    @property
    def is_running(self) -> bool:
        """队列是否正在运行"""
        return self._running
