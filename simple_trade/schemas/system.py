#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
系统相关的 Pydantic 数据模型
"""

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


# ========== 系统状态相关 ==========

class ConfigInfo(BaseModel):
    """配置信息"""
    auto_trade: bool = Field(description="是否开启自动交易")
    update_interval: int = Field(description="更新间隔（秒）")
    max_stocks: int = Field(description="最大监控股票数")


class SubscriptionStatus(BaseModel):
    """订阅状态"""
    subscribed_count: int = Field(description="已订阅股票数量")
    max_subscription: int = Field(description="最大订阅数量")
    subscribed_stocks: List[str] = Field(default_factory=list, description="已订阅股票列表")


class SystemStatus(BaseModel):
    """系统状态"""
    is_running: bool = Field(description="监控是否运行中")
    last_update: Optional[str] = Field(None, description="最后更新时间")
    futu_connected: bool = Field(description="富途API是否连接")
    subscription_status: Dict = Field(description="订阅状态")
    config: ConfigInfo = Field(description="配置信息")


class DataStats(BaseModel):
    """数据统计"""
    plates_total: int = Field(description="板块总数")
    stocks_active: int = Field(description="活跃股票数")


class DatabaseDiagnosis(BaseModel):
    """数据库诊断结果"""
    connection: bool = Field(description="连接状态")
    existing_tables: List[str] = Field(default_factory=list, description="现有表")
    missing_tables: List[str] = Field(default_factory=list, description="缺失表")
    tables_complete: bool = Field(description="表是否完整")
    data_stats: Optional[DataStats] = Field(None, description="数据统计")
    error: Optional[str] = Field(None, description="错误信息")


class FutuAPIDiagnosis(BaseModel):
    """富途API诊断结果"""
    status: Dict = Field(description="连接状态")
    test_results: Dict = Field(default_factory=dict, description="测试结果")


class DiagnosisResult(BaseModel):
    """诊断结果"""
    success: bool = Field(description="诊断是否成功")
    timestamp: str = Field(description="诊断时间")
    futu_api: FutuAPIDiagnosis = Field(description="富途API状态")
    database: DatabaseDiagnosis = Field(description="数据库状态")
    data_initialization: Dict = Field(description="数据初始化状态")
    recommendations: List[str] = Field(description="建议")


# ========== 监控控制相关 ==========

class MonitorControlRequest(BaseModel):
    """监控控制请求"""
    action: str = Field(..., description="控制操作：start/stop")


class MonitorStartResponse(BaseModel):
    """监控启动响应"""
    futu_available: bool = Field(description="富途API是否可用")
    stock_count: int = Field(description="股票池数量")
    subscribed_count: int = Field(description="已订阅数量")
    already_running: Optional[bool] = Field(None, description="是否已在运行")


class StockPoolHealth(BaseModel):
    """股票池健康状态"""
    total_count: int = Field(description="总数量")
    has_data: bool = Field(description="是否有数据")


class SubscriptionHealth(BaseModel):
    """订阅健康状态"""
    subscribed_count: int = Field(description="已订阅数量")
    has_subscription: bool = Field(description="是否有订阅")
    sample_stocks: List[str] = Field(description="样本股票")


class MonitorHealth(BaseModel):
    """监控健康状态"""
    is_running: bool = Field(description="监控是否运行")
    futu_api_available: bool = Field(description="富途API是否可用")
    monitor_thread_alive: bool = Field(description="监控线程是否存活")


class HealthCheckData(BaseModel):
    """健康检查数据"""
    timestamp: str = Field(description="检查时间")
    status: MonitorHealth = Field(description="监控状态")
    stock_pool: StockPoolHealth = Field(description="股票池状态")
    subscription: SubscriptionHealth = Field(description="订阅状态")
    last_update: Optional[str] = Field(None, description="最后更新时间")
    config: ConfigInfo = Field(description="配置信息")
