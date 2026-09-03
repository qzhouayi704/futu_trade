import unittest
from datetime import datetime, timedelta, timezone

from simple_trade.v2.application.features.capital_windows import CapitalWindowEngine
from simple_trade.v2.domain.enums import CapitalMemoryState, DataQuality, TickDirection
from simple_trade.v2.domain.features import CapitalBaseline
from simple_trade.v2.domain.market import TickAggregate, TickTrade


NOW = datetime(2026, 8, 31, 10, 0, tzinfo=timezone(timedelta(hours=8)))


def tick(
    seconds: int,
    *,
    amount: float = 200_000,
    direction: TickDirection = TickDirection.BUY,
    sequence: int | None = None,
    price: float = 100.0,
) -> TickTrade:
    volume = max(1, int(amount / price))
    return TickTrade(
        stock_code="HK.00100",
        exchange_time=NOW + timedelta(seconds=seconds),
        price=price,
        volume=volume,
        turnover=amount,
        direction=direction,
        sequence=sequence,
    )


class CapitalWindowTests(unittest.TestCase):
    @staticmethod
    def _seed_good_baseline(engine: CapitalWindowEngine) -> None:
        engine.set_baselines((CapitalBaseline(
            stock_code="HK.00100",
            large_order_threshold=100_000,
            flow_scale=300_000,
            quality=DataQuality.GOOD,
        ),))

    def test_per_stock_baseline_controls_threshold_and_event_span(self) -> None:
        engine = CapitalWindowEngine()
        engine.set_baselines((CapitalBaseline(
            stock_code="HK.00100",
            large_order_threshold=300_000,
            flow_scale=900_000,
            quality=DataQuality.GOOD,
        ),))
        engine.on_tick(tick(0, amount=200_000, sequence=1))
        engine.on_tick(tick(10, amount=400_000, sequence=2))
        engine.on_tick(tick(320, amount=500_000, sequence=3, price=101))

        window = next(
            item for item in engine.snapshots("HK.00100", NOW + timedelta(seconds=321))
            if item.window_seconds == 900
        )
        self.assertEqual(window.sample_count, 2)
        self.assertEqual(window.large_order_threshold, 300_000)
        self.assertEqual(window.flow_scale, 900_000)
        self.assertEqual(window.independent_buy_events, 2)
        self.assertEqual(window.independent_buy_span_seconds, 310)

    def test_one_five_fifteen_thirty_sixty_minute_boundaries(self) -> None:
        engine = CapitalWindowEngine()
        engine.on_tick(tick(0, sequence=1))

        at_boundary = engine.snapshots("HK.00100", NOW + timedelta(seconds=60))
        after_boundary = engine.snapshots("HK.00100", NOW + timedelta(seconds=61))

        self.assertEqual(tuple(item.window_seconds for item in at_boundary), (60, 300, 900, 1800, 3600))
        self.assertEqual(at_boundary[0].sample_count, 1)
        self.assertEqual(after_boundary[0].sample_count, 0)
        self.assertEqual(after_boundary[1].sample_count, 1)

    def test_split_orders_keep_amount_but_count_one_independent_event(self) -> None:
        engine = CapitalWindowEngine()
        self._seed_good_baseline(engine)
        for index, price in enumerate((100.0, 100.05, 100.10), start=1):
            engine.on_tick(tick(index - 1, sequence=index, price=price))

        window = engine.snapshots("HK.00100", NOW + timedelta(seconds=3))[0]
        memory = engine.memory("HK.00100", NOW + timedelta(seconds=3))

        self.assertEqual(window.big_buy_count, 3)
        self.assertEqual(window.independent_buy_events, 1)
        self.assertEqual(window.buy_amount, 600_000)
        self.assertAlmostEqual(memory.decayed_buy_events, 1.0, places=3)
        self.assertEqual(memory.recent_15m_buy_events, 1)

    def test_memory_decay_uses_trading_time_and_pauses_for_lunch(self) -> None:
        engine = CapitalWindowEngine(memory_half_life_minutes=30)
        self._seed_good_baseline(engine)
        engine.on_tick(tick(6_300, amount=600_000, sequence=1))  # 11:45

        at_afternoon_open = engine.memory(
            "HK.00100", NOW + timedelta(seconds=10_800)  # 13:00
        )
        after_half_life = engine.memory(
            "HK.00100", NOW + timedelta(seconds=11_700)  # 13:15
        )

        self.assertAlmostEqual(
            at_afternoon_open.decayed_buy_amount, 600_000 * 2 ** -0.5, delta=1
        )
        self.assertEqual(at_afternoon_open.recent_15m_buy_events, 1)
        self.assertAlmostEqual(after_half_life.decayed_buy_amount, 300_000, delta=1)
        self.assertEqual(after_half_life.recent_15m_buy_events, 0)

    def test_all_day_outflow_can_become_recent_reversal_watch_state(self) -> None:
        engine = CapitalWindowEngine()
        self._seed_good_baseline(engine)
        engine.on_tick(tick(
            0, amount=5_000_000, direction=TickDirection.SELL, sequence=1
        ))
        engine.on_tick(tick(13_800, amount=2_000_000, sequence=2, price=99.0))
        engine.on_tick(tick(13_810, amount=2_000_000, sequence=3, price=99.2))

        memory = engine.memory("HK.00100", NOW + timedelta(seconds=14_400))

        self.assertEqual(memory.day_main_net, -1_000_000)
        self.assertEqual(memory.recent_15m_buy_events, 2)
        self.assertGreater(memory.decayed_main_net, 3_000_000)
        self.assertAlmostEqual(memory.day_recovery_ratio, 0.8, places=3)
        self.assertIs(memory.state, CapitalMemoryState.REVERSING)

    def test_inflow_and_outflow_offset_net_count_and_direction(self) -> None:
        engine = CapitalWindowEngine()
        engine.on_tick(tick(0, amount=500_000, sequence=1))
        engine.on_tick(
            tick(10, amount=300_000, direction=TickDirection.SELL, sequence=2)
        )
        window = engine.snapshots("HK.00100", NOW + timedelta(seconds=11))[0]

        self.assertEqual(window.main_net, 200_000)
        self.assertEqual(window.independent_buy_events, 1)
        self.assertEqual(window.independent_sell_events, 1)
        self.assertIs(window.net_direction, TickDirection.BUY)
        self.assertEqual(window.buy_sell_ratio, 0.625)

    def test_active_tape_pressure_includes_orders_below_large_threshold(self) -> None:
        engine = CapitalWindowEngine(large_order_threshold=100_000)
        engine.on_tick(tick(0, amount=80_000, sequence=1))
        engine.on_tick(tick(
            10, amount=90_000, direction=TickDirection.SELL, sequence=2
        ))
        engine.on_tick(tick(
            20, amount=70_000, direction=TickDirection.SELL, sequence=3
        ))

        window = engine.snapshots("HK.00100", NOW + timedelta(seconds=21))[0]

        self.assertEqual(window.sample_count, 0)
        self.assertEqual(window.active_buy_amount, 80_000)
        self.assertEqual(window.active_sell_amount, 160_000)
        self.assertEqual(window.active_net, -80_000)
        self.assertAlmostEqual(window.active_buy_ratio, 1 / 3, places=6)

    def test_replay_duplicate_ignores_unstable_sequence(self) -> None:
        engine = CapitalWindowEngine()
        replayed = tick(0, sequence=None)
        live = tick(0, sequence=999)

        self.assertTrue(engine.on_tick(replayed).accepted)
        self.assertFalse(engine.on_tick(live).accepted)
        window = engine.snapshots("HK.00100", NOW + timedelta(seconds=1))[0]
        self.assertEqual(window.sample_count, 1)
        self.assertEqual(window.active_buy_amount, 200_000)

    def test_business_duplicate_is_rejected_even_without_adapter(self) -> None:
        engine = CapitalWindowEngine()
        source = tick(0, sequence=None)

        self.assertTrue(engine.on_tick(source).accepted)
        self.assertFalse(engine.on_tick(source).accepted)
        self.assertEqual(
            engine.snapshots("HK.00100", NOW + timedelta(seconds=1))[0].sample_count,
            1,
        )

    def test_seed_preserves_cumulative_values_but_marks_window_quality(self) -> None:
        engine = CapitalWindowEngine()
        engine.seed(
            TickAggregate(
                stock_code="HK.00100",
                as_of=NOW,
                window_seconds=600,
                buy_amount=0,
                sell_amount=0,
                main_net=0,
                big_buy_count=4,
                big_sell_count=1,
                independent_buy_events=4,
                independent_sell_events=1,
                buy_sell_ratio=0.8,
                cumulative_main_net=2_000_000,
                cumulative_peak=3_000_000,
                cumulative_trough=-100_000,
                last_sequence=20,
                sample_count=5,
                quality=DataQuality.DEGRADED,
            )
        )
        engine.on_tick(tick(5, amount=500_000, sequence=21))
        window = engine.snapshots("HK.00100", NOW + timedelta(seconds=6))[0]

        self.assertEqual(window.cumulative_main_net, 2_500_000)
        self.assertEqual(window.cumulative_peak, 3_000_000)
        self.assertIs(window.quality, DataQuality.DEGRADED)


if __name__ == "__main__":
    unittest.main()
