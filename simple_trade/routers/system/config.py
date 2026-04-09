#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置管理路由 - FastAPI Router

迁移自 routes/config_routes.py
"""

import os
import logging
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, Depends

from ...config.config import Config, ConfigManager
from ...core.exceptions import BusinessError, ValidationError
from ...dependencies import get_container
from ...schemas.common import APIResponse
from ...schemas.config import ConfigData, ConfigMeta, UpdateConfigRequest


router = APIRouter(prefix="/api/config", tags=["配置管理"])


def _get_config_meta(config_path: str = "simple_trade/config.json") -> ConfigMeta:
    """获取配置文件元信息"""
    meta = ConfigMeta(config_path=config_path, last_modified=None)

    if os.path.exists(config_path):
        modified_time = os.path.getmtime(config_path)
        meta.last_modified = datetime.fromtimestamp(modified_time).isoformat()

    return meta


def _config_to_dict(config: Config) -> Dict[str, Any]:
    """将 Config 对象转为字典"""
    return ConfigManager.to_dict(config)


@router.get("")
async def get_config(container=Depends(get_container)):
    """获取当前配置"""
    try:
        # 获取配置对象
        config = container.config
        config_dict = _config_to_dict(config)

        # 获取配置文件的元信息
        meta = _get_config_meta()

        return {
            "success": True,
            "message": "获取配置成功",
            "data": config_dict,
            "meta": meta.dict()
        }
    except Exception as e:
        logging.error(f"获取配置失败: {e}")
        raise BusinessError(message=f"获取配置失败: {str(e)}")


@router.put("")
async def update_config(
    request: UpdateConfigRequest,
    container=Depends(get_container)
):
    """更新配置"""
    try:
        # 获取请求数据（排除 None 值）
        update_data = request.dict(exclude_none=True)

        if not update_data:
            raise ValidationError(message="请提供配置数据")

        # 获取当前配置
        current_config = container.config
        current_dict = _config_to_dict(current_config)

        # 合并更新数据
        updated_dict = {**current_dict, **update_data}

        # 验证配置数据
        try:
            new_config = Config(**updated_dict)
        except Exception as e:
            raise ValidationError(
                message=f"配置数据验证失败: {str(e)}",
                details=str(e)
            )

        # 保存配置
        config_path = "simple_trade/config.json"
        ConfigManager.save_config(new_config, config_path)

        # 更新系统配置的属性（热更新，不影响运行中的系统）
        for key, value in update_data.items():
            if hasattr(container.config, key):
                setattr(container.config, key, value)

        # 获取更新后的元信息
        meta = _get_config_meta(config_path)

        # 检查是否需要重启
        requires_restart = False
        critical_fields = ['futu_host', 'futu_port', 'database_path']
        for field in critical_fields:
            if field in update_data:
                requires_restart = True
                break

        return {
            "success": True,
            "message": "配置更新成功",
            "data": _config_to_dict(new_config),
            "meta": meta.dict(),
            "requires_restart": requires_restart
        }

    except ValidationError:
        raise
    except Exception as e:
        logging.error(f"更新配置失败: {e}")
        raise BusinessError(message=f"更新配置失败: {str(e)}")


@router.post("/reset")
async def reset_config(container=Depends(get_container)):
    """恢复默认配置"""
    try:
        # 创建默认配置
        default_config = Config()

        # 保存默认配置
        config_path = "simple_trade/config.json"
        ConfigManager.save_config(default_config, config_path)

        # 更新系统配置（直接替换配置对象的属性）
        default_dict = _config_to_dict(default_config)
        for key, value in default_dict.items():
            if hasattr(container.config, key):
                setattr(container.config, key, value)

        # 获取元信息
        meta = _get_config_meta(config_path)

        return {
            "success": True,
            "message": "配置已重置为默认值",
            "data": default_dict,
            "meta": meta.dict(),
            "requires_restart": True
        }

    except Exception as e:
        logging.error(f"重置配置失败: {e}")
        raise BusinessError(message=f"重置配置失败: {str(e)}")
