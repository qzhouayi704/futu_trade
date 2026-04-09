"""
令牌桶限流器（Token Bucket Rate Limiter）

控制 futu API 调用频率不超过安全阈值，避免触发频率限制。
使用令牌桶算法，支持异步等待和公平排队。
"""

import asyncio
import time
import logging

logger = logging.getLogger("scalping.rate_limiter")


class RateLimiter:
    """令牌桶限流器

    默认 25 tokens/sec（futu 限制约 30 次/秒，预留 5 次余量）。
    多个协程同时请求时按到达顺序公平分配。
    """

    def __init__(self, rate: float = 25.0, capacity: int = 25):
        """初始化限流器

        Args:
            rate: 令牌生成速率（个/秒）
            capacity: 桶容量（最大令牌数）
        """
        self._rate = rate
        self._capacity = capacity
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        """补充令牌（根据时间流逝计算）"""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            self._capacity,
            self._tokens + elapsed * self._rate,
        )
        self._last_refill = now

    async def acquire(self) -> None:
        """获取一个令牌，无令牌时异步等待

        使用 asyncio.Lock 保证公平排队（FIFO）。
        """
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                # 计算需要等待的时间
                wait_time = (1.0 - self._tokens) / self._rate
            await asyncio.sleep(wait_time)

    @property
    def available_tokens(self) -> float:
        """当前可用令牌数（近似值，不加锁）"""
        self._refill()
        return self._tokens
