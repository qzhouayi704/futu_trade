import asyncio
from datetime import timedelta
import threading

from simple_trade.v2.application.exposure_subscriptions import ExposureSubscriptionCoordinator
from simple_trade.v2.domain.enums import DataQuality, EventType
from simple_trade.v2.domain.events import PositionReconciledEvent
from simple_trade.v2.domain.positions import ActiveOrderSnapshot, PositionReconciliation, PositionSnapshot
from tests.v2.test_candidate_strategy import NOW
from tests.v2.test_stores_and_runtime import SqliteTestDatabase
from simple_trade.v2.application.runtime import V2Runtime
from simple_trade.v2.config.models import V2Config


class Port:
    def __init__(self):
        self.protected = ()
        self.calls = []
        self.succeed = True

    def protect_exposure(self, codes):
        self.protected = codes

    def subscribe_exposure(self, code):
        self.calls.append(code)
        return self.succeed


def event(second=0, *, positions=("HK.00100",), orders=("HK.00700",), authoritative=True, reasons=()):
    at = NOW + timedelta(seconds=second)
    value = PositionReconciliation(
        as_of=at, authoritative=authoritative, quality=DataQuality.GOOD, reason_codes=reasons,
        positions=tuple(PositionSnapshot(stock_code=code, as_of=at, quantity=100, sellable_quantity=100,
                                         cost_price=100, current_price=100, peak_price=100, lot_size=100)
                        for code in positions),
        active_orders=tuple(ActiveOrderSnapshot(order_id=code, stock_code=code, side="BUY", status="SUBMITTED",
                                                quantity=100) for code in orders))
    return PositionReconciledEvent(event_type=EventType.POSITION_RECONCILED, stock_code="HK.00100",
                                   exchange_time=at, received_time=at, source="test", strategy_version="test",
                                   reconciliation=value)


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.005)


def test_authoritative_updates_failed_and_stale_results_never_clear_protection():
    port = Port()
    coordinator = ExposureSubscriptionCoordinator(port)
    coordinator.on_reconciled(event())
    assert port.protected == ("HK.00100", "HK.00700")
    coordinator.on_reconciled(event(1, authoritative=False, positions=(), orders=()))
    coordinator.on_reconciled(event(-1, positions=(), orders=()))
    coordinator.on_reconciled(event(0, positions=(), orders=()))
    assert port.protected == ("HK.00100", "HK.00700")
    assert coordinator.snapshot().ignored_reconciliations == 3
    coordinator.on_reconciled(event(2, positions=(), orders=(), reasons=("ORDER_QUERY_NOT_AUTHORITATIVE",)))
    assert port.protected == ("HK.00700",)
    coordinator.on_reconciled(event(3, positions=(), orders=(), reasons=("ACTIVE_ORDERS_NOT_REFRESHED",)))
    assert port.protected == ("HK.00700",)
    coordinator.on_reconciled(event(4, positions=(), orders=()))
    assert port.protected == ()


def test_worker_retries_false_results_and_stops_cleanly():
    async def run():
        port = Port()
        port.succeed = False
        coordinator = ExposureSubscriptionCoordinator(port, retry_seconds=0.02, timeout_seconds=0.02)
        coordinator.on_reconciled(event(orders=()))
        assert port.calls == []
        await coordinator.start()
        try:
            await until(lambda: coordinator.snapshot().failed >= 1)
            port.succeed = True
            await until(lambda: coordinator.snapshot().completed >= 1)
        finally:
            await coordinator.stop()
        assert not coordinator.snapshot().running
        assert port.protected == ("HK.00100",)
    asyncio.run(run())


def test_timeout_and_restart_do_not_launch_overlapping_sdk_calls():
    async def run():
        port = Port()
        started, release = threading.Event(), threading.Event()
        def slow(code):
            port.calls.append(code)
            started.set()
            release.wait(2)
            return True
        port.subscribe_exposure = slow
        coordinator = ExposureSubscriptionCoordinator(port, retry_seconds=0.01, timeout_seconds=0.01)
        coordinator.on_reconciled(event(orders=()))
        await coordinator.start()
        try:
            await until(started.is_set)
            await until(lambda: coordinator.snapshot().timeouts >= 2)
            await coordinator.stop()
            await coordinator.start()
            await until(lambda: coordinator.snapshot().timeouts >= 3)
            assert port.calls == ["HK.00100"]
            # A close while the SDK is blocked still updates protection immediately.
            coordinator.on_reconciled(event(1, positions=(), orders=()))
            assert port.protected == ()
            release.set()
            await until(lambda: coordinator.snapshot().completed == 1)
            assert port.calls == ["HK.00100"]
        finally:
            release.set()
            await coordinator.stop()
    asyncio.run(run())


def test_runtime_registers_protection_and_stops_worker(tmp_path):
    async def run():
        port = Port()
        runtime = V2Runtime(SqliteTestDatabase(tmp_path / "runtime.db"), config=V2Config(enabled=True),
                            exposure_subscription_port=port)
        await runtime.start()
        try:
            await runtime.event_bus.publish(event())
            await runtime.event_bus.join()
            await until(lambda: set(port.calls) == {"HK.00100", "HK.00700"})
            assert runtime.snapshot().exposure_subscriptions.running
        finally:
            await runtime.stop()
        assert not runtime.snapshot().exposure_subscriptions.running
        assert port.protected == ("HK.00100", "HK.00700")
    asyncio.run(run())
