import unittest
from datetime import datetime, timedelta, timezone

from simple_trade.v2.application.notifications import NotificationCoordinator, NotificationFormatter
from simple_trade.v2.application.risk import ExecutionModeGate, RiskEngine
from simple_trade.v2.config.defaults import EXECUTION_CONFIRMATION_TOKEN
from simple_trade.v2.domain.decisions import NotificationEvent
from simple_trade.v2.domain.enums import (
    DataQuality,
    EventType,
    IntentType,
    NotificationChannel,
    NotificationDeliveryResult,
    OrderSide,
    RiskResult,
    RuntimeMode,
)
from simple_trade.v2.domain.events import RiskAssessedEvent
from simple_trade.v2.domain.orders import OrderLeg, RiskDecision, TradeIntent
from simple_trade.v2.domain.positions import ActiveOrderSnapshot, PositionSnapshot
from simple_trade.v2.domain.risk import AccountSnapshot, RiskContext, RiskLimits
from simple_trade.v2.infrastructure.broker.futu_account_provider import FutuAccountProvider


NOW = datetime(2026, 9, 1, 2, 0, tzinfo=timezone.utc)


class AllowGuard:
    def can_buy(self, stock_code, when):
        return True, ""

    def can_sell(self, stock_code, when):
        return True, ""


def account(*, available=100_000, assets=500_000, quality=DataQuality.GOOD):
    reasons = ("INVALID",) if quality is DataQuality.INVALID else ()
    return AccountSnapshot(
        as_of=NOW,
        available_funds=available,
        total_assets=assets,
        quality=quality,
        reason_codes=reasons,
    )


def position(code="HK.00100", sellable=100):
    return PositionSnapshot(
        stock_code=code,
        as_of=NOW,
        quantity=100,
        sellable_quantity=sellable,
        cost_price=9,
        current_price=10,
        peak_price=11,
        lot_size=100,
    )


def context(*, positions=(), orders=(), market=True, account_snapshot=None):
    return RiskContext(
        checked_at=NOW,
        market_trading=market,
        positions=positions,
        active_orders=orders,
        account=account_snapshot or account(),
    )


def buy_intent(quantity=100, lot=100):
    return TradeIntent(
        source_event_id="decision-1",
        intent_type=IntentType.BUY,
        created_at=NOW,
        mode=RuntimeMode.ALERT,
        buy_leg=OrderLeg(
            stock_code="HK.00200",
            side=OrderSide.BUY,
            quantity=quantity,
            reference_price=10,
            lot_size=lot,
        ),
    )


class RiskEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = RiskEngine(RiskLimits(max_positions=2), AllowGuard())

    def test_approved_buy_uses_account_lot_position_and_frequency_facts(self):
        decision = self.engine.evaluate(buy_intent(), context(positions=(position(),)))
        self.assertIs(decision.result, RiskResult.APPROVED)

    def test_market_active_order_capacity_and_account_fail_closed(self):
        order = ActiveOrderSnapshot(
            order_id="o1",
            stock_code="HK.00200",
            side="BUY",
            status="SUBMITTED",
            quantity=100,
        )
        positions = (position(), position("HK.00300"))
        result = self.engine.evaluate(
            buy_intent(),
            context(
                positions=positions,
                orders=(order,),
                market=False,
                account_snapshot=account(available=0, assets=0, quality=DataQuality.INVALID),
            ),
        )
        self.assertIs(result.result, RiskResult.REJECTED)
        joined = "|".join(result.reason_codes)
        self.assertIn("MARKET_NOT_TRADING", joined)
        self.assertIn("ACTIVE_ORDER_CONFLICT", joined)
        self.assertIn("MAX_POSITION_COUNT_REACHED", joined)
        self.assertIn("ACCOUNT_CAPACITY_UNAVAILABLE", joined)

    def test_sell_cannot_exceed_broker_sellable_quantity(self):
        intent = TradeIntent(
            source_event_id="decision-sell",
            intent_type=IntentType.SELL,
            created_at=NOW,
            mode=RuntimeMode.ALERT,
            sell_leg=OrderLeg(
                stock_code="HK.00100",
                side=OrderSide.SELL,
                quantity=100,
                reference_price=10,
                lot_size=100,
            ),
        )
        result = self.engine.evaluate(intent, context(positions=(position(sellable=50),)))
        self.assertIn("SELLABLE_QUANTITY_EXCEEDED:HK.00100", result.reason_codes)

    def test_execution_gate_blocks_shadow_and_alert(self):
        gate = ExecutionModeGate(
            enabled=True,
            confirmation=EXECUTION_CONFIRMATION_TOKEN,
        )
        self.assertFalse(gate.allows(RuntimeMode.SHADOW))
        self.assertFalse(gate.allows(RuntimeMode.ALERT))
        self.assertTrue(gate.allows(RuntimeMode.SEMI))
        with self.assertRaises(PermissionError):
            gate.require(RuntimeMode.ALERT)


