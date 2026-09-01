"""行情数据端口。"""

from collections.abc import AsyncIterator
from typing import Protocol

from ..domain.events import MarketEvent


class MarketDataPort(Protocol):
    async def subscribe(self, stock_codes: tuple[str, ...]) -> None: ...

    async def unsubscribe(self, stock_codes: tuple[str, ...]) -> None: ...

    def events(self) -> AsyncIterator[MarketEvent]: ...
