#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据转换基类模块

提供通用的数据转换Mixin类
"""

from typing import Dict, Any


class DictConvertibleMixin:
    """
    提供 to_dict() 方法的 Mixin 类

    任何需要转换为字典的数据类都可以继承此 Mixin，
    自动获得 to_dict() 方法，将所有非私有属性转换为字典。

    Example:
        >>> class MyData(DictConvertibleMixin):
        ...     def __init__(self, name: str, value: int):
        ...         self.name = name
        ...         self.value = value
        ...         self._internal = "private"
        ...
        >>> data = MyData("test", 42)
        >>> data.to_dict()
        {'name': 'test', 'value': 42}
    """

    def to_dict(self) -> Dict[str, Any]:
        """
        将对象转换为字典

        Returns:
            包含所有非私有属性的字典（不包括以 _ 开头的属性）
        """
        return {
            key: value
            for key, value in self.__dict__.items()
            if not key.startswith('_')
        }


class JsonSerializableMixin(DictConvertibleMixin):
    """
    提供 JSON 序列化支持的 Mixin 类

    继承自 DictConvertibleMixin，并添加了对嵌套对象的支持
    """

    def to_dict(self) -> Dict[str, Any]:
        """
        将对象转换为字典，支持嵌套对象

        Returns:
            包含所有非私有属性的字典，嵌套对象也会被转换
        """
        result = {}
        for key, value in self.__dict__.items():
            if key.startswith('_'):
                continue

            # 处理嵌套的 DictConvertibleMixin 对象
            if isinstance(value, DictConvertibleMixin):
                result[key] = value.to_dict()
            # 处理列表
            elif isinstance(value, list):
                result[key] = [
                    item.to_dict() if isinstance(item, DictConvertibleMixin) else item
                    for item in value
                ]
            # 处理字典
            elif isinstance(value, dict):
                result[key] = {
                    k: v.to_dict() if isinstance(v, DictConvertibleMixin) else v
                    for k, v in value.items()
                }
            else:
                result[key] = value

        return result
