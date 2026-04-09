#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置相关的 Pydantic 数据模型
"""

from typing import Optional

from pydantic import BaseModel, Field


class ConfigMeta(BaseModel):
    """配置元信息"""
    config_path: str = Field(description="配置文件路径")
    last_modified: Optional[str] = Field(None, description="最后修改时间")


class ConfigData(BaseModel):
    """配置数据（映射 Config 类）"""
    # 连接配置
    futu_host: str = Field(description="富途API主机地址")
    futu_port: int = Field(description="富途API端口")
    database_path: str = Field(description="数据库路径")

    # 交易配置
    update_interval: int = Field(description="更新间隔（秒）")
    auto_trade: bool = Field(description="是否自动交易")
    price_change_threshold: float = Field(description="价格变动阈值")

    # 预警配置
    alert_5min_rise_threshold: float = Field(description="5分钟上涨预警阈值")
    alert_5min_fall_threshold: float = Field(description="5分钟下跌预警阈值")

    # 监控配置
    max_stocks_monitor: int = Field(description="最大监控股票数")
    max_subscription_stocks: int = Field(description="最大订阅股票数")

    # K线配置
    kline_init_days: int = Field(description="K线初始化天数")
    kline_batch_size: int = Field(description="K线批量大小")


class ConfigResponse(BaseModel):
    """配置响应（带元信息）"""
    data: ConfigData = Field(description="配置数据")
    meta: ConfigMeta = Field(description="配置元信息")
    requires_restart: Optional[bool] = Field(None, description="是否需要重启")


class UpdateConfigRequest(BaseModel):
    """更新配置请求"""
    # 所有字段都是可选的，允许部分更新
    futu_host: Optional[str] = None
    futu_port: Optional[int] = None
    database_path: Optional[str] = None
    update_interval: Optional[int] = None
    auto_trade: Optional[bool] = None
    price_change_threshold: Optional[float] = None
    alert_5min_rise_threshold: Optional[float] = None
    alert_5min_fall_threshold: Optional[float] = None
    max_stocks_monitor: Optional[int] = None
    max_subscription_stocks: Optional[int] = None
    kline_init_days: Optional[int] = None
    kline_batch_size: Optional[int] = None
