"""
回测日志配置模块

提供统一的日志配置功能
"""

import logging
import os
from typing import Optional


def setup_backtest_logging(
    output_dir: str,
    log_name: str = 'backtest',
    level: int = logging.INFO,
    console: bool = True
) -> logging.Logger:
    """
    统一的回测日志配置

    Args:
        output_dir: 输出目录
        log_name: 日志文件名（不含扩展名）
        level: 日志级别（默认INFO）
        console: 是否输出到控制台（默认True）

    Returns:
        配置好的Logger实例
    """
    # 创建输出目录
    os.makedirs(output_dir, exist_ok=True)

    # 日志文件路径
    log_file = os.path.join(output_dir, f'{log_name}.log')

    # 配置日志格式
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    # 创建handlers
    handlers = [
        logging.FileHandler(log_file, encoding='utf-8')
    ]

    if console:
        handlers.append(logging.StreamHandler())

    # 配置日志
    logging.basicConfig(
        level=level,
        format=log_format,
        handlers=handlers,
        force=True  # 强制重新配置
    )

    # 返回logger
    logger = logging.getLogger(__name__)
    logger.info(f"日志已配置，输出到: {log_file}")

    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    获取logger实例

    Args:
        name: logger名称（默认使用调用模块的名称）

    Returns:
        Logger实例
    """
    return logging.getLogger(name or __name__)
