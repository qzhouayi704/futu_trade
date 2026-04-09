#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebSocket 模块

提供 WebSocket 管理和事件处理功能
"""

from .socket_manager import SocketManager, get_socket_manager
from .events import (
    SocketEvent,
    StatusData,
    QuotesUpdateData,
    AlertsUpdateData,
    ConditionsUpdateData,
    SignalsUpdateData,
    StrategySignalData,
    KlineUpdateData,
    QuotaUpdateData,
    ErrorData
)

__all__ = [
    'SocketManager',
    'get_socket_manager',
    'SocketEvent',
    'StatusData',
    'QuotesUpdateData',
    'AlertsUpdateData',
    'ConditionsUpdateData',
    'SignalsUpdateData',
    'StrategySignalData',
    'KlineUpdateData',
    'QuotaUpdateData',
    'ErrorData'
]
