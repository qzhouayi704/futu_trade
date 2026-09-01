"""策略当前状态存储端口。"""

from typing import Protocol

from ..domain.decisions import StrategyState


class StateStore(Protocol):
    async def get(self, stock_code: str, strategy_version: str) -> StrategyState | None: ...

    async def save(self, state: StrategyState, expected_version: int) -> None: ...
