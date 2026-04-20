#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebSocket 管理器

管理 python-socketio AsyncServer 和事件处理
"""

import logging
import time
from datetime import datetime
from typing import Optional, Dict, Any, Set

import socketio

from .events import SocketEvent, StatusData, ErrorData


class SocketManager:
    """WebSocket 管理器 - 封装 AsyncServer 和事件处理"""

    # 高频事件节流配置（事件名 -> 最小间隔秒数）
    _THROTTLE_INTERVALS: Dict[str, float] = {
        'quotes_update': 3.0,      # 报价更新：最快 3 秒一次
        'conditions_update': 5.0,  # 条件更新：最快 5 秒一次
    }

    def __init__(self):
        """初始化 WebSocket 管理器"""
        self.sio: Optional[socketio.AsyncServer] = None
        self.connected_clients: Dict[str, Dict[str, Any]] = {}
        # 节流状态：事件名 -> 上次发送时间戳
        self._last_emit_time: Dict[str, float] = {}
        # 节流统计
        self._throttle_skip_count: int = 0

    def create_server(self) -> socketio.AsyncServer:
        """创建 AsyncServer 实例

        Returns:
            socketio.AsyncServer 实例
        """
        self.sio = socketio.AsyncServer(
            async_mode='asgi',
            cors_allowed_origins='*',
            logger=True,
            engineio_logger=False
        )

        # 注册事件处理器
        self._register_handlers()

        return self.sio

    def _register_handlers(self):
        """注册事件处理器"""

        @self.sio.event
        async def connect(sid, environ):
            """客户端连接事件"""
            client_info = {
                'sid': sid,
                'connected_at': datetime.now().isoformat(),
                'user_agent': environ.get('HTTP_USER_AGENT', 'Unknown')
            }
            self.connected_clients[sid] = client_info

            logging.info(f"[SocketIO] 客户端已连接: {sid}")
            print(f"[SocketIO] 客户端已连接: {sid}, 当前连接数: {len(self.connected_clients)}")

            # 发送连接成功状态
            status_data = StatusData(
                connected=True,
                timestamp=datetime.now().isoformat(),
                message="连接成功"
            )
            await self.sio.emit(SocketEvent.STATUS, status_data.dict(), to=sid)

        @self.sio.event
        async def disconnect(sid):
            """客户端断开事件"""
            if sid in self.connected_clients:
                del self.connected_clients[sid]

            logging.info(f"[SocketIO] 客户端已断开: {sid}")
            print(f"[SocketIO] 客户端已断开: {sid}, 当前连接数: {len(self.connected_clients)}")

        @self.sio.event
        async def request_update(sid):
            """客户端请求更新事件"""
            logging.info(f"[SocketIO] 收到更新请求: {sid}")

            # TODO: 触发广播协调器的异步更新
            # 这里暂时返回一个待实现的消息
            await self.sio.emit(
                SocketEvent.UPDATE_PENDING,
                {'message': '更新功能待完整迁移', 'timestamp': datetime.now().isoformat()},
                to=sid
            )

    async def emit_to_all(self, event: str, data: Dict[str, Any]):
        """向所有客户端广播消息（含超时保护 + 高频节流）

        Args:
            event: 事件名称
            data: 数据
        """
        if not self.sio:
            logging.warning("[SocketIO] Server not initialized")
            return

        # 高频事件节流：在最小间隔内跳过，只保留最新数据
        event_name = event.value if hasattr(event, 'value') else str(event)
        throttle_interval = self._THROTTLE_INTERVALS.get(event_name)
        if throttle_interval:
            now = time.monotonic()
            last_time = self._last_emit_time.get(event_name, 0)
            if now - last_time < throttle_interval:
                self._throttle_skip_count += 1
                if self._throttle_skip_count % 50 == 1:
                    logging.debug(
                        f"[SocketIO] 节流跳过: {event_name}，"
                        f"累计跳过 {self._throttle_skip_count} 次"
                    )
                return
            self._last_emit_time[event_name] = now

        try:
            import asyncio
            await asyncio.wait_for(self.sio.emit(event, data), timeout=3.0)
            logging.debug(f"[SocketIO] 广播事件: {event_name}, 客户端数: {len(self.connected_clients)}")
        except asyncio.TimeoutError:
            logging.warning(f"[SocketIO] 广播超时(3s): {event_name}, 客户端数: {len(self.connected_clients)}")
        except Exception as e:
            logging.error(f"[SocketIO] 广播失败: {e}")

    async def emit_to_client(self, sid: str, event: str, data: Dict[str, Any]):
        """向指定客户端发送消息

        Args:
            sid: 客户端 session ID
            event: 事件名称
            data: 数据
        """
        if not self.sio:
            logging.warning("[SocketIO] Server not initialized")
            return

        try:
            await self.sio.emit(event, data, to=sid)
            logging.debug(f"[SocketIO] 发送事件到 {sid}: {event}")
        except Exception as e:
            logging.error(f"[SocketIO] 发送失败: {e}")

    async def emit_error(self, sid: str, error_message: str, error_code: str = ""):
        """向客户端发送错误消息

        Args:
            sid: 客户端 session ID
            error_message: 错误消息
            error_code: 错误代码
        """
        error_data = ErrorData(
            error=error_message,
            code=error_code,
            timestamp=datetime.now().isoformat()
        )
        await self.emit_to_client(sid, SocketEvent.ERROR, error_data.dict())

    def get_connected_count(self) -> int:
        """获取当前连接的客户端数量

        Returns:
            连接数
        """
        return len(self.connected_clients)

    def get_connected_clients(self) -> Dict[str, Dict[str, Any]]:
        """获取所有连接的客户端信息

        Returns:
            客户端信息字典
        """
        return self.connected_clients.copy()


# 全局单例
_socket_manager: Optional[SocketManager] = None


def get_socket_manager() -> SocketManager:
    """获取 SocketManager 单例

    Returns:
        SocketManager 实例
    """
    global _socket_manager
    if _socket_manager is None:
        _socket_manager = SocketManager()
    return _socket_manager
