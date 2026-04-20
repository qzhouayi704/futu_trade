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

    # Windows 多进程环境下 TimedRotatingFileHandler 会导致 PermissionError
    # 改用 RotatingFileHandler 按大小轮转，避免文件锁冲突
    is_windows = platform.system() == 'Windows'
    if is_windows and use_rotation:
        use_rotation = False  # 标记禁用时间轮转，下面改用大小轮转

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

    # 文件处理器
    try:
        if use_rotation:
            # 非 Windows：按日期轮转，保留30天
            file_handler = TimedRotatingFileHandler(
                log_file,
                when='midnight',
                interval=1,
                backupCount=30,
                encoding='utf-8'
            )
            file_handler.suffix = "%Y-%m-%d"
            rotation_info = "按日期轮转(30天)"
        elif is_windows:
            # Windows：按大小轮转，10MB × 7个备份 ≈ 最大80MB
            from logging.handlers import RotatingFileHandler
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=10 * 1024 * 1024,  # 10MB
                backupCount=7,
                encoding='utf-8'
            )
            rotation_info = "按大小轮转(10MB×7)"
        else:
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            rotation_info = "单文件(无轮转)"

        file_handler.setLevel(file_level)
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
    except Exception as e:
        print(f"无法创建文件日志处理器: {e}")

    # 独立的错误日志文件（只记录 ERROR+，方便快速定位问题）
    try:
        error_log_file = log_file.replace('.log', '.error.log') if log_file else 'data/system.error.log'
        if is_windows:
            from logging.handlers import RotatingFileHandler as _RotatingFileHandler
            error_handler = _RotatingFileHandler(
                error_log_file,
                maxBytes=5 * 1024 * 1024,  # 5MB
                backupCount=5,
                encoding='utf-8'
            )
        else:
            error_handler = TimedRotatingFileHandler(
                error_log_file,
                when='midnight',
                interval=1,
                backupCount=30,
                encoding='utf-8'
            )
            error_handler.suffix = "%Y-%m-%d"
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(file_formatter)
        root_logger.addHandler(error_handler)
    except Exception as e:
        print(f"无法创建错误日志处理器: {e}")

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

    # 降级高频模块日志（每5秒执行一次的模块只记录WARNING+）
    for noisy_module in [
        'simple_trade.api.subscription_optimizer',
        'simple_trade.api.quote_service',
        'scalping.health_monitor',
    ]:
        logging.getLogger(noisy_module).setLevel(logging.WARNING)

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


class FlowLogger:
    """流程日志器 - 在关键节点输出结构化摘要

    用法:
        flow = FlowLogger("系统启动")
        flow.step("数据库初始化", stocks=120, plates=8)
        flow.step("订阅完成", subscribed=50, failed=3)
        flow.end(success=True)

    输出格式:
        ▶ [系统启动] 开始
        ├ [系统启动] 数据库初始化 | stocks=120 plates=8 (1.2s)
        ├ [系统启动] 订阅完成 | subscribed=50 failed=3 (3.4s)
        ◀ [系统启动] 完成 | 总耗时=4.6s steps=2
    """

    def __init__(self, flow_name: str, logger_name: str = None):
        self.flow_name = flow_name
        self.logger = logging.getLogger(logger_name or 'flow')
        self._start_time = datetime.now()
        self._step_time = self._start_time
        self._step_count = 0
        self._errors = []
        self.logger.info(f"▶ [{self.flow_name}] 开始")

    def step(self, action: str, **metrics):
        """记录流程步骤及关键指标"""
        now = datetime.now()
        elapsed = (now - self._step_time).total_seconds()
        self._step_time = now
        self._step_count += 1

        metrics_str = ' '.join(f"{k}={v}" for k, v in metrics.items())
        msg = f"├ [{self.flow_name}] {action}"
        if metrics_str:
            msg += f" | {metrics_str}"
        msg += f" ({elapsed:.1f}s)"
        self.logger.info(msg)

    def warn(self, action: str, **metrics):
        """记录流程警告"""
        metrics_str = ' '.join(f"{k}={v}" for k, v in metrics.items())
        msg = f"├ [{self.flow_name}] ⚠ {action}"
        if metrics_str:
            msg += f" | {metrics_str}"
        self.logger.warning(msg)

    def error(self, action: str, err: Exception = None, **metrics):
        """记录流程错误"""
        self._errors.append(action)
        metrics_str = ' '.join(f"{k}={v}" for k, v in metrics.items())
        msg = f"├ [{self.flow_name}] ✖ {action}"
        if metrics_str:
            msg += f" | {metrics_str}"
        if err:
            msg += f" | error={err}"
        self.logger.error(msg)

    def end(self, success: bool = True, **metrics):
        """结束流程并输出摘要"""
        total = (datetime.now() - self._start_time).total_seconds()
        status = "完成" if success else "失败"
        metrics_str = ' '.join(f"{k}={v}" for k, v in metrics.items())
        msg = f"◀ [{self.flow_name}] {status} | 总耗时={total:.1f}s steps={self._step_count}"
        if self._errors:
            msg += f" errors={len(self._errors)}"
        if metrics_str:
            msg += f" {metrics_str}"
        level = logging.INFO if success else logging.ERROR
        self.logger.log(level, msg)
        # 同时输出到控制台
        print_status(msg, 'ok' if success else 'error')


def get_flow_logger(flow_name: str) -> FlowLogger:
    """快捷获取流程日志器"""
    return FlowLogger(flow_name)
