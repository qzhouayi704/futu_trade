"""
异步重试工具
提供异步函数的重试机制，支持超时控制和指数退避
"""

import asyncio
import logging
from typing import Callable, Any, Optional
from functools import wraps

from simple_trade.utils.retry_helper import (
    RetryConfig,
    parse_error_type,
    is_retryable_error,
    ErrorType
)


async def async_retry_with_timeout(
    func: Callable,
    *args,
    config: RetryConfig,
    timeout: float,
    logger: Optional[logging.Logger] = None,
    **kwargs
) -> Any:
    """
    异步重试包装器（支持超时控制）

    Args:
        func: 要执行的异步函数
        *args: 函数参数
        config: 重试配置
        timeout: 超时时间（秒）
        logger: 日志记录器
        **kwargs: 函数关键字参数

    Returns:
        函数执行结果

    Raises:
        最后一次执行的异常
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    last_error = None
    func_name = getattr(func, '__name__', str(func))

    for attempt in range(config.max_retries + 1):
        try:
            # 执行函数并应用超时
            result = await asyncio.wait_for(
                func(*args, **kwargs),
                timeout=timeout
            )

            # 成功后重置错误计数
            if attempt > 0:
                logger.info(
                    f"{func_name} 重试成功（第 {attempt + 1} 次尝试）"
                )
            return result

        except asyncio.TimeoutError as e:
            last_error = e
            error_msg = f"timeout after {timeout}s"

            # 最后一次尝试，不再重试
            if attempt >= config.max_retries:
                logger.error(
                    f"{func_name} 超时失败，已达最大重试次数 {config.max_retries}"
                )
                raise

            # 判断是否可重试
            if not config.retry_on_timeout:
                logger.warning(f"{func_name} 超时，配置不允许重试")
                raise

            # 计算退避时间
            backoff_time = min(
                config.initial_backoff * (config.backoff_multiplier ** attempt),
                config.max_backoff
            )

            logger.warning(
                f"{func_name} 超时（第 {attempt + 1}/{config.max_retries + 1} 次），"
                f"{backoff_time:.2f} 秒后重试"
            )

            await asyncio.sleep(backoff_time)

        except Exception as e:
            last_error = e
            error_msg = str(e)

            # 最后一次尝试，不再重试
            if attempt >= config.max_retries:
                logger.error(
                    f"{func_name} 失败，已达最大重试次数 {config.max_retries}，"
                    f"错误: {error_msg}"
                )
                raise

            # 判断是否可重试
            if not is_retryable_error(error_msg, config):
                logger.warning(
                    f"{func_name} 遇到不可重试错误: {error_msg}"
                )
                raise

            # 计算退避时间
            backoff_time = min(
                config.initial_backoff * (config.backoff_multiplier ** attempt),
                config.max_backoff
            )

            error_type = parse_error_type(error_msg)
            logger.warning(
                f"{func_name} 失败（第 {attempt + 1}/{config.max_retries + 1} 次），"
                f"错误类型: {error_type}，{backoff_time:.2f} 秒后重试，"
                f"错误: {error_msg}"
            )

            await asyncio.sleep(backoff_time)

    # 理论上不会到这里，但为了安全起见
    if last_error:
        raise last_error


async def run_sync_with_retry(
    func: Callable,
    *args,
    timeout: float,
    retry_config: RetryConfig,
    logger: Optional[logging.Logger] = None,
    **kwargs
) -> Any:
    """
    在线程池中执行同步函数，带超时和重试

    Args:
        func: 要执行的同步函数
        *args: 函数参数
        timeout: 超时时间（秒）
        retry_config: 重试配置
        logger: 日志记录器
        **kwargs: 函数关键字参数

    Returns:
        函数执行结果

    Raises:
        最后一次执行的异常
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    loop = asyncio.get_running_loop()

    # 包装同步函数为异步函数
    async def async_wrapper():
        return await loop.run_in_executor(None, func, *args, **kwargs)

    # 使用异步重试包装器
    return await async_retry_with_timeout(
        async_wrapper,
        config=retry_config,
        timeout=timeout,
        logger=logger
    )


def async_retry_decorator(
    config: Optional[RetryConfig] = None,
    timeout: float = 10.0
):
    """
    异步重试装饰器

    Args:
        config: 重试配置，如果为None则使用默认配置
        timeout: 超时时间（秒）

    Returns:
        装饰器函数
    """
    if config is None:
        config = RetryConfig()

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            logger = logging.getLogger(func.__module__)
            return await async_retry_with_timeout(
                func,
                *args,
                config=config,
                timeout=timeout,
                logger=logger,
                **kwargs
            )
        return wrapper
    return decorator
