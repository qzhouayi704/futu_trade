"""Timeout-bounded Futu account capacity adapter."""

import asyncio
from datetime import datetime, timezone
from typing import Protocol

from ...domain.enums import DataQuality
from ...domain.risk import AccountSnapshot


class FutuAccountSource(Protocol):
    def get_account_info(self) -> dict: ...


class FutuAccountProvider:
    def __init__(self, source: FutuAccountSource | None, *, timeout_seconds: float = 8.0) -> None:
        self._source = source
        self._timeout = timeout_seconds

    async def fetch(self) -> AccountSnapshot:
        as_of = datetime.now(timezone.utc)
        if self._source is None:
            return self._invalid(as_of, "ACCOUNT_SOURCE_UNAVAILABLE")
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self._query), timeout=self._timeout
            )
        except Exception as error:
            return self._invalid(as_of, f"ACCOUNT_QUERY_FAILED:{type(error).__name__}")
        return self.adapt(result, as_of=as_of)

    def adapt(self, result: object, *, as_of: datetime | None = None) -> AccountSnapshot:
        observed_at = as_of or datetime.now(timezone.utc)
        ok, rows = self._unwrap(result)
        if not ok or not rows:
            return self._invalid(observed_at, "ACCOUNT_QUERY_NOT_AUTHORITATIVE")
        row = max(rows, key=lambda item: self._number(item.get("total_assets")))
        available = self._number(
            row.get("cash"),
            row.get("available_funds"),
            row.get("avl_withdrawal_cash"),
            row.get("power"),
        )
        total_assets = self._number(row.get("total_assets"), row.get("total_asset"))
        if total_assets <= 0:
            return self._invalid(observed_at, "ACCOUNT_TOTAL_ASSETS_UNAVAILABLE")
        quality = DataQuality.GOOD if available > 0 else DataQuality.DEGRADED
        reasons = () if quality is DataQuality.GOOD else ("ACCOUNT_AVAILABLE_FUNDS_ZERO",)
        return AccountSnapshot(
            as_of=observed_at,
            available_funds=available,
            total_assets=total_assets,
            currency=str(row.get("currency") or "HKD"),
            quality=quality,
            reason_codes=reasons,
        )

    def _query(self):
        manager = getattr(self._source, "account_manager", None)
        client = getattr(manager, "trade_client", None)
        if client is not None and hasattr(client, "accinfo_query"):
            return client.accinfo_query(trd_env=getattr(manager, "trd_env", None))
        return self._source.get_account_info()

    @classmethod
    def _unwrap(cls, result: object) -> tuple[bool, list[dict]]:
        if isinstance(result, tuple) and len(result) == 2:
            ok, data = result
            return ok == 0, cls._rows(data)
        if isinstance(result, dict):
            rows = result.get("accounts", result.get("data", []))
            return bool(result.get("success")), cls._rows(rows)
        return False, []

    @staticmethod
    def _rows(data: object) -> list[dict]:
        if isinstance(data, (list, tuple)):
            return [dict(item) for item in data]
        if hasattr(data, "to_dict"):
            try:
                rows = data.to_dict("records")
                return [dict(item) for item in rows]
            except Exception:
                return []
        return []

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

    @staticmethod
    def _invalid(as_of: datetime, reason: str) -> AccountSnapshot:
        return AccountSnapshot(
            as_of=as_of,
            available_funds=0,
            total_assets=0,
            quality=DataQuality.INVALID,
            reason_codes=(reason,),
        )
