#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析上下文 - 消除 (futu_client, db_manager, config) 三元组数据泥团。

将反复出现的三元组依赖封装为一个数据类，供所有分析模块统一使用。
"""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class AnalysisContext:
    """分析上下文 - 封装分析模块的公共依赖

    替代 (futu_client, db_manager, config) 三元组，
    减少构造函数参数传递的冗余。

    Attributes:
        futu_client: 富途 API 客户端实例
        db_manager: 数据库管理器实例
        config: 全局配置字典
    """

    futu_client: Any  # FutuClient 实例
    db_manager: Any  # DatabaseManager 实例
    config: dict

    @property
    def enhanced_heat_config(self) -> dict:
        """增强热度配置子集"""
        return self.config.get("enhanced_heat_config", {})

    @property
    def capital_flow_config(self) -> dict:
        """资金流向配置"""
        return self.enhanced_heat_config.get("capital_flow_config", {})

    @property
    def big_order_config(self) -> dict:
        """大单追踪配置"""
        return self.enhanced_heat_config.get("big_order_config", {})

    @property
    def cache_duration_config(self) -> dict:
        """缓存时效配置"""
        return self.enhanced_heat_config.get("cache_duration", {})
