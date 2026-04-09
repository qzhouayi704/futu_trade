#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebSocket 管理器

管理 python-socketio AsyncServer 和事件处理
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any

import socketio

from .events import SocketEvent, StatusData, ErrorData


class SocketManager:
    """WebSocket 管理器 - 封装 AsyncServer 和事件处理"""

    def __init__(self):
        """初始化 WebSocket 管理器"""
        self.sio: Optional[socketio.AsyncServer] = None
        self.connected_clients: Dict[str, Dict[str, Any]] = {}

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
        """向所有客户端广播消息

        Args:
            event: 事件名称
            data: 数据
        """
        if not self.sio:
            logging.warning("[SocketIO] Server not initialized")
            return

        try:
            await self.sio.emit(event, data)
            logging.debug(f"[SocketIO] 广播事件: {event}, 客户端数: {len(self.connected_clients)}")
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
