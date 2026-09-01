"""通过现有单写队列异步等待 SQLite 事务。"""

import asyncio
from collections.abc import Callable
import logging
from typing import TYPE_CHECKING, Protocol, TypeVar

if TYPE_CHECKING:
    from ...database.core.db_manager import DatabaseManager


T = TypeVar("T")


class _WriteQueue(Protocol):
    is_running: bool
    pending_count: int

    def submit(self, operation: Callable[..., T], *args: object): ...


class DatabaseWritePort(Protocol):
    write_queue: _WriteQueue


async def submit_write(
    db: "DatabaseManager | DatabaseWritePort",
    operation: Callable[..., T],
    *args: object,
    timeout: float,
) -> T:
    if not db.write_queue.is_running:
        raise RuntimeError("数据库单写队列未运行")
    future = db.write_queue.submit(operation, *args)
    wrapped = asyncio.wrap_future(future)
    try:
        return await asyncio.wait_for(wrapped, timeout=timeout)
    except TimeoutError:
        cancelled = future.cancel()
        logging.error(
            "V2 数据库写入超时: operation=%s cancelled=%s pending=%s",
            getattr(operation, "__name__", type(operation).__name__),
            cancelled,
            db.write_queue.pending_count,
        )
        raise
