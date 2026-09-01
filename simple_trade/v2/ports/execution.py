"""券商订单执行端口。"""

from typing import Protocol

from ..domain.orders import ExecutionReport, OrderCommand


class ExecutionPort(Protocol):
    async def submit(self, command: OrderCommand) -> ExecutionReport: ...

    async def cancel(self, broker_order_id: str) -> ExecutionReport: ...
