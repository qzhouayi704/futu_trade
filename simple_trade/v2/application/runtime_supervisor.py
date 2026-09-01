"""持有 V2 所有长期任务真实句柄的运行监管器。"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import logging


FailureCallback = Callable[[str, BaseException, bool], None]


@dataclass(frozen=True, slots=True)
class TaskSnapshot:
    name: str
    critical: bool
    running: bool
    done: bool
    cancelled: bool
    failed: bool
    started_at: datetime
    finished_at: datetime | None
    error: str | None


@dataclass(slots=True)
class _ManagedTask:
    task: asyncio.Task
    critical: bool
    started_at: datetime
    finished_at: datetime | None = None
    error: str | None = None


class RuntimeSupervisor:
    def __init__(self, on_failure: FailureCallback | None = None) -> None:
        self._tasks: dict[str, _ManagedTask] = {}
        self._on_failure = on_failure
        self._stopping = False

    def create_task(
        self,
        name: str,
        coroutine: Awaitable[object],
        *,
        critical: bool = False,
    ) -> asyncio.Task:
        if self._stopping:
            if hasattr(coroutine, "close"):
                coroutine.close()  # type: ignore[attr-defined]
            raise RuntimeError("RuntimeSupervisor 正在停止")
        existing = self._tasks.get(name)
        if existing is not None and not existing.task.done():
            if hasattr(coroutine, "close"):
                coroutine.close()  # type: ignore[attr-defined]
            raise ValueError(f"任务已存在且仍在运行: {name}")

        task = asyncio.create_task(coroutine, name=name)
        managed = _ManagedTask(
            task=task,
            critical=critical,
            started_at=datetime.now(timezone.utc),
        )
        self._tasks[name] = managed
        task.add_done_callback(lambda completed, task_name=name: self._on_done(task_name, completed))
        return task

    async def stop(self, timeout: float = 10.0) -> None:
        self._stopping = True
        pending = [managed.task for managed in self._tasks.values() if not managed.task.done()]
        for task in pending:
            task.cancel()
        if pending:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending, return_exceptions=True),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                logging.error("V2 RuntimeSupervisor 停止超时: pending=%s", len(pending))

    def snapshots(self) -> tuple[TaskSnapshot, ...]:
        result = []
        for name, managed in sorted(self._tasks.items()):
            task = managed.task
            result.append(
                TaskSnapshot(
                    name=name,
                    critical=managed.critical,
                    running=not task.done(),
                    done=task.done(),
                    cancelled=task.cancelled(),
                    failed=managed.error is not None,
                    started_at=managed.started_at,
                    finished_at=managed.finished_at,
                    error=managed.error,
                )
            )
        return tuple(result)

    def _on_done(self, name: str, task: asyncio.Task) -> None:
        managed = self._tasks.get(name)
        if managed is None:
            return
        managed.finished_at = datetime.now(timezone.utc)
        if task.cancelled():
            return
        try:
            error = task.exception()
        except asyncio.CancelledError:
            return
        if error is None:
            return
        managed.error = f"{type(error).__name__}: {error}"
        logging.error(
            "V2 后台任务异常: name=%s critical=%s error=%s",
            name,
            managed.critical,
            managed.error,
        )
        if self._on_failure is not None:
            try:
                self._on_failure(name, error, managed.critical)
            except Exception:
                logging.exception("V2 任务失败回调异常: %s", name)
