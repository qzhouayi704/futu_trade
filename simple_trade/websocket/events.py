#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebSocket 事件定义

定义所有 WebSocket 事件的名称和数据结构
"""

from enum import Enum
from typing import Dict, Any, List
from pydantic import BaseModel


class SocketEvent(str, Enum):
    """WebSocket 事件名称枚举"""
    # 连接事件
    CONNECT = "connect"
    DISCONNECT = "disconnect"

    # 客户端请求事件
    REQUEST_UPDATE = "request_update"
    SUBSCRIBE_QUOTES = "subscribe_quotes"
    UNSUBSCRIBE_QUOTES = "unsubscribe_quotes"

    # 服务端推送事件
    STATUS = "status"
    QUOTES_UPDATE = "quotes_update"
    ALERTS_UPDATE = "alerts_update"
    CONDITIONS_UPDATE = "conditions_update"
    SIGNALS_UPDATE = "signals_update"
    STRATEGY_SIGNAL = "strategy_signal"
    KLINE_UPDATE = "kline_update"
    QUOTA_UPDATE = "quota_update"

    # 交易确认事件
    TRADE_CONFIRM_REQUEST = "trade_confirm_request"    # 服务端 → 前端
    TRADE_CONFIRM_RESPONSE = "trade_confirm_response"  # 前端 → 服务端

    # 系统事件
    UPDATE_PENDING = "update_pending"
    ERROR = "error"

    # 决策助理事件
    ADVISOR_UPDATE = "advisor_update"

    # Scalping 日内超短线事件
    DELTA_UPDATE = "delta_update"                  # Delta 动量更新
    MOMENTUM_IGNITION = "momentum_ignition"        # 动能点火事件
    PRICE_LEVEL_CREATE = "price_level_create"      # 生成阻力/支撑线
    PRICE_LEVEL_REMOVE = "price_level_remove"      # 撤销阻力/支撑线
    PRICE_LEVEL_BREAK = "price_level_break"        # 阻力/支撑线被突破
    POC_UPDATE = "poc_update"                      # POC 控制点更新
    SCALPING_SIGNAL = "scalping_signal"            # Scalping 交易信号

    # 防诱多/诱空事件
    TRAP_ALERT = "trap_alert"                      # 诱多/诱空警报
    FAKE_BREAKOUT_ALERT = "fake_breakout_alert"    # 假突破警报
    TRUE_BREAKOUT_CONFIRM = "true_breakout_confirm"  # 真突破确认
    FAKE_LIQUIDITY_ALERT = "fake_liquidity_alert"  # 虚假流动性警报
    VWAP_EXTENSION_ALERT = "vwap_extension_alert"  # VWAP 超限警报
    VWAP_EXTENSION_CLEAR = "vwap_extension_clear"  # VWAP 恢复正常

    # Tick 可信度与止损事件
    STOP_LOSS_ALERT = "stop_loss_alert"            # 止损提示
    TICK_OUTLIER = "tick_outlier"                   # 异常大单标记

    # 行为模式与行动评分
    PATTERN_ALERT = "pattern_alert"                # 行为模式预警（8种）
    ACTION_SIGNAL = "action_signal"                # 行动评分信号（加分制）


# ==================== 事件数据模型 ====================

class StatusData(BaseModel):
    """状态数据"""
    connected: bool
    timestamp: str = ""
    message: str = ""


class QuotesUpdateData(BaseModel):
    """报价更新数据"""
    quotes: List[Dict[str, Any]]
    count: int
    timestamp: str


class AlertsUpdateData(BaseModel):
    """预警更新数据"""
    alerts: List[Dict[str, Any]]
    count: int
    timestamp: str


class ConditionsUpdateData(BaseModel):
    """交易条件更新数据"""
    conditions: List[Dict[str, Any]]
    count: int
    timestamp: str


class SignalsUpdateData(BaseModel):
    """信号更新数据"""
    signals: List[Dict[str, Any]]
    count: int
    timestamp: str


class StrategySignalData(BaseModel):
    """策略信号数据"""
    signal_type: str  # 'buy' or 'sell'
    stock_code: str
    stock_name: str
    price: float
    reason: str
    strategy_name: str = ""
    timestamp: str


class KlineUpdateData(BaseModel):
    """K线更新数据"""
    stock_code: str
    kline_data: List[List[Any]]  # [[date, open, close, low, high, volume], ...]
    timestamp: str


class QuotaUpdateData(BaseModel):
    """配额更新数据"""
    quota_data: Dict[str, Any]
    timestamp: str


class ErrorData(BaseModel):
    """错误数据"""
    error: str
    code: str = ""
    timestamp: str


class TradeConfirmRequestData(BaseModel):
    """交易确认请求数据（服务端 → 前端）"""
    signal_id: int
    stock_code: str
    stock_name: str
    trade_type: str  # 'BUY' or 'SELL'
    price: float
    reason: str = ""
    timeout: int = 30  # 确认超时秒数
    timestamp: str


class TradeConfirmResponseData(BaseModel):
    """交易确认响应数据（前端 → 服务端）"""
    signal_id: int
    confirmed: bool  # True=确认执行, False=拒绝
    timestamp: str
