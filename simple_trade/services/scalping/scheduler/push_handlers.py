#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scalping 推送处理器

利用 Futu 的订阅推送回调（TickerHandlerBase / OrderBookHandlerBase）接收数据，
替代主动轮询，大幅减少 OpenD 请求量。

推送到达后更新共享缓存，轮询器变为低频 fallback。
"""

import time
import logging
import threading
from typing import Dict, Optional, Callable

try:
    from futu import TickerHandlerBase, OrderBookHandlerBase, RET_OK
    FUTU_AVAILABLE = True
except ImportError:
    FUTU_AVAILABLE = False
    RET_OK = 0

    class TickerHandlerBase:
        def on_recv_rsp(self, rsp_pb):
            return 0, None

    class OrderBookHandlerBase:
        def on_recv_rsp(self, rsp_pb):
            return 0, None

logger = logging.getLogger(__name__)


class PushDataCache:
    """线程安全的推送数据缓存

    Scalping 的 TickerPoller / OrderBookPoller 可以先查缓存，
    只有缓存过期时才回退为 API 轮询。
    """

    def __init__(self, ttl: float = 30.0):
        """
        Args:
            ttl: 缓存有效期（秒），超过此时间视为过期
        """
        self._ttl = ttl
        self._lock = threading.Lock()
        self._ticker_cache: Dict[str, dict] = {}   # {stock_code: {data, timestamp}}
        self._orderbook_cache: Dict[str, dict] = {}
        self._stats = {"ticker_push": 0, "orderbook_push": 0}

    def put_ticker(self, stock_code: str, data) -> None:
        with self._lock:
            self._ticker_cache[stock_code] = {
                "data": data,
                "timestamp": time.monotonic(),
            }
            self._stats["ticker_push"] += 1

    def put_orderbook(self, stock_code: str, data) -> None:
        with self._lock:
            self._orderbook_cache[stock_code] = {
                "data": data,
                "timestamp": time.monotonic(),
            }
            self._stats["orderbook_push"] += 1

    def get_ticker(self, stock_code: str) -> Optional[object]:
        """获取缓存的 Ticker 数据，过期返回 None"""
        with self._lock:
            entry = self._ticker_cache.get(stock_code)
            if entry and (time.monotonic() - entry["timestamp"]) < self._ttl:
                return entry["data"]
            return None

    def get_orderbook(self, stock_code: str) -> Optional[object]:
        """获取缓存的 OrderBook 数据，过期返回 None"""
        with self._lock:
            entry = self._orderbook_cache.get(stock_code)
            if entry and (time.monotonic() - entry["timestamp"]) < self._ttl:
                return entry["data"]
            return None

    @property
    def stats(self) -> dict:
        with self._lock:
            return dict(self._stats)


# 全局单例
_push_cache = PushDataCache(ttl=30.0)


def get_push_cache() -> PushDataCache:
    return _push_cache


class ScalpingTickerHandler(TickerHandlerBase):
    """Ticker 推送处理器：接收逐笔成交推送，写入共享缓存"""

    def __init__(self, data_time_updater: Optional[Callable] = None):
        super().__init__()
        self._cache = get_push_cache()
        self._data_time_updater = data_time_updater

    def on_recv_rsp(self, rsp_pb):
        ret_code, data = super().on_recv_rsp(rsp_pb)
        if ret_code != RET_OK:
            return ret_code, data

        try:
            if data is not None and not data.empty:
                stock_code = data.iloc[0].get("code", "")
                if stock_code:
                    self._cache.put_ticker(stock_code, data)
                    # 更新最后数据时间（供健康检查使用）
                    if self._data_time_updater:
                        self._data_time_updater(stock_code, time.time())
                    logger.debug(f"[推送] Ticker {stock_code}: {len(data)} 笔")
        except Exception as e:
            logger.debug(f"[推送] Ticker 处理异常: {e}")

        return ret_code, data


class ScalpingOrderBookHandler(OrderBookHandlerBase):
    """OrderBook 推送处理器：接收摆盘推送，写入共享缓存"""

    def __init__(self, data_time_updater: Optional[Callable] = None):
        super().__init__()
        self._cache = get_push_cache()
        self._data_time_updater = data_time_updater

    def on_recv_rsp(self, rsp_pb):
        ret_code, data = super().on_recv_rsp(rsp_pb)
        if ret_code != RET_OK:
            return ret_code, data

        try:
            if data is not None:
                stock_code = data.get("code", "")
                if stock_code:
                    self._cache.put_orderbook(stock_code, data)
                    if self._data_time_updater:
                        self._data_time_updater(stock_code, time.time())
                    logger.debug(f"[推送] OrderBook {stock_code}")
        except Exception as e:
            logger.debug(f"[推送] OrderBook 处理异常: {e}")

        return ret_code, data
