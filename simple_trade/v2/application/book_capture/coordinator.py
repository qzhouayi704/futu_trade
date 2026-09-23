"""Opt-in capture lifecycle, isolated from production strategy calculations."""

import asyncio
from collections.abc import Callable
import logging

from ...domain.capture import BookCaptureConfig, CaptureStats
from ...domain.planning.models import hk_stock_code
from ...ports.book_capture import BookCapturePort
from .recorder import BookRecorder


class BookCaptureCoordinator:
    def __init__(self, config: BookCaptureConfig, port: BookCapturePort,
                 targets: Callable[[], tuple[str, ...]], recorder: BookRecorder) -> None:
        self.config = config
        self.port = port
        self._targets = targets
        self.recorder = recorder
        self._worker: asyncio.Task | None = None
        self._inflight: asyncio.Task | None = None
        self._running = False

    async def start(self, supervisor=None) -> None:
        if self._running:
            return
        try:
            await asyncio.to_thread(self.recorder.start)
            self.port.set_sink(self.recorder.offer)
        except Exception as error:
            self.recorder.fail(f"CAPTURE_START_FAILED:{type(error).__name__}:{error}")
            self._detach()
            await asyncio.to_thread(self.recorder.stop)
            logging.exception("V2 book capture unavailable; normal alerts are unchanged")
            return
        self._running = True
        self._worker = (supervisor.create_task("v2-book-subscriptions", self._run(), critical=False)
                        if supervisor else asyncio.create_task(self._run(), name="v2-book-subscriptions"))

    async def _run(self) -> None:
        try:
            while self._running and self.recorder.snapshot().running:
                codes = tuple(dict.fromkeys(hk_stock_code(code) for code in self._targets()))[:self.config.max_stocks]
                self.recorder.targets(codes)
                if self._inflight is None:
                    self._inflight = asyncio.create_task(asyncio.to_thread(self.port.sync, codes))
                try:
                    actual = await asyncio.wait_for(asyncio.shield(self._inflight), self.config.io_timeout_seconds)
                except TimeoutError:
                    self.recorder.subscriptions((), failed=True)
                except Exception:
                    self._inflight = None
                    self.recorder.subscriptions((), failed=True)
                    logging.exception("V2 book subscriptions failed")
                else:
                    self._inflight = None
                    self.recorder.subscriptions(actual, failed=any(code not in actual for code in codes))
                await asyncio.sleep(self.config.refresh_seconds)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.recorder.fail(f"CAPTURE_WORKER_FAILED:{type(error).__name__}:{error}")
            logging.exception("V2 book capture worker stopped")
        finally:
            self._detach()

    def _detach(self) -> None:
        try:
            self.port.close()
        except Exception:
            self.recorder.fail("CAPTURE_SINK_DETACH_FAILED")
            logging.exception("V2 book capture sink detach failed")

    async def stop(self) -> None:
        self._running = False
        self._detach()
        if self._worker is not None:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
        if self._inflight is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._inflight), self.config.io_timeout_seconds)
            except Exception:
                self.recorder.fail("SUBSCRIPTION_STOP_PENDING")
        await asyncio.to_thread(self.recorder.stop)

    def snapshot(self) -> CaptureStats:
        return self.recorder.snapshot()
