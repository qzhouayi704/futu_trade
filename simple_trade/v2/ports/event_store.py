"""决策事件存储端口。"""

from datetime import datetime
from typing import AsyncIterator, Protocol

from ..domain.decisions import DecisionEvent, StrategyState


class EventStore(Protocol):
    async def append(self, event: DecisionEvent) -> bool: ...

    async def append_with_state(
        self,
        event: DecisionEvent,
        state: StrategyState,
        expected_version: int,
    ) -> bool: ...

    async def load(
        self,
        stock_code: str,
        strategy_version: str,
    ) -> list[DecisionEvent]: ...

    def stream(
        self,
        start_at: datetime,
        end_at: datetime,
    ) -> AsyncIterator[DecisionEvent]: ...
