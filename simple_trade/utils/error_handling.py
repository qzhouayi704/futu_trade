#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
错误处理装饰器模块

提供统一的错误处理装饰器，减少重复的 try-except 代码
"""

import logging
from functools import wraps
from typing import Any, Callable, Optional, TypeVar, cast


# 定义泛型类型变量
F = TypeVar('F', bound=Callable[..., Any])


def handle_db_error(
    default_return: Any = None,
    log_prefix: str = "",
    logger: Optional[logging.Logger] = None
) -> Callable[[F], F]:
    """
    数据库错误处理装饰器

    自动捕获数据库操作中的异常，记录日志并返回默认值。

    Args:
        default_return: 发生错误时的返回值（默认 None）
        log_prefix: 日志消息前缀（默认为空）
        logger: 自定义日志记录器（默认使用函数所在模块的logger）

    Returns:
        装饰器函数

    Example:
        >>> @handle_db_error(default_return=[], log_prefix="查询股票列表")
        >>> def get_stocks(self):
        ...     return self.db.query("SELECT * FROM stocks")
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # 使用自定义logger或函数所在模块的logger
                log = logger or logging.getLogger(func.__module__)

                # 构建日志消息
                func_name = func.__name__
                if log_prefix:
                    message = f"{log_prefix}失败 ({func_name}): {e}"
                else:
                    message = f"{func_name} 失败: {e}"

                log.error(message, exc_info=True)
                return default_return

        return cast(F, wrapper)

    return decorator


def handle_api_error(
    default_return: Any = None,
    log_prefix: str = "",
    logger: Optional[logging.Logger] = None,
    raise_on_error: bool = False
) -> Callable[[F], F]:
    """
    API错误处理装饰器

    自动捕获API调用中的异常，记录日志并返回默认值或重新抛出异常。

    Args:
        default_return: 发生错误时的返回值（默认 None）
        log_prefix: 日志消息前缀（默认为空）
        logger: 自定义日志记录器（默认使用函数所在模块的logger）
        raise_on_error: 是否重新抛出异常（默认 False）

    Returns:
        装饰器函数

    Example:
        >>> @handle_api_error(default_return={}, log_prefix="获取行情数据")
        >>> def get_quote(self, stock_code):
        ...     return self.api.get_quote(stock_code)
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # 使用自定义logger或函数所在模块的logger
                log = logger or logging.getLogger(func.__module__)

                # 构建日志消息
                func_name = func.__name__
                if log_prefix:
                    message = f"{log_prefix}失败 ({func_name}): {e}"
                else:
                    message = f"{func_name} 失败: {e}"

                log.error(message, exc_info=True)

                if raise_on_error:
                    raise

                return default_return

        return cast(F, wrapper)

    return decorator


def handle_error(
    default_return: Any = None,
    log_level: int = logging.ERROR,
    log_prefix: str = "",
    logger: Optional[logging.Logger] = None,
    suppress_exception: bool = True
) -> Callable[[F], F]:
    """
    通用错误处理装饰器

    提供更灵活的错误处理选项，适用于各种场景。

    Args:
        default_return: 发生错误时的返回值（默认 None）
        log_level: 日志级别（默认 ERROR）
        log_prefix: 日志消息前缀（默认为空）
        logger: 自定义日志记录器（默认使用函数所在模块的logger）
        suppress_exception: 是否抑制异常（默认 True，返回default_return；False则重新抛出）

    Returns:
        装饰器函数

    Example:
        >>> @handle_error(default_return=0, log_level=logging.WARNING)
        >>> def calculate_score(self, data):
        ...     return complex_calculation(data)
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # 使用自定义logger或函数所在模块的logger
                log = logger or logging.getLogger(func.__module__)

                # 构建日志消息
                func_name = func.__name__
                if log_prefix:
                    message = f"{log_prefix}失败 ({func_name}): {e}"
                else:
                    message = f"{func_name} 失败: {e}"

                # 根据日志级别记录
                log.log(log_level, message, exc_info=True)

                if not suppress_exception:
                    raise

                return default_return

        return cast(F, wrapper)

    return decorator


def retry_on_error(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
    logger: Optional[logging.Logger] = None
) -> Callable[[F], F]:
    """
    错误重试装饰器

    在发生指定异常时自动重试，支持指数退避。

    Args:
        max_retries: 最大重试次数（默认 3）
        delay: 初始延迟时间（秒，默认 1.0）
        backoff: 退避系数（默认 2.0，每次重试延迟时间翻倍）
        exceptions: 需要重试的异常类型元组（默认所有异常）
        logger: 自定义日志记录器

    Returns:
        装饰器函数

    Example:
        >>> @retry_on_error(max_retries=3, delay=1.0)
        >>> def fetch_data(self, url):
        ...     return requests.get(url)
    """
    import time

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            log = logger or logging.getLogger(func.__module__)
            func_name = func.__name__

            current_delay = delay
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_retries:
                        log.error(f"{func_name} 失败，已达最大重试次数 {max_retries}: {e}")
                        raise

                    log.warning(
                        f"{func_name} 失败 (尝试 {attempt + 1}/{max_retries + 1}): {e}，"
                        f"{current_delay:.1f}秒后重试..."
                    )
                    time.sleep(current_delay)
                    current_delay *= backoff

            # 不应该到达这里
            return None

        return cast(F, wrapper)

    return decorator
