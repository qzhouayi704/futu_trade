#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
服务容器 - 负责所有服务的初始化和依赖注入（重构版）

通过组合子容器实现分层管理：
- CoreServices: 核心组件（数据库、API客户端）
- DataServices: 数据服务（初始化、实时、K线）
- BusinessServices: 业务服务（交易、策略、监控）
"""

import logging
from typing import Optional

from ...config.config import ConfigManager
from .core_services import CoreServices
from .data_services import DataServices
from .business_services import BusinessServices


class ServiceContainer:
    """服务容器 - 管理所有服务的生命周期和依赖关系"""

    def __init__(self, config: ConfigManager, app=None):
        """初始化服务容器

        Args:
            config: 配置管理器
            app: Flask应用实例（可选）
        """
        self.config = config
        self.app = app

        # 子容器
        self._core: Optional[CoreServices] = None
        self._data: Optional[DataServices] = None
        self._business: Optional[BusinessServices] = None

    def initialize_core(self):
        """初始化核心服务"""
        self._core = CoreServices(self.config)
        self._core.initialize()

    def initialize_data(self):
        """初始化数据服务"""
        if not self._core:
            raise RuntimeError("必须先初始化核心服务")
        self._data = DataServices(self._core, container=self)
        self._data.initialize()

    def initialize_business(self):
        """初始化业务服务"""
        if not self._core or not self._data:
            raise RuntimeError("必须先初始化核心服务和数据服务")
        self._business = BusinessServices(self._core, self._data)
        self._business.initialize()

    def initialize_all(self):
        """初始化所有服务（向后兼容方法）"""
        try:
            self.initialize_core()
            self.initialize_data()
            self.initialize_business()
            self._inject_dependencies()
            logging.info("服务容器初始化完成")
        except Exception as e:
            logging.error(f"服务容器初始化失败: {e}")
            raise

    def _inject_dependencies(self):
        """注入跨层依赖"""
        from ..state import get_state_manager

        state_manager = get_state_manager()

        # 注入 subscription_manager，用于 get_target_stocks()
        if self.subscription_manager:
            state_manager.set_subscription_manager(self.subscription_manager)
            logging.info("已注入 SubscriptionManager 到 StateManager")
        else:
            logging.warning("SubscriptionManager 未初始化，无法注入到 StateManager")

        # 延迟注入 heat_calculator 到 Pipeline
        if (self._data and self._data.subscription_helper
                and self._business and self._business.hot_stock_service):
            subscription_helper = self._data.subscription_helper
            heat_calculator = self._business.hot_stock_service.heat_calculator
            subscription_helper._init_pipeline(heat_calculator)
        else:
            logging.warning("无法注入 heat_calculator 到 Pipeline")

    def cleanup(self):
        """清理资源"""
        if self._core:
            self._core.cleanup()

    def __getattr__(self, name: str):
        """动态代理到子容器，按 _core → _data → _business 顺序查找

        替代原有的 29 个 @property 代理方法，保持向后兼容。
        仅在正常属性查找失败时触发（即不影响 config/app/_core/_data/_business 等实例属性）。
        """
        # 避免对私有/内部属性递归调用
        if name.startswith('_'):
            raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")

        # 使用 object.__getattribute__ 避免递归
        try:
            core = object.__getattribute__(self, '_core')
            data = object.__getattribute__(self, '_data')
            business = object.__getattribute__(self, '_business')
        except AttributeError:
            raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")

        for sub in (core, data, business):
            if sub is not None and hasattr(sub, name):
                return getattr(sub, name)

        raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")
