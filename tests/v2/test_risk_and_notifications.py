import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from simple_trade.v2.application.notifications import NotificationCoordinator, NotificationFormatter
from simple_trade.v2.application.risk import ExecutionModeGate, IntentFactory, RiskEngine
from simple_trade.v2.config.defaults import EXECUTION_CONFIRMATION_TOKEN
from simple_trade.v2.domain.decisions import DecisionEvent, NotificationEvent
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
from simple_trade.v2.infrastructure.notifications.channels import UnifiedNotifier


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


def buy_intent(quantity=100, lot=100, mode=RuntimeMode.SEMI):
    return TradeIntent(
        source_event_id="decision-1",
        intent_type=IntentType.BUY,
        created_at=NOW,
        mode=mode,
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

    def test_shadow_momentum_confirmation_cannot_create_alert_intent(self):
        event = DecisionEvent(
            event_type=EventType.BUY_CONFIRMED,
            stock_code="HK.00100",
            exchange_time=NOW,
            received_time=NOW,
            source="test",
            strategy_version="test-v2",
            reason_code="STRICT_MOMENTUM_SHADOW_CONFIRMED",
            payload={"alert_eligible": False},
        )

        intent = IntentFactory(RuntimeMode.ALERT, RiskLimits()).build(event, context())

        self.assertIsNone(intent)

    def test_alert_buy_does_not_require_lot_size_or_account_capacity(self):
        event = DecisionEvent(
            event_type=EventType.BUY_CONFIRMED,
            stock_code="HK.00100",
            exchange_time=NOW,
            received_time=NOW,
            source="test",
            strategy_version="test-v2",
            reason_code="FAST_15M_MULTI_INFLOW_CONFIRMED",
            payload={
                "feature_snapshot": {
                    "quote": {"last_price": 12.34, "lot_size": None}
                }
            },
        )
        invalid_account = context(
            account_snapshot=account(
                available=0,
                assets=0,
                quality=DataQuality.INVALID,
            )
        )

        intent = IntentFactory(RuntimeMode.ALERT, RiskLimits()).build(
            event, invalid_account
        )

        self.assertIsNotNone(intent)
        self.assertIsNone(intent.buy_leg.lot_size)
        decision = self.engine.evaluate(intent, invalid_account)
        self.assertIs(decision.result, RiskResult.APPROVED)
        self.assertNotIn("ACCOUNT_CAPACITY_UNAVAILABLE", decision.reason_codes)

    def test_position_add_builds_manual_alert_only_when_position_exists(self):
        event = DecisionEvent(
            event_type=EventType.POSITION_ADD_CONFIRMED,
            stock_code="HK.00100",
            exchange_time=NOW,
            received_time=NOW,
            source="test",
            strategy_version="test-v2",
            reason_code="POSITION_ADD_CAPITAL_CONFIRMED",
            payload={
                "alert_eligible": True,
                "manual_only": True,
                "position": {"current_price": 10.2, "lot_size": 100},
            },
        )

        alert_intent = IntentFactory(RuntimeMode.ALERT, RiskLimits()).build(
            event, context(positions=(position(),))
        )
        missing_position = IntentFactory(RuntimeMode.ALERT, RiskLimits()).build(
            event, context()
        )
        executable = IntentFactory(RuntimeMode.SEMI, RiskLimits()).build(
            event, context(positions=(position(),))
        )

        self.assertIsNotNone(alert_intent)
        self.assertEqual(alert_intent.reason_codes, ("POSITION_ADD_CAPITAL_CONFIRMED",))
        self.assertIsNone(missing_position)
        self.assertIsNone(executable)


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


class NotificationFormatterTests(unittest.TestCase):
    @staticmethod
    def _buy_source(reason: str) -> RiskAssessedEvent:
        intent = TradeIntent(
            source_event_id="decision-buy",
            intent_type=IntentType.BUY,
            created_at=NOW,
            mode=RuntimeMode.ALERT,
            reason_codes=(reason,),
            buy_leg=OrderLeg(
                stock_code="HK.00100",
                side=OrderSide.BUY,
                quantity=100,
                reference_price=10,
                lot_size=100,
            ),
        )
        risk = RiskDecision(
            intent_id=intent.intent_id,
            result=RiskResult.APPROVED,
            checked_at=NOW,
            reason_codes=("RISK_CHECKS_PASSED",),
        )
        return RiskAssessedEvent(
            event_type=EventType.RISK_APPROVED,
            stock_code="HK.00100",
            exchange_time=NOW,
            received_time=NOW,
            source="test",
            source_decision_event_id="decision-buy",
            intent=intent,
            risk=risk,
        )

    def test_initial_entry_notification_includes_position_plan(self):
        event = NotificationFormatter(expiry_seconds=300).build(
            self._buy_source("FAST_15M_MULTI_INFLOW_CONFIRMED")
        )[0]

        self.assertEqual(event.title, "V2 首次建仓确认 · HK.00100")
        self.assertIn("建议首仓15%", event.message)
        self.assertIn("单票总仓不超过25%", event.message)

    def test_post_invalidation_recovery_uses_small_initial_position(self):
        event = NotificationFormatter(expiry_seconds=300).build(
            self._buy_source("POST_INVALIDATION_FLOW_RECOVERY_CONFIRMED")
        )[0]

        self.assertIn("候选失效后低位资金恢复确认", event.message)
        self.assertIn("建议首仓10%", event.message)

    def test_rejected_buy_is_only_an_observation_without_allocation_advice(self):
        source = self._buy_source("FAST_15M_MULTI_INFLOW_CONFIRMED")
        source = replace(source, event_type=EventType.RISK_REJECTED, risk=replace(source.risk, result=RiskResult.REJECTED))
        events = NotificationFormatter(expiry_seconds=300).build(source)
        self.assertEqual([event.channel for event in events], [NotificationChannel.WEBSOCKET])
        self.assertFalse(events[0].actionable)
        self.assertIn("尚不具备建仓或加仓条件", events[0].message)
        self.assertNotIn("建议首仓", events[0].message)
        self.assertNotIn("买入参考", events[0].message)

    def test_late_replay_does_not_reset_notification_expiry(self):
        source = self._buy_source("FAST_15M_MULTI_INFLOW_CONFIRMED")
        source = replace(source, received_time=NOW + timedelta(hours=1))
        event = NotificationFormatter(expiry_seconds=300).build(source)[0]
        self.assertEqual(event.expires_at, NOW + timedelta(minutes=5))
        self.assertLess(event.expires_at, source.received_time)

    def test_add_notification_has_distinct_title_plan_and_identity(self):
        formatter = NotificationFormatter(expiry_seconds=300)
        initial = formatter.build(
            self._buy_source("FAST_15M_MULTI_INFLOW_CONFIRMED")
        )[0]
        adding = formatter.build(
            self._buy_source("POSITION_ADD_CAPITAL_CONFIRMED")
        )[0]

        self.assertEqual(adding.title, "V2 加仓确认 · HK.00100")
        self.assertIn("建议加仓10%", adding.message)
        self.assertIn("只加盈利仓", adding.message)
        self.assertIn("风控：**通过**", adding.message)
        self.assertIn("风控检查通过", adding.message)
        self.assertNotEqual(initial.idempotency_key, adding.idempotency_key)

    def test_sell_notification_includes_strategy_reason(self):
        intent = TradeIntent(
            source_event_id="decision-exit",
            intent_type=IntentType.SELL,
            created_at=NOW,
            mode=RuntimeMode.ALERT,
            reason_codes=("REPEATED_OUTFLOW_AND_STRUCTURE_BREAK",),
            sell_leg=OrderLeg(
                stock_code="HK.00100",
                side=OrderSide.SELL,
                quantity=100,
                reference_price=10,
                lot_size=100,
            ),
        )
        risk = RiskDecision(
            intent_id=intent.intent_id,
            result=RiskResult.APPROVED,
            checked_at=NOW,
            reason_codes=("RISK_CHECKS_PASSED",),
        )
        source = RiskAssessedEvent(
            event_type=EventType.RISK_APPROVED,
            stock_code="HK.00100",
            exchange_time=NOW,
            received_time=NOW,
            source="test",
            source_decision_event_id="decision-exit",
            intent=intent,
            risk=risk,
        )

        message = NotificationFormatter(expiry_seconds=300).build(source)[0].message

        self.assertIn("多次大单流出且价格结构破位", message)
        self.assertIn("风控检查通过", message)


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


class NotificationGovernanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from simple_trade.services.alert.push_governor import GovernorConfig, PushGovernor
        from simple_trade.services.alert.wechat_alert import WeChatAlertService

        self.environment = patch.dict("os.environ", {"WECHAT_SOLO_CATEGORIES": ""})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.wechat = WeChatAlertService(webhook_key="unit-test-no-network")
        self.wechat._do_send = AsyncMock(return_value=True)
        self.wechat.governor = PushGovernor(
            GovernorConfig(enabled=True, info_budget_per_window=0),
            today_provider=lambda: "2026-09-01",
        )
        self.notifier = UnifiedNotifier(wechat_service=self.wechat)
        self.formatter = NotificationFormatter(expiry_seconds=300)

    async def test_initial_and_add_bypass_exhausted_low_priority_budget(self):
        for _ in range(2):
            self.wechat.governor.record_sent("交易信号", "HK.00100", 10, "INFO")
        for reason in ("FAST_15M_MULTI_INFLOW_CONFIRMED", "POSITION_ADD_CAPITAL_CONFIRMED"):
            source = NotificationFormatterTests._buy_source(reason)
            event = self.formatter.build(source)[1]
            result = await self.notifier.send(event, attempt=1)
            self.assertIs(result, NotificationDeliveryResult.DELIVERED)
        self.assertEqual(self.wechat._do_send.await_count, 2)
        repeated = await self.notifier.send(event, attempt=1)
        self.assertIs(repeated, NotificationDeliveryResult.COLLAPSED)
        self.assertEqual(self.wechat._do_send.await_count, 2)

    async def test_risk_notice_cannot_throttle_subsequent_approved_exit(self):
        from simple_trade.services.alert.wechat_alert import AlertLevel

        buy = NotificationFormatterTests._buy_source("REPEATED_OUTFLOW_AND_STRUCTURE_BREAK")
        intent = replace(
            buy.intent, source_event_id="risk-limited", intent_type=IntentType.SELL, buy_leg=None,
            sell_leg=replace(buy.intent.buy_leg, side=OrderSide.SELL),
        )
        risk_notice = replace(
            buy, intent=intent, event_type=EventType.RISK_REJECTED, source_decision_event_id="risk-limited",
            risk=replace(buy.risk, result=RiskResult.REJECTED),
        )
        risk_event = self.formatter.build(risk_notice)[1]
        self.assertNotIn("卖出参考", risk_event.message)
        self.assertFalse(risk_event.actionable)
        self.assertIs(await self.notifier.send(risk_event, attempt=1), NotificationDeliveryResult.DELIVERED)
        self.assertIs(self.wechat._do_send.await_args.args[0], AlertLevel.WARNING)

        approved = replace(
            risk_notice, event_type=EventType.RISK_APPROVED,
            source_decision_event_id="exit-approved", risk=buy.risk,
            intent=replace(intent, source_event_id="exit-approved"),
        )
        exit_event = self.formatter.build(approved)[1]
        self.assertTrue(exit_event.actionable)
        self.assertIs(await self.notifier.send(exit_event, attempt=1), NotificationDeliveryResult.DELIVERED)
        self.assertIs(self.wechat._do_send.await_args.args[0], AlertLevel.CRITICAL)

        escalated = replace(exit_event, idempotency_key="new-price", reference_price=9.5)
        self.assertIs(await self.notifier.send(escalated, attempt=1), NotificationDeliveryResult.DELIVERED)


if __name__ == "__main__":
    unittest.main()
