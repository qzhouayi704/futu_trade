#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
脚本初始化工具模块

提供脚本通用的初始化函数，包括路径设置、日志配置等
"""

import os
import sys
import logging
from pathlib import Path
from typing import Optional


def setup_project_path() -> str:
    """
    设置项目路径到 sys.path

    自动检测脚本所在位置，将项目根目录添加到 sys.path，
    使脚本可以正确导入 simple_trade 模块。

    Returns:
        项目根目录的绝对路径

    Example:
        >>> from simple_trade.utils.script_helper import setup_project_path
        >>> project_root = setup_project_path()
        >>> # 现在可以导入 simple_trade 模块了
        >>> from simple_trade.database.core.db_manager import DatabaseManager
    """
    # 获取当前脚本的绝对路径
    current_file = os.path.abspath(__file__)

    # 向上查找项目根目录（包含 simple_trade 目录的目录）
    current_dir = os.path.dirname(current_file)
    while current_dir != os.path.dirname(current_dir):  # 未到达根目录
        if os.path.exists(os.path.join(current_dir, 'simple_trade')):
            project_root = current_dir
            break
        current_dir = os.path.dirname(current_dir)
    else:
        # 如果没找到，使用传统方法（假设脚本在 scripts/ 下）
        project_root = os.path.dirname(os.path.dirname(current_file))

    # 添加到 sys.path（如果还没有）
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    return project_root


def setup_logging(
    level: int = logging.INFO,
    log_file: Optional[str] = None,
    format_string: Optional[str] = None
) -> None:
    """
    配置日志系统

    Args:
        level: 日志级别（默认 INFO）
        log_file: 日志文件路径（可选，不指定则只输出到控制台）
        format_string: 日志格式字符串（可选）

    Example:
        >>> setup_logging(level=logging.DEBUG, log_file='script.log')
    """
    if format_string is None:
        format_string = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    handlers = [logging.StreamHandler()]

    if log_file:
        # 确保日志目录存在
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding='utf-8'))

    logging.basicConfig(
        level=level,
        format=format_string,
        handlers=handlers,
        force=True  # 覆盖已有的配置
    )


def init_script_environment(
    log_level: int = logging.INFO,
    log_file: Optional[str] = None
) -> str:
    """
    初始化脚本环境（路径 + 日志）

    这是最常用的初始化函数，一次性完成路径设置和日志配置。

    Args:
        log_level: 日志级别（默认 INFO）
        log_file: 日志文件路径（可选）

    Returns:
        项目根目录的绝对路径

    Example:
        >>> from simple_trade.utils.script_helper import init_script_environment
        >>> project_root = init_script_environment(log_level=logging.DEBUG)
        >>> # 现在可以使用 simple_trade 模块和日志系统了
    """
    project_root = setup_project_path()
    setup_logging(level=log_level, log_file=log_file)
    return project_root
