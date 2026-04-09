#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略注册器

提供策略的注册、发现和管理功能。
支持通过名称获取策略实例，以及策略的动态加载。
"""

import logging
from typing import Dict, Type, List, Optional, Any
from .base_strategy import BaseStrategy


class StrategyRegistry:
    """
    策略注册器
    
    管理所有可用的交易策略，提供注册和获取功能。
    
    使用示例：
    ```python
    # 注册策略
    StrategyRegistry.register("swing", SwingStrategy)
    
    # 获取策略类
    strategy_class = StrategyRegistry.get("swing")
    
    # 创建策略实例
    strategy = StrategyRegistry.create_instance("swing", data_service=service)
    
    # 获取所有策略信息
    all_strategies = StrategyRegistry.list_strategies()
    ```
    """
    
    # 策略注册表：{策略名称: 策略类}
    _strategies: Dict[str, Type[BaseStrategy]] = {}
    
    # 策略实例缓存：{策略名称: 策略实例}
    _instances: Dict[str, BaseStrategy] = {}
    
    # 默认策略名称
    _default_strategy: Optional[str] = None
    
    @classmethod
    def register(
        cls, 
        name: str, 
        strategy_class: Type[BaseStrategy],
        is_default: bool = False
    ) -> None:
        """
        注册策略
        
        Args:
            name: 策略名称（唯一标识）
            strategy_class: 策略类（必须继承 BaseStrategy）
            is_default: 是否设为默认策略
        """
        if not issubclass(strategy_class, BaseStrategy):
            raise TypeError(f"策略类 {strategy_class.__name__} 必须继承 BaseStrategy")
        
        if name in cls._strategies:
            logging.warning(f"策略 '{name}' 已存在，将被覆盖")
        
        cls._strategies[name] = strategy_class
        logging.info(f"已注册策略: {name} -> {strategy_class.__name__}")
        
        if is_default or cls._default_strategy is None:
            cls._default_strategy = name
            logging.info(f"默认策略设置为: {name}")
    
    @classmethod
    def unregister(cls, name: str) -> bool:
        """
        取消注册策略
        
        Args:
            name: 策略名称
            
        Returns:
            是否成功取消注册
        """
        if name in cls._strategies:
            del cls._strategies[name]
            logging.info(f"已取消注册策略: {name}")
            
            # 如果取消的是默认策略，重置默认策略
            if cls._default_strategy == name:
                cls._default_strategy = next(iter(cls._strategies), None)
                if cls._default_strategy:
                    logging.info(f"默认策略重置为: {cls._default_strategy}")
            return True
        return False
    
    @classmethod
    def get(cls, name: str) -> Optional[Type[BaseStrategy]]:
        """
        获取策略类
        
        Args:
            name: 策略名称
            
        Returns:
            策略类，如果不存在返回 None
        """
        return cls._strategies.get(name)
    
    @classmethod
    def get_instance(cls, name: str) -> Optional[BaseStrategy]:
        """
        获取已缓存的策略实例
        
        Args:
            name: 策略名称
            
        Returns:
            策略实例，如果不存在返回 None
        """
        return cls._instances.get(name)
    
    @classmethod
    def get_default(cls) -> Optional[Type[BaseStrategy]]:
        """
        获取默认策略类
        
        Returns:
            默认策略类
        """
        if cls._default_strategy:
            return cls._strategies.get(cls._default_strategy)
        return None
    
    @classmethod
    def get_default_name(cls) -> Optional[str]:
        """
        获取默认策略名称
        
        Returns:
            默认策略名称
        """
        return cls._default_strategy
    
    @classmethod
    def set_default(cls, name: str) -> bool:
        """
        设置默认策略
        
        Args:
            name: 策略名称
            
        Returns:
            是否设置成功
        """
        if name in cls._strategies:
            cls._default_strategy = name
            logging.info(f"默认策略设置为: {name}")
            return True
        logging.warning(f"策略 '{name}' 不存在，无法设为默认策略")
        return False
    
    @classmethod
    def create_instance(
        cls,
        name: str = None,
        data_service = None,
        config: Dict[str, Any] = None
    ) -> Optional[BaseStrategy]:
        """
        创建策略实例
        
        Args:
            name: 策略名称，如果为 None 则使用默认策略
            data_service: 数据服务
            config: 策略配置
            
        Returns:
            策略实例，如果策略不存在返回 None
        """
        if name is None:
            name = cls._default_strategy
        
        if name is None:
            logging.error("没有可用的策略")
            return None
        
        strategy_class = cls._strategies.get(name)
        if strategy_class is None:
            logging.error(f"策略 '{name}' 不存在")
            return None
        
        try:
            # 创建策略实例
            instance = strategy_class(data_service=data_service, config=config)
            logging.debug(f"创建策略实例: {name}")
            return instance
        except Exception as e:
            logging.error(f"创建策略实例失败 '{name}': {e}")
            return None
    
    @classmethod
    def create_all_instances(
        cls,
        data_service = None,
        config: Dict[str, Any] = None
    ) -> Dict[str, BaseStrategy]:
        """
        创建所有策略的实例
        
        Args:
            data_service: 数据服务
            config: 通用配置
            
        Returns:
            {策略名称: 策略实例}
        """
        instances = {}
        for name in cls._strategies:
            instance = cls.create_instance(name, data_service, config)
            if instance:
                instances[name] = instance
        # 缓存实例，供 get_instance() 使用
        cls._instances.update(instances)
        return instances
    
    @classmethod
    def list_strategies(cls) -> List[Dict[str, Any]]:
        """
        列出所有注册的策略
        
        Returns:
            策略信息列表
        """
        strategies = []
        for name, strategy_class in cls._strategies.items():
            # 创建临时实例获取策略信息
            try:
                temp_instance = strategy_class()
                info = {
                    'id': name,
                    'name': temp_instance.name,
                    'description': temp_instance.description,
                    'class_name': strategy_class.__name__,
                    'is_default': name == cls._default_strategy,
                    'buy_conditions': temp_instance.get_buy_conditions(),
                    'sell_conditions': temp_instance.get_sell_conditions(),
                    'required_kline_days': temp_instance.get_required_kline_days()
                }
            except Exception as e:
                logging.warning(f"获取策略信息失败 '{name}': {e}")
                info = {
                    'id': name,
                    'name': name,
                    'description': f"无法获取描述: {e}",
                    'class_name': strategy_class.__name__,
                    'is_default': name == cls._default_strategy
                }
            strategies.append(info)
        return strategies
    
    @classmethod
    def get_strategy_info(cls, name: str) -> Optional[Dict[str, Any]]:
        """
        获取单个策略的详细信息
        
        Args:
            name: 策略名称
            
        Returns:
            策略信息字典
        """
        strategy_class = cls._strategies.get(name)
        if not strategy_class:
            return None
        
        try:
            temp_instance = strategy_class()
            return temp_instance.get_strategy_info()
        except Exception as e:
            logging.error(f"获取策略信息失败 '{name}': {e}")
            return None
    
    @classmethod
    def has_strategy(cls, name: str) -> bool:
        """
        检查策略是否存在
        
        Args:
            name: 策略名称
            
        Returns:
            是否存在
        """
        return name in cls._strategies
    
    @classmethod
    def count(cls) -> int:
        """
        获取已注册策略数量
        
        Returns:
            策略数量
        """
        return len(cls._strategies)
    
    @classmethod
    def clear(cls) -> None:
        """
        清空所有注册的策略
        """
        cls._strategies.clear()
        cls._instances.clear()
        cls._default_strategy = None
        logging.info("已清空所有策略注册")
    
    @classmethod
    def get_strategy_names(cls) -> List[str]:
        """
        获取所有策略名称
        
        Returns:
            策略名称列表
        """
        return list(cls._strategies.keys())


def register_strategy(name: str, is_default: bool = False):
    """
    策略注册装饰器
    
    使用示例：
    ```python
    @register_strategy("swing", is_default=True)
    class SwingStrategy(BaseStrategy):
        ...
    ```
    """
    def decorator(cls):
        if not issubclass(cls, BaseStrategy):
            raise TypeError(f"策略类 {cls.__name__} 必须继承 BaseStrategy")
        StrategyRegistry.register(name, cls, is_default)
        return cls
    return decorator


def auto_discover_strategies():
    """
    自动发现并注册策略
    
    扫描 strategy 模块下的所有策略类并自动注册。
    策略类需要定义 STRATEGY_ID 类属性作为注册名称。
    """
    import importlib
    import pkgutil
    from pathlib import Path
    
    # 获取 strategy 包路径
    strategy_path = Path(__file__).parent
    
    for _, module_name, _ in pkgutil.iter_modules([str(strategy_path)]):
        # 跳过基类和注册器模块
        if module_name in ['base_strategy', 'strategy_registry', '__init__']:
            continue
        
        try:
            # 动态导入模块
            module = importlib.import_module(f'.{module_name}', package='simple_trade.strategy')
            
            # 查找模块中的策略类
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and 
                    issubclass(attr, BaseStrategy) and 
                    attr is not BaseStrategy):
                    
                    # 检查是否有 STRATEGY_ID 属性
                    strategy_id = getattr(attr, 'STRATEGY_ID', None)
                    if strategy_id and not StrategyRegistry.has_strategy(strategy_id):
                        is_default = getattr(attr, 'IS_DEFAULT', False)
                        StrategyRegistry.register(strategy_id, attr, is_default)
                        logging.info(f"自动发现并注册策略: {strategy_id}")
                        
        except Exception as e:
            logging.warning(f"自动发现策略失败 '{module_name}': {e}")
