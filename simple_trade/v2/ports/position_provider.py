"""券商持仓事实端口。"""

from typing import Protocol

from ..domain.positions import PositionSnapshot


class PositionProvider(Protocol):
    async def list_positions(self) -> tuple[PositionSnapshot, ...]: ...

    async def get_position(self, stock_code: str) -> PositionSnapshot | None: ...
