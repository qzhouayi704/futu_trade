"""Typed, timeout-bounded adapter for broker positions and active orders."""

import asyncio
from datetime import datetime, timezone
import threading
from typing import Protocol

from ...domain.enums import DataQuality
from ...domain.positions import (
    ActiveOrderSnapshot,
    PositionReconciliation,
    PositionSnapshot,
)


class FutuPositionSource(Protocol):
    def get_positions(self) -> dict: ...

    def get_orders(self, status_filter_list=None) -> dict: ...


class FutuPositionProvider:
    _TERMINAL_ORDER_SUFFIXES = (
        "FILLED_ALL",
        "CANCELLED_ALL",
        "CANCELLED_PART",
        "CANCELED_ALL",
        "CANCELED_PART",
        "FAILED",
        "DISABLED",
        "DELETED",
    )

    def __init__(
        self,
        source: FutuPositionSource | None = None,
        *,
        timeout_seconds: float = 8.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._source = source
        self._timeout = timeout_seconds
        self._last_active_orders: tuple[ActiveOrderSnapshot, ...] = ()
        self._lock = threading.RLock()

    @property
    def has_source(self) -> bool:
        return self._source is not None

    async def fetch(self) -> PositionReconciliation:
        as_of = datetime.now(timezone.utc)
        if self._source is None:
            return PositionReconciliation(
                as_of=as_of,
                positions=(),
                active_orders=(),
                authoritative=False,
                quality=DataQuality.INVALID,
                reason_codes=("POSITION_SOURCE_UNAVAILABLE",),
            )
        try:
            positions_result = await asyncio.wait_for(
                asyncio.to_thread(self._query_positions),
                timeout=self._timeout,
            )
        except Exception as error:
            return PositionReconciliation(
                as_of=as_of,
                positions=(),
                active_orders=(),
                authoritative=False,
                quality=DataQuality.INVALID,
                reason_codes=(f"POSITION_QUERY_FAILED:{type(error).__name__}",),
            )
        orders_result: dict | None = None
        try:
            orders_result = await asyncio.wait_for(
                asyncio.to_thread(self._query_orders),
                timeout=self._timeout,
            )
        except Exception:
            orders_result = None
        return self.adapt_results(
            positions_result,
            orders_result,
            as_of=as_of,
        )

    def adapt_results(
        self,
        positions_result: dict | list | tuple,
        orders_result: dict | list | tuple | None = None,
        *,
        quote_rows: list[dict] | tuple[dict, ...] = (),
        as_of: datetime | None = None,
    ) -> PositionReconciliation:
        observed_at = as_of or datetime.now(timezone.utc)
        position_ok, position_rows = self._unwrap(positions_result, "positions")
        order_ok, order_rows = self._unwrap(orders_result, "orders")
        quotes = {
            str(row.get("code") or row.get("stock_code") or "").strip().upper(): row
            for row in quote_rows
        }
        adapted_orders = tuple(
            order
            for row in order_rows
            if (order := self._adapt_order(row)) is not None
        )
        with self._lock:
            if order_ok:
                self._last_active_orders = adapted_orders
            orders = self._last_active_orders if not order_ok else adapted_orders
        order_ids: dict[str, list[str]] = {}
        for order in orders:
            order_ids.setdefault(order.stock_code, []).append(order.order_id)

        positions: list[PositionSnapshot] = []
        reasons: list[str] = []
        for row in position_rows:
            code = str(row.get("stock_code") or row.get("code") or "").strip().upper()
            quantity = self._integer(row.get("qty", row.get("quantity", 0)))
            if not code or quantity <= 0:
                continue
            quote = quotes.get(code, {})
            current = self._number(
                quote.get("last_price"),
                row.get("nominal_price"),
                row.get("current_price"),
            )
            cost = self._number(row.get("cost_price"), row.get("avg_price"))
            lot_size = self._integer(quote.get("lot_size", row.get("lot_size", 0))) or None
            quality = DataQuality.GOOD
            if current <= 0 or cost <= 0:
                quality = DataQuality.DEGRADED
                reasons.append(f"POSITION_PRICE_INCOMPLETE:{code}")
            sellable = max(
                0,
                min(
                    quantity,
                    self._integer(row.get("can_sell_qty", row.get("sellable_quantity", 0))),
                ),
            )
            positions.append(
                PositionSnapshot(
                    stock_code=code,
                    stock_name=str(row.get("stock_name") or quote.get("name") or ""),
                    as_of=observed_at,
                    quantity=quantity,
                    sellable_quantity=sellable,
                    cost_price=cost,
                    current_price=current,
                    peak_price=current,
                    lot_size=lot_size,
                    active_order_ids=tuple(order_ids.get(code, ())),
                    quality=quality,
                )
            )
        if not position_ok:
            reasons.append("POSITION_QUERY_NOT_AUTHORITATIVE")
        if orders_result is not None and not order_ok:
            reasons.append("ORDER_QUERY_NOT_AUTHORITATIVE")
        elif orders_result is None:
            reasons.append("ACTIVE_ORDERS_NOT_REFRESHED")
        quality = (
            DataQuality.INVALID
            if not position_ok
            else DataQuality.DEGRADED
            if reasons or any(item.quality is DataQuality.DEGRADED for item in positions)
            else DataQuality.GOOD
        )
        return PositionReconciliation(
            as_of=observed_at,
            positions=tuple(positions),
            active_orders=orders,
            authoritative=position_ok,
            quality=quality,
            reason_codes=tuple(dict.fromkeys(reasons)),
        )

    def adapt_rows(
        self,
        positions: dict[str, dict] | list[dict] | tuple[dict, ...],
        *,
        quote_rows: list[dict] | tuple[dict, ...] = (),
        as_of: datetime | None = None,
    ) -> PositionReconciliation:
        rows = list(positions.values()) if isinstance(positions, dict) else list(positions)
        return self.adapt_results(
            {"success": bool(rows), "positions": rows},
            None,
            quote_rows=quote_rows,
            as_of=as_of,
        )

    def _adapt_order(self, row: dict) -> ActiveOrderSnapshot | None:
        status = str(row.get("order_status") or row.get("status") or "").upper()
        if not status or any(status.endswith(token) for token in self._TERMINAL_ORDER_SUFFIXES):
            return None
        order_id = str(row.get("order_id") or "").strip()
        code = str(row.get("stock_code") or row.get("code") or "").strip()
        side = str(row.get("trd_side") or row.get("side") or "UNKNOWN")
        if not order_id or not code:
            return None
        return ActiveOrderSnapshot(
            order_id=order_id,
            stock_code=code,
            side=side,
            status=status,
            quantity=self._integer(row.get("qty", row.get("quantity", 0))),
            dealt_quantity=self._integer(row.get("dealt_qty", 0)),
        )

    def _query_positions(self) -> dict:
        if self._source is None:
            return {"success": False, "positions": []}
        manager = getattr(self._source, "position_manager", None)
        return manager.get_positions() if manager is not None else self._source.get_positions()

    def _query_orders(self) -> dict:
        if self._source is None:
            return {"success": False, "orders": []}
        manager = getattr(self._source, "order_manager", None)
        return manager.get_orders() if manager is not None else self._source.get_orders()

    @staticmethod
    def _unwrap(result: object, key: str) -> tuple[bool, list[dict]]:
        if isinstance(result, dict):
            rows = result.get(key, [])
            return bool(result.get("success")), list(rows) if isinstance(rows, (list, tuple)) else []
        if isinstance(result, (list, tuple)):
            return True, list(result)
        return False, []

    @staticmethod
    def _integer(value: object) -> int:
        try:
            return max(0, int(float(value or 0)))
        except (TypeError, ValueError, OverflowError):
            return 0

    @staticmethod
    def _number(*values: object) -> float:
        for value in values:
            try:
                number = float(value or 0)
            except (TypeError, ValueError, OverflowError):
                continue
            if number > 0:
                return number
        return 0.0
