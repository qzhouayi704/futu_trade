"""Cached broker and market facts for fail-closed risk evaluation."""

import asyncio
from datetime import datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from ...domain.risk import RiskContext
from .futu_account_provider import FutuAccountProvider
from .futu_position_provider import FutuPositionProvider


class MarketSessionPort(Protocol):
    def is_trading(self, stock_code: str, when: datetime) -> bool: ...


class HKMarketSession:
    def is_trading(self, stock_code: str, when: datetime) -> bool:
        from ....utils.market_helper import MarketTimeHelper

        market = "US" if stock_code.startswith("US.") else "HK"
        local = when.astimezone(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
        return MarketTimeHelper.is_market_trading(market, local)


class BrokerRiskContextProvider:
    def __init__(
        self,
        positions: FutuPositionProvider,
        account: FutuAccountProvider,
        market: MarketSessionPort | None = None,
        *,
        cache_seconds: float = 10.0,
    ) -> None:
        self._positions = positions
        self._account = account
        self._market = market or HKMarketSession()
        self._cache_for = timedelta(seconds=cache_seconds)
        self._cached_at: datetime | None = None
        self._cached_facts = None
        self._lock = asyncio.Lock()

    async def fetch(self, stock_code: str, when: datetime) -> RiskContext:
        async with self._lock:
            if self._cached_at is None or when - self._cached_at > self._cache_for:
                position_result, account_result = await asyncio.gather(
                    self._positions.fetch(), self._account.fetch()
                )
                self._cached_at = when
                self._cached_facts = (position_result, account_result)
            reconciliation, account = self._cached_facts
        market_trading = self._market.is_trading(stock_code, when)
        return RiskContext(
            checked_at=when,
            market_trading=market_trading,
            positions=reconciliation.positions,
            active_orders=reconciliation.active_orders,
            account=account,
        )
