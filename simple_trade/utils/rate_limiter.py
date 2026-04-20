"""
全局频率控制器
实现滑动窗口频率限制，确保API请求不超过限制
"""

import time
import threading
from typing import Optional
from collections import deque
import logging


class RateLimiter:
    """滑动窗口频率限制器（线程安全）"""

    def __init__(self, max_requests: int = 60, time_window: int = 30):
        """
        初始化频率限制器

        Args:
            max_requests: 时间窗口内最大请求数
            time_window: 时间窗口（秒）
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = deque()  # 使用deque提高性能
        self.lock = threading.Lock()
        self.logger = logging.getLogger(__name__)
        # 日志降噪状态
        self._throttle_count = 0
        self._total_wait_time = 0.0
        self._last_summary_time = 0.0

    def wait_if_needed(self) -> float:
        """
        如果需要，等待直到可以发送请求

        Returns:
            等待时间（秒）
        """
        total_wait = 0.0

        while True:
            with self.lock:
                current_time = time.time()

                # 移除时间窗口外的请求记录
                while self.requests and self.requests[0] < current_time - self.time_window:
                    self.requests.popleft()

                # 检查是否超过限制
                if len(self.requests) < self.max_requests:
                    # 有余量，记录本次请求并放行
                    self.requests.append(current_time)
                    return total_wait

                # 计算需要等待的时间
                oldest_request = self.requests[0]
                wait_time = oldest_request + self.time_window - current_time + 0.1

                if wait_time <= 0:
                    # 窗口已过期，记录并放行
                    self.requests.append(current_time)
                    return total_wait

                # 日志降噪
                self._throttle_count += 1
                self._total_wait_time += wait_time

                if self._throttle_count == 1:
                    self.logger.warning(
                        f"达到频率限制（{self.max_requests}次/{self.time_window}秒），"
                        f"等待 {wait_time:.2f} 秒"
                    )
                    self._last_summary_time = current_time
                elif (current_time - self._last_summary_time) >= 30:
                    self.logger.info(
                        f"频率限制汇总: 过去30秒共限流 {self._throttle_count} 次，"
                        f"累计等待 {self._total_wait_time:.1f}s"
                    )
                    self._throttle_count = 0
                    self._total_wait_time = 0.0
                    self._last_summary_time = current_time
                else:
                    self.logger.debug(
                        f"频率限制等待 {wait_time:.2f}s "
                        f"(本轮第 {self._throttle_count} 次)"
                    )

            # 在锁外等待，不阻塞其他线程的检查
            time.sleep(wait_time)
            total_wait += wait_time
            # 循环回去重新竞争锁，确保不会突发

    def add_delay(self, delay: float):
        """
        添加固定延迟（兼容旧代码）

        Args:
            delay: 延迟时间（秒）
        """
        if delay > 0:
            time.sleep(delay)

    def reset(self):
        """重置频率限制器"""
        with self.lock:
            self.requests.clear()

    def get_current_rate(self) -> int:
        """
        获取当前时间窗口内的请求数

        Returns:
            当前请求数
        """
        with self.lock:
            current_time = time.time()
            # 移除时间窗口外的请求记录
            while self.requests and self.requests[0] < current_time - self.time_window:
                self.requests.popleft()
            return len(self.requests)

    def update_limits(self, max_requests: Optional[int] = None, time_window: Optional[int] = None):
        """
        动态更新限流参数

        Args:
            max_requests: 新的最大请求数
            time_window: 新的时间窗口
        """
        with self.lock:
            if max_requests is not None:
                self.max_requests = max_requests
            if time_window is not None:
                self.time_window = time_window
            self.logger.info(f"更新频率限制参数: {self.max_requests}次/{self.time_window}秒")


# 全局单例实例
_global_rate_limiter: Optional[RateLimiter] = None
_global_lock = threading.Lock()


def get_global_rate_limiter(max_requests: int = 60, time_window: int = 30) -> RateLimiter:
    """
    获取全局频率限制器单例

    Args:
        max_requests: 时间窗口内最大请求数
        time_window: 时间窗口（秒）

    Returns:
        全局频率限制器实例
    """
    global _global_rate_limiter
    if _global_rate_limiter is None:
        with _global_lock:
            if _global_rate_limiter is None:
                _global_rate_limiter = RateLimiter(max_requests, time_window)
    return _global_rate_limiter


# ========== 兼容性便捷函数 ==========

# 按 API 名称分组的限流器
_api_limiters: dict = {}
_api_limiters_lock = threading.Lock()


# 各 API 实际限频配置（来自富途官方文档 / 实际错误提示）
_API_RATE_LIMITS = {
    'get_plate_stock': (10, 30),   # "每30秒最多10次"
    'get_plate_list': (10, 30),
    'default': (60, 30),
}


def _get_api_limiter(api_name: str) -> RateLimiter:
    """获取指定 API 的限流器"""
    if api_name not in _api_limiters:
        with _api_limiters_lock:
            if api_name not in _api_limiters:
                max_req, window = _API_RATE_LIMITS.get(api_name, _API_RATE_LIMITS['default'])
                _api_limiters[api_name] = RateLimiter(max_requests=max_req, time_window=window)
    return _api_limiters[api_name]


def get_rate_limiter(max_requests: int = 60, time_window: int = 30) -> RateLimiter:
    """获取全局频率限制器（get_global_rate_limiter 的别名）"""
    return get_global_rate_limiter(max_requests, time_window)


def wait_for_api(api_name: str = 'default') -> float:
    """
    等待直到指定 API 可以调用

    Args:
        api_name: API 名称

    Returns:
        等待时间（秒）
    """
    limiter = _get_api_limiter(api_name)
    return limiter.wait_if_needed()


def record_api_call(api_name: str = 'default'):
    """记录一次API调用（兼容旧代码，wait_for_api已内含记录逻辑）"""
    pass


def can_call_api(api_name: str = 'default') -> bool:
    """
    检查指定 API 是否可以调用（不等待）

    Args:
        api_name: API 名称

    Returns:
        是否可以调用
    """
    limiter = _get_api_limiter(api_name)
    return limiter.get_current_rate() < limiter.max_requests


def get_api_status(api_name: str = 'default') -> dict:
    """
    获取指定 API 的频率状态

    Args:
        api_name: API 名称

    Returns:
        {'current_rate': int, 'max_requests': int, 'time_window': int}
    """
    limiter = _get_api_limiter(api_name)
    return {
        'current_rate': limiter.get_current_rate(),
        'max_requests': limiter.max_requests,
        'time_window': limiter.time_window,
    }
