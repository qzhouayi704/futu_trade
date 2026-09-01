import asyncio
from concurrent.futures import Future
from types import SimpleNamespace

import pytest

from simple_trade.v2.infrastructure.db_write import submit_write


class _WriteQueue:
    def __init__(self, future: Future):
        self.future = future
        self.is_running = True
        self.pending_count = 0

    def submit(self, operation, *args):
        return self.future


@pytest.mark.asyncio
async def test_submit_write_cancels_task_that_has_not_started():
    future = Future()
    db = SimpleNamespace(write_queue=_WriteQueue(future))

    with pytest.raises(TimeoutError):
        await submit_write(db, lambda: None, timeout=0.01)

    assert future.cancelled()


@pytest.mark.asyncio
async def test_submit_write_waits_for_running_transaction_after_soft_timeout():
    future = Future()
    assert future.set_running_or_notify_cancel()
    db = SimpleNamespace(write_queue=_WriteQueue(future))
    asyncio.get_running_loop().call_later(0.03, future.set_result, 42)

    result = await submit_write(db, lambda: None, timeout=0.01)

    assert result == 42
    assert not future.cancelled()


@pytest.mark.asyncio
async def test_submit_write_returns_without_timeout_when_write_is_fast():
    future = Future()
    future.set_result("ok")
    db = SimpleNamespace(write_queue=_WriteQueue(future))

    result = await submit_write(db, lambda: None, timeout=0.1)

    assert result == "ok"
