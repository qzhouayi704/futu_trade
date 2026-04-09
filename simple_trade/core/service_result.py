#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
标准服务返回格式

统一所有服务的返回值格式，提供一致的API响应结构
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime


@dataclass
class ServiceResult:
    """标准服务返回结果类"""
    
    success: bool
    message: str = ""
    data: Any = None
    error_code: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        result = {
            'success': self.success,
            'message': self.message,
            'timestamp': self.timestamp
        }
        
        if self.data is not None:
            result['data'] = self.data
            
        if self.error_code:
            result['error_code'] = self.error_code
            
        return result
    
    @classmethod
    def ok(cls, message: str = "操作成功", data: Any = None) -> 'ServiceResult':
        """创建成功结果"""
        return cls(success=True, message=message, data=data)
    
    @classmethod
    def fail(cls, message: str, error_code: str = None, data: Any = None) -> 'ServiceResult':
        """创建失败结果"""
        return cls(success=False, message=message, error_code=error_code, data=data)
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'ServiceResult':
        """从字典创建（用于兼容旧格式）"""
        return cls(
            success=d.get('success', False),
            message=d.get('message', ''),
            data=d.get('data'),
            error_code=d.get('error_code')
        )


class ServiceResultBuilder:
    """服务结果构建器 - 用于复杂的结果构建"""
    
    def __init__(self):
        self._success = True
        self._message = ""
        self._data = {}
        self._error_code = None
        self._errors: List[str] = []
    
    def set_success(self, success: bool) -> 'ServiceResultBuilder':
        self._success = success
        return self
    
    def set_message(self, message: str) -> 'ServiceResultBuilder':
        self._message = message
        return self
    
    def add_data(self, key: str, value: Any) -> 'ServiceResultBuilder':
        self._data[key] = value
        return self
    
    def set_data(self, data: Any) -> 'ServiceResultBuilder':
        self._data = data
        return self
    
    def set_error_code(self, code: str) -> 'ServiceResultBuilder':
        self._error_code = code
        return self
    
    def add_error(self, error: str) -> 'ServiceResultBuilder':
        self._errors.append(error)
        self._success = False
        return self
    
    def build(self) -> ServiceResult:
        data = self._data
        if self._errors:
            if isinstance(data, dict):
                data['errors'] = self._errors
            else:
                data = {'result': data, 'errors': self._errors}
        
        return ServiceResult(
            success=self._success,
            message=self._message,
            data=data if data else None,
            error_code=self._error_code
        )


# 便捷函数
def success_result(message: str = "操作成功", **kwargs) -> Dict[str, Any]:
    """创建成功结果字典（兼容旧代码）"""
    result = {'success': True, 'message': message}
    result.update(kwargs)
    return result


def error_result(message: str, error_code: str = None, **kwargs) -> Dict[str, Any]:
    """创建错误结果字典（兼容旧代码）"""
    result = {'success': False, 'message': message}
    if error_code:
        result['error_code'] = error_code
    result.update(kwargs)
    return result