class AccountProviderTests(unittest.TestCase):
    def test_adapts_real_account_capacity_fields(self):
        snapshot = FutuAccountProvider(None).adapt(
            (
                0,
                [
                    {
                        "cash": 88_000,
                        "power": 120_000,
                        "total_assets": 500_000,
                        "currency": "HKD",
                    }
                ],
            ),
            as_of=NOW,
        )
        self.assertEqual(snapshot.available_funds, 88_000)
        self.assertEqual(snapshot.total_assets, 500_000)
        self.assertIs(snapshot.quality, DataQuality.GOOD)


class FakeNotificationStore:
    def __init__(self):
        self.claimed = set()
        self.marks = []

    async def claim(self, event):
        key = (event.idempotency_key, event.channel)
        if key in self.claimed:
            return False
        self.claimed.add(key)
        return True

    async def mark(self, event, **kwargs):
        self.marks.append(kwargs)


class FlakyNotifier:
    def __init__(self):
        self.calls = 0

    async def send(self, event, *, attempt):
        self.calls += 1
        return (
            NotificationDeliveryResult.FAILED
            if attempt == 1
            else NotificationDeliveryResult.DELIVERED
        )


def notification(expires_at):
    return NotificationEvent(
        event_type=EventType.NOTIFICATION_REQUESTED,
        stock_code="HK.00100",
        exchange_time=NOW,
        received_time=NOW,
        source="test",
        strategy_version="risk-v1",
        decision_event_id="decision-1",
        channel=NotificationChannel.WEBSOCKET,
        idempotency_key="same-key",
        title="V2 test",
        message="test",
        expires_at=expires_at,
    )


class NotificationCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_delivery_and_duplicate_collapse(self):
        store = FakeNotificationStore()
        notifier = FlakyNotifier()
        coordinator = NotificationCoordinator(
            NotificationFormatter(expiry_seconds=300),
            store,
            notifier,
            max_attempts=2,
            retry_delays=(0, 0),
        )
        await coordinator.start()
        event = notification(datetime.now(timezone.utc) + timedelta(minutes=5))
        coordinator.on_notification(event)
        coordinator.on_notification(event)
        await coordinator.join()
        await coordinator.stop()
        self.assertEqual(notifier.calls, 2)
        self.assertEqual(coordinator.snapshot().delivered, 1)
        self.assertEqual(coordinator.snapshot().collapsed, 1)
        self.assertEqual(store.marks[-1]["status"], "DELIVERED")

    async def test_expired_notification_is_dropped_without_send(self):
        store = FakeNotificationStore()
        notifier = FlakyNotifier()
        coordinator = NotificationCoordinator(
            NotificationFormatter(expiry_seconds=300),
            store,
            notifier,
            max_attempts=2,
            retry_delays=(0, 0),
        )
        await coordinator.start()
        coordinator.on_notification(
            notification(datetime.now(timezone.utc) - timedelta(seconds=1))
        )
        await coordinator.join()
        await coordinator.stop()
        self.assertEqual(notifier.calls, 0)
        self.assertEqual(coordinator.snapshot().expired, 1)


if __name__ == "__main__":
    unittest.main()
