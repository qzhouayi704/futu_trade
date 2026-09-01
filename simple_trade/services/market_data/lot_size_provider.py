#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每手股数(lot_size)提供者 — 按股票取真实每手股数，替代全局硬编码100。

港股每手股数按股票而定：常见 100/500/1000/2000，也有小于100的（几十股一手）。
硬编码100会两头出错：小手数股票被误拒或取整成0，大手数股票下出非整手单被券商打回。

数据源：富途快照的 lot_size 字段。lot_size 极少变动，进程内长期缓存；
取不到时 get() 返回 None，由调用方决定回退口径（下单路径不回退、宁可放行让券商判定；
取整路径回退 DEFAULT_LOT_SIZE 以免把数量抹成0）。
"""

import logging
import threading
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_LOT_SIZE = 100  # 富途不可用时的保守回退（港股最常见的每手股数）

_BATCH_SIZE = 200  # 富途快照单次请求上限


class LotSizeProvider:
    """按股票代码提供每手股数，带进程内缓存。线程安全。"""

    def __init__(self, futu_client: Any = None):
        self._futu_client = futu_client
        self._cache: Dict[str, int] = {}
        self._lock = threading.Lock()

    def set_futu_client(self, futu_client: Any) -> None:
        self._futu_client = futu_client

    # ---------- 查询 ----------

    def get(self, stock_code: str) -> Optional[int]:
        """返回该股每手股数；富途不可用或无此字段时返回 None（不猜）。"""
        if not stock_code:
            return None
        with self._lock:
            cached = self._cache.get(stock_code)
        if cached:
            return cached
        return self._fetch([stock_code]).get(stock_code)

    def get_or_default(self, stock_code: str, default: int = DEFAULT_LOT_SIZE) -> int:
        """返回每手股数，取不到时用 default（默认100）。"""
        return self.get(stock_code) or default

    def prefetch(self, stock_codes: Iterable[str]) -> Dict[str, int]:
        """批量预热缓存，返回本次已知的 {code: lot_size}（含缓存命中的）。"""
        codes = [c for c in dict.fromkeys(stock_codes or []) if c]
        if not codes:
            return {}
        with self._lock:
            known = {c: self._cache[c] for c in codes if c in self._cache}
        missing = [c for c in codes if c not in known]
        if missing:
            known.update(self._fetch(missing))
        return known

    # ---------- 取整 ----------

    def floor_to_lot(self, stock_code: str, quantity: int,
                     default: int = DEFAULT_LOT_SIZE) -> int:
        """向下取整到该股整手（不足一手返回0）。"""
        try:
            qty = int(quantity or 0)
        except (TypeError, ValueError):
            return 0
        if qty <= 0:
            return 0
        lot = self.get_or_default(stock_code, default)
        if lot <= 0:
            lot = 1
        return (qty // lot) * lot

    def is_valid_quantity(self, stock_code: str, quantity: int) -> bool:
        """数量是否为该股整手的整数倍；每手股数未知时一律放行（交由券商判定）。"""
        try:
            qty = int(quantity or 0)
        except (TypeError, ValueError):
            return False
        if qty <= 0:
            return False
        lot = self.get(stock_code)
        if not lot or lot <= 0:
            return True
        return qty % lot == 0

    # ---------- 内部 ----------

    def _resolve_client(self) -> Any:
        if self._futu_client is not None:
            return self._futu_client
        try:
            from ...dependencies import get_container
            self._futu_client = getattr(get_container(), 'futu_client', None)
        except Exception as e:
            logger.debug(f"[每手股数] 解析 futu_client 失败: {e}")
        return self._futu_client

    def _fetch(self, codes: List[str]) -> Dict[str, int]:
        client = self._resolve_client()
        if client is None or not client.is_available():
            return {}

        found: Dict[str, int] = {}
        for i in range(0, len(codes), _BATCH_SIZE):
            batch = codes[i:i + _BATCH_SIZE]
            try:
                ret, data = client.get_market_snapshot(batch)
                if ret != 0 or data is None or getattr(data, 'empty', True):
                    continue
                for _, row in data.iterrows():
                    code = row.get('code', '')
                    raw = row.get('lot_size', 0)
                    try:
                        lot = int(raw or 0)
                    except (TypeError, ValueError):
                        lot = 0
                    if code and lot > 0:
                        found[code] = lot
            except Exception as e:
                logger.warning(f"[每手股数] 快照获取失败 {batch[:3]}...: {e}")

        if found:
            with self._lock:
                self._cache.update(found)
        return found


# ==================== 模块级单例 ====================

_provider: Optional[LotSizeProvider] = None
_provider_lock = threading.Lock()


def get_lot_size_provider() -> LotSizeProvider:
    """获取全局 LotSizeProvider（futu_client 首次使用时从容器懒解析）。"""
    global _provider
    if _provider is None:
        with _provider_lock:
            if _provider is None:
                _provider = LotSizeProvider()
    return _provider
