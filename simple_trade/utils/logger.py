#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日志配置工具

提供两种输出方式：
1. logging - 详细日志写入文件，控制台只显示警告和错误
2. print_status - 简洁的状态信息打印到控制台
"""

import logging
import os
import sys
import platform
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from typing import Optional


def setup_logging(log_file: Optional[str] = None, log_level: str = 'INFO', console_level: str = 'INFO', use_rotation: bool = True) -> None:
    """设置日志配置

    Args:
        log_file: 日志文件路径（不含日期后缀）
        log_level: 文件日志级别（默认INFO）
        console_level: 控制台日志级别（默认INFO，用于调试监控问题）
        use_rotation: 是否使用按日期轮转（默认True，每天一个文件）
                     注意：Windows 多进程环境下会自动禁用轮转以避免文件锁冲突
    """

    # 确保日志目录存在
    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
    else:
        os.makedirs('data', exist_ok=True)
        log_file = 'data/system.log'

    # Windows 多进程环境下禁用日志轮转，避免文件锁冲突
    # TimedRotatingFileHandler 在 Windows 下多进程同时轮转会导致 PermissionError
    is_windows = platform.system() == 'Windows'
    if is_windows and use_rotation:
        use_rotation = False
        # 只在主进程输出警告（避免多进程重复输出）
        if not hasattr(setup_logging, '_warned'):
            print(f"[警告] Windows 环境下已禁用日志轮转以避免多进程文件锁冲突", file=sys.stderr)
            setup_logging._warned = True

    # 设置日志级别
    level_map = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL
    }
    file_level = level_map.get(log_level.upper(), logging.INFO)
    console_log_level = level_map.get(console_level.upper(), logging.WARNING)

    # 配置日志格式（文件用详细格式，控制台用简洁格式）
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_formatter = logging.Formatter(
        '%(levelname)s: %(message)s'
    )

    # 清除现有的处理器
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # 文件处理器 - 使用按日期轮转或普通文件处理器
    try:
        if use_rotation:
            # 使用 TimedRotatingFileHandler 按日期轮转
            # when='midnight' 表示每天午夜轮转
            # interval=1 表示每1天轮转一次
            # backupCount=30 表示保留最近30天的日志
            file_handler = TimedRotatingFileHandler(
                log_file,
                when='midnight',
                interval=1,
                backupCount=30,
                encoding='utf-8'
            )
            # 设置日志文件名后缀格式为 .YYYY-MM-DD
            file_handler.suffix = "%Y-%m-%d"
        else:
            file_handler = logging.FileHandler(log_file, encoding='utf-8')

        file_handler.setLevel(file_level)
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
    except Exception as e:
        print(f"无法创建文件日志处理器: {e}")

    # 控制台处理器 - 临时使用INFO级别用于调试监控问题
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_log_level)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # 设置根日志级别（使用较低的级别以便文件能记录所有日志）
    root_logger.setLevel(min(file_level, console_log_level))

    # 抑制第三方库的冗余日志
    for lib in ['werkzeug', 'urllib3', 'engineio', 'socketio', 'futu',
                'uvicorn.access']:
        logging.getLogger(lib).setLevel(logging.ERROR)

    rotation_info = "按日期轮转" if use_rotation else "单文件"
    logging.info(f"日志系统已初始化 - 文件级别: {log_level}, 控制台级别: {console_level}, 模式: {rotation_info}, 文件: {log_file}")


def get_logger(name: str) -> logging.Logger:
    """获取指定名称的日志器"""
    return logging.getLogger(name)


def set_log_level(level: str) -> None:
    """动态设置日志级别"""
    level_map = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL
    }

    log_level = level_map.get(level.upper(), logging.INFO)
    logging.getLogger().setLevel(log_level)

    # 同时设置所有处理器的级别
    for handler in logging.getLogger().handlers:
        handler.setLevel(log_level)

    logging.info(f"日志级别已设置为: {level}")


def print_status(message: str, status: str = 'info') -> None:
    """打印简洁的状态信息到控制台

    用于显示关键步骤的状态，不会被日志级别过滤

    Args:
        message: 状态消息
        status: 状态类型 ('info', 'ok', 'warn', 'error')
    """
    symbols = {
        'info': '[*]',
        'ok': '[+]',
        'warn': '[!]',
        'error': '[-]'
    }
    symbol = symbols.get(status, '[*]')
    time_str = datetime.now().strftime('%H:%M:%S')
    print(f"{time_str} {symbol} {message}", flush=True)

    # 同时写入日志文件
    log_level = {'info': logging.INFO, 'ok': logging.INFO, 'warn': logging.WARNING, 'error': logging.ERROR}
    logging.log(log_level.get(status, logging.INFO), message)
