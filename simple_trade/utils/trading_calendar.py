#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交易日历

基于 FUTU `request_trading_days` 接口判断某市场某天是否为交易日（含节假日）。
按自然日缓存「今天 ± 窗口」的交易日集合，供盘中高频判断复用。

设计原则 —— **fail-open**：
当 OpenD 不可用 / 接口失败 / 查询日超出缓存窗口等无法确定的情况下，
一律视为「交易日」(返回 True)，绝不因日历问题误拦真实交易日导致信号停摆。
只有当日历**明确**表示当天非交易日时才返回 False。
"""

import logging
import threading
import time as _time
from datetime import date, datetime, timedelta
from typing import Dict, Optional, Set, Tuple

logger = logging.getLogger("trading_calendar")

# 拉取窗口：今天往前 30 天、往后 15 天 —— 足够日内判断，也容纳跨周/跨节缓存
_LOOKBACK_DAYS = 30
_LOOKAHEAD_DAYS = 15
# 刷新失败后的冷却（秒）：避免 OpenD 不可用时每个监控周期都重试并阻塞管道
_FAILURE_COOLDOWN = 300.0


class TradingCalendar:
    """市场交易日历（线程安全，按天缓存，fail-open）"""

    def __init__(self):
        self._futu_client = None
        self._cache: Dict[str, Set[str]] = {}          # market -> {'YYYY-MM-DD', ...}
        self._window: Dict[str, Tuple[str, str]] = {}  # market -> (start, end)
        self._built_on: Dict[str, str] = {}            # market -> 'YYYY-MM-DD'(缓存构建日)
        self._last_fail_ts: Dict[str, float] = {}      # market -> monotonic 上次失败时刻
        self._lock = threading.Lock()                  # 保护缓存读写
        self._refresh_lock = threading.Lock()          # 串行化刷新，避免并发重复拉取

    def set_futu_client(self, futu_client) -> None:
        """显式注入 FutuClient（可选；未注入时按需经容器懒解析）"""
        self._futu_client = futu_client

    def _resolve_client(self):
        if self._futu_client is not None:
            return self._futu_client
        try:
            from ..dependencies import get_container
            self._futu_client = getattr(get_container(), 'futu_client', None)
        except Exception:
            self._futu_client = None
        return self._futu_client

    def _refresh(self, market: str, today_str: str) -> bool:
        """拉取并缓存指定市场的交易日窗口。返回是否刷新成功。"""
        with self._refresh_lock:
            # 二次确认：可能已被其它线程刚刷新
            with self._lock:
                if (self._built_on.get(market) == today_str
                        and self._cache.get(market) is not None):
                    return True

            # 失败冷却：近期刚失败过则不重试，保持 fail-open、不阻塞管道
            last_fail = self._last_fail_ts.get(market, 0.0)
            if last_fail and (_time.monotonic() - last_fail) < _FAILURE_COOLDOWN:
                return False

            client = self._resolve_client()
            if client is None or not getattr(client, 'is_available', lambda: False)():
                self._last_fail_ts[market] = _time.monotonic()
                # 显式落日志：历史上此处静默返回，导致节假日闸长期 fail-open 而无人察觉
                logger.warning(
                    "[交易日历] %s 刷新跳过：富途客户端%s → fail-open 当作交易日"
                    "（节假日闸暂不生效，%.0fs 后重试）",
                    market,
                    "未注入/未解析" if client is None else "未就绪(is_available=False)",
                    _FAILURE_COOLDOWN,
                )
                return False

            try:
                d = datetime.strptime(today_str, '%Y-%m-%d').date()
                start = (d - timedelta(days=_LOOKBACK_DAYS)).isoformat()
                end = (d + timedelta(days=_LOOKAHEAD_DAYS)).isoformat()
                ret, data = client.request_trading_days(
                    market=market, start=start, end=end
                )

                from ..api.futu_client import RET_OK
                if ret != RET_OK or not isinstance(data, (list, tuple)):
                    self._last_fail_ts[market] = _time.monotonic()
                    logger.warning(f"[交易日历] {market} 接口返回异常: ret={ret}, data={data}")
                    return False

                days: Set[str] = set()
                for item in data:
                    t = item.get('time') if isinstance(item, dict) else None
                    if t:
                        days.add(str(t)[:10])

                with self._lock:
                    self._cache[market] = days
                    self._window[market] = (start, end)
                    self._built_on[market] = today_str
                self._last_fail_ts.pop(market, None)
                logger.info(
                    f"[交易日历] {market} 已刷新: {len(days)} 个交易日 ({start}~{end})"
                )
                return True
            except Exception as e:
                self._last_fail_ts[market] = _time.monotonic()
                logger.warning(f"[交易日历] {market} 刷新失败: {e}")
                return False

    def is_trading_day(self, market: str, day: Optional[date] = None) -> bool:
        """判断 `market` 在 `day` 是否为交易日。无法确定时 fail-open 返回 True。"""
        if day is None:
            day = datetime.now().date()
        day_str = day.isoformat()
        today_str = datetime.now().date().isoformat()

        with self._lock:
            built_on = self._built_on.get(market)
            cached = self._cache.get(market)
            window = self._window.get(market)

        # 缓存缺失或非当天构建 → 尝试刷新（每自然日一次，失败有冷却）
        if cached is None or built_on != today_str:
            self._refresh(market, today_str)
            with self._lock:
                cached = self._cache.get(market)
                window = self._window.get(market)

        if cached is None or window is None:
            return True  # fail-open：拿不到日历

        start, end = window
        if not (start <= day_str <= end):
            return True  # 查询日超出缓存窗口，无法判断 → fail-open

        return day_str in cached


_calendar_singleton: Optional[TradingCalendar] = None
_singleton_lock = threading.Lock()


def get_trading_calendar() -> TradingCalendar:
    """获取进程内唯一的交易日历实例"""
    global _calendar_singleton
    if _calendar_singleton is None:
        with _singleton_lock:
            if _calendar_singleton is None:
                _calendar_singleton = TradingCalendar()
    return _calendar_singleton
