#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ASGI 入口文件

整合 FastAPI 和 python-socketio (ASGI 模式)

启动命令：
  uvicorn simple_trade.asgi:app --host 0.0.0.0 --port 5001 --reload
"""

import sys
import os
import asyncio
import socketio

# 加载 .env 文件到环境变量（确保直接用 uvicorn 启动时也能读取）
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

from .app import fastapi_app
from .websocket import get_socket_manager

# 获取 SocketManager 并创建 AsyncServer
socket_manager = get_socket_manager()
sio = socket_manager.create_server()

# 包装 FastAPI 应用
app = socketio.ASGIApp(sio, fastapi_app)


# 导出 sio 实例和 socket_manager 供其他模块使用
def get_sio():
    """获取 SocketIO 实例"""
    return sio


def get_manager():
    """获取 SocketManager 实例"""
    return socket_manager
