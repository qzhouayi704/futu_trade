"""
重试装饰器
实现指数退避重试机制，区分可重试和不可重试错误
"""

import time
import logging
from functools import wraps
from typing import Callable, Optional, Tuple, Any


class RetryConfig:
    """重试配置"""

    def __init__(
        self,
        max_retries: int = 3,
        initial_backoff: float = 1.0,
        max_backoff: float = 32.0,
        backoff_multiplier: float = 2.0,
        retry_on_rate_limit: bool = True,
        retry_on_timeout: bool = True,
        retry_on_network_error: bool = True
    ):
        self.max_retries = max_retries
        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff
        self.backoff_multiplier = backoff_multiplier
        self.retry_on_rate_limit = retry_on_rate_limit
        self.retry_on_timeout = retry_on_timeout
        self.retry_on_network_error = retry_on_network_error


class ErrorType:
    """错误类型枚举"""
    RATE_LIMIT = "rate_limit"  # 频率限制
    TIMEOUT = "timeout"  # 超时
    NETWORK = "network"  # 网络错误
    QUOTA = "quota"  # 额度不足
    NOT_FOUND = "not_found"  # 股票不存在
    UNKNOWN = "unknown"  # 未知错误


def parse_error_type(error_msg: str) -> str:
    """
    解析错误类型

    Args:
        error_msg: 错误消息

    Returns:
        错误类型
    """
    error_msg_lower = error_msg.lower()

    # 检测频率限制
    if any(keyword in error_msg_lower for keyword in ["frequency", "频率", "rate limit", "too many"]):
        return ErrorType.RATE_LIMIT

    # 检测超时
    if any(keyword in error_msg_lower for keyword in ["timeout", "超时", "timed out"]):
        return ErrorType.TIMEOUT

    # 检测网络错误
    if any(keyword in error_msg_lower for keyword in ["network", "网络", "connection", "连接"]):
        return ErrorType.NETWORK

    # 检测额度不足
    if any(keyword in error_msg_lower for keyword in ["quota", "额度", "limit exceeded"]):
        return ErrorType.QUOTA

    # 检测股票不存在
    if any(keyword in error_msg_lower for keyword in ["not found", "不存在", "invalid", "退市"]):
        return ErrorType.NOT_FOUND

    return ErrorType.UNKNOWN


def is_retryable_error(error_msg: str, config: RetryConfig) -> bool:
    """
    判断错误是否可重试

    Args:
        error_msg: 错误消息
        config: 重试配置

    Returns:
        是否可重试
    """
    error_type = parse_error_type(error_msg)

    if error_type == ErrorType.RATE_LIMIT:
        return config.retry_on_rate_limit
    elif error_type == ErrorType.TIMEOUT:
        return config.retry_on_timeout
    elif error_type == ErrorType.NETWORK:
        return config.retry_on_network_error
    elif error_type in [ErrorType.QUOTA, ErrorType.NOT_FOUND]:
        return False  # 额度不足和股票不存在不可重试
    else:
        return False  # 未知错误默认不重试


def retry_with_backoff(config: Optional[RetryConfig] = None):
    """
    重试装饰器（指数退避）

    Args:
        config: 重试配置，如果为None则使用默认配置

    Returns:
        装饰器函数
    """
    if config is None:
        config = RetryConfig()

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            logger = logging.getLogger(func.__module__)
            last_error = None

            for attempt in range(config.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    error_msg = str(e)

                    # 最后一次尝试，不再重试
                    if attempt >= config.max_retries:
                        logger.error(
                            f"{func.__name__} 失败，已达最大重试次数 {config.max_retries}，"
                            f"错误: {error_msg}"
                        )
                        raise

                    # 判断是否可重试
                    if not is_retryable_error(error_msg, config):
                        logger.warning(
                            f"{func.__name__} 遇到不可重试错误: {error_msg}"
                        )
                        raise

                    # 计算退避时间
                    backoff_time = min(
                        config.initial_backoff * (config.backoff_multiplier ** attempt),
                        config.max_backoff
                    )

                    error_type = parse_error_type(error_msg)
                    logger.warning(
                        f"{func.__name__} 失败（第 {attempt + 1}/{config.max_retries + 1} 次），"
                        f"错误类型: {error_type}，{backoff_time:.2f} 秒后重试，"
                        f"错误: {error_msg}"
                    )

                    time.sleep(backoff_time)

            # 理论上不会到这里，但为了安全起见
            if last_error:
                raise last_error

        return wrapper
    return decorator


def create_retry_decorator(
    max_retries: int = 3,
    initial_backoff: float = 1.0,
    max_backoff: float = 32.0,
    backoff_multiplier: float = 2.0
):
    """
    创建自定义重试装饰器

    Args:
        max_retries: 最大重试次数
        initial_backoff: 初始退避时间（秒）
        max_backoff: 最大退避时间（秒）
        backoff_multiplier: 退避倍数

    Returns:
        重试装饰器
    """
    config = RetryConfig(
        max_retries=max_retries,
        initial_backoff=initial_backoff,
        max_backoff=max_backoff,
        backoff_multiplier=backoff_multiplier
    )
    return retry_with_backoff(config)
