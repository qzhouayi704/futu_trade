import unittest
from datetime import datetime, timedelta, timezone

from simple_trade.v2.config.models import V2Config
from simple_trade.v2.domain.enums import (
    CandidateStatus,
    DataQuality,
    DecisionAction,
    EventType,
    IntentType,
    OrderSide,
    PositionStatus,
    RuntimeMode,
    StrategyStatus,
)
from simple_trade.v2.domain.candidates import TradeCandidate
from simple_trade.v2.domain.decisions import StrategyTransition
from simple_trade.v2.domain.events import DomainEvent, MarketEvent
from simple_trade.v2.domain.market import QuoteSnapshot
from simple_trade.v2.domain.orders import OrderLeg, TradeIntent
from simple_trade.v2.domain.positions import PositionDecision, PositionSnapshot
from simple_trade.v2.domain.serialization import to_primitive
from simple_trade.v2.ports.clock import Clock, SystemClock, VirtualClock


NOW = datetime(2026, 8, 31, 9, 30, tzinfo=timezone.utc)


class DomainContractTests(unittest.TestCase):
    def test_event_requires_timezone(self) -> None:
        with self.assertRaisesRegex(ValueError, "exchange_time"):
            DomainEvent(
                event_type=EventType.QUOTE_UPDATED,
                stock_code="HK.00100",
                exchange_time=datetime(2026, 8, 31, 9, 30),
                received_time=NOW,
                source="test",
            )

    def test_event_payload_is_recursively_immutable(self) -> None:
        event = MarketEvent(
            event_type=EventType.TICK_RECEIVED,
            stock_code=" hk.00100 ",
            exchange_time=NOW,
            received_time=NOW,
            source="test",
            payload={"levels": [{"price": 356.6}]},
        )

        self.assertEqual(event.stock_code, "HK.00100")
        with self.assertRaises(TypeError):
            event.payload["new"] = 1  # type: ignore[index]
        with self.assertRaises(TypeError):
            event.payload["levels"][0]["price"] = 1  # type: ignore[index]

    def test_rotation_requires_sell_and_buy_legs(self) -> None:
        sell_leg = OrderLeg(
            stock_code="HK.00100",
            side=OrderSide.SELL,
            quantity=100,
        )
        with self.assertRaisesRegex(ValueError, "sell.*buy|buy.*sell|卖出腿和买入腿"):
            TradeIntent(
                source_event_id="event-1",
                intent_type=IntentType.ROTATE,
                created_at=NOW,
                mode=RuntimeMode.SHADOW,
                sell_leg=sell_leg,
            )

    def test_strategy_version_is_deterministic(self) -> None:
        first = V2Config(strategy_name="rotation", ruleset_revision="r1")
        second = V2Config(strategy_name="rotation", ruleset_revision="r1")
        changed = V2Config(strategy_name="rotation", ruleset_revision="r2")

        self.assertEqual(first.strategy_version, second.strategy_version)
        self.assertNotEqual(first.strategy_version, changed.strategy_version)
        self.assertFalse(first.enabled)
        self.assertIs(first.mode, RuntimeMode.SHADOW)

    def test_quote_serialization_round_trip(self) -> None:
        quote = QuoteSnapshot(
            stock_code="HK.00100",
            exchange_time=NOW,
            last_price=356.6,
            prev_close=300.4,
            volume=1_729_830,
            quality=DataQuality.GOOD,
        )
        primitive = to_primitive(quote)
        restored = QuoteSnapshot(
            stock_code=primitive["stock_code"],
            exchange_time=datetime.fromisoformat(primitive["exchange_time"]),
            last_price=primitive["last_price"],
            prev_close=primitive["prev_close"],
            open_price=primitive["open_price"],
            high_price=primitive["high_price"],
            low_price=primitive["low_price"],
            volume=primitive["volume"],
            turnover=primitive["turnover"],
            quality=DataQuality(primitive["quality"]),
        )
        self.assertEqual(restored, quote)

    def test_candidate_score_is_bounded(self) -> None:
        with self.assertRaisesRegex(ValueError, "score"):
            TradeCandidate(
                stock_code="HK.00100",
                as_of=NOW,
                status=CandidateStatus.OBSERVE,
                score=101,
                quality=DataQuality.GOOD,
                reason_codes=("ACTIVE",),
                invalidation_conditions=("FLOW_REVERSED",),
            )

    def test_position_constraints_and_rotation_target(self) -> None:
        with self.assertRaisesRegex(ValueError, "sellable|可卖数量"):
            PositionSnapshot(
                stock_code="HK.00100",
                as_of=NOW,
                quantity=100,
                sellable_quantity=200,
                cost_price=300,
                current_price=356.6,
                peak_price=358.2,
                lot_size=100,
            )
        with self.assertRaisesRegex(ValueError, "replacement_stock_code"):
            PositionDecision(
                stock_code="HK.00100",
                as_of=NOW,
                status=PositionStatus.ROTATION_READY,
                action=DecisionAction.ROTATE,
                reason_codes=("EFFICIENCY_DECAY",),
                confidence=0.8,
            )

    def test_transition_carries_strategy_version(self) -> None:
        transition = StrategyTransition(
            stock_code="HK.00100",
            strategy_version="rotation-r1",
            old_state=StrategyStatus.WATCHING,
            new_state=StrategyStatus.CONFIRMED,
            occurred_at=NOW,
            reason_code="FLOW_CONFIRMED",
            evidence_event_ids=("tick-1", "tick-2"),
        )
        self.assertEqual(transition.strategy_version, "rotation-r1")

    def test_real_and_virtual_clocks_share_contract(self) -> None:
        clocks: tuple[Clock, ...] = (SystemClock(), VirtualClock(NOW))
        self.assertTrue(all(clock.now().tzinfo is not None for clock in clocks))

        replay_clock = VirtualClock(NOW)
        self.assertEqual(replay_clock.advance(timedelta(seconds=5)), NOW + timedelta(seconds=5))
        with self.assertRaisesRegex(ValueError, "倒退"):
            replay_clock.set(NOW)

    def test_config_rejects_invalid_capacity(self) -> None:
        with self.assertRaisesRegex(ValueError, "event_bus_capacity"):
            V2Config(event_bus_capacity=0)


if __name__ == "__main__":
    unittest.main()
