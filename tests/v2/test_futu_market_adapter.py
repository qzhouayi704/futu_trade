import ast
import unittest
from datetime import datetime, timezone
from pathlib import Path

from simple_trade.api.ticker_push_handler import TickerPushHandler
from simple_trade.v2.domain.enums import DataQuality, EventType, TickDirection
from simple_trade.v2.domain.events import DataQualityEvent, OrderBookEvent, QuoteEvent, TickEvent
from simple_trade.v2.infrastructure.futu_market_adapter import FutuMarketAdapter


RECEIVED = datetime(2026, 8, 31, 2, 0, tzinfo=timezone.utc)


class FutuMarketAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = FutuMarketAdapter(strategy_version="test-v2")

    def test_quote_fields_and_exchange_time(self) -> None:
        events = self.adapter.adapt_quote(
            {
                "code": "HK.00100",
                "last_price": 356.6,
                "prev_close_price": 300.4,
                "open_price": 299.0,
                "high_price": 358.2,
                "low_price": 296.0,
                "volume": 1_729_830,
                "turnover": 5_651_000_000,
                "turnover_rate": 3.2,
                "amplitude": 20.7,
                "lot_size": 100,
                "plate_name": "AI",
                "data_date": "2026-08-31",
                "data_time": "10:00:00",
                "is_realtime": True,
            },
            received_time=RECEIVED,
        )

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertIsInstance(event, QuoteEvent)
        self.assertEqual(event.quote.last_price, 356.6)
        self.assertEqual(event.exchange_time.isoformat(), "2026-08-31T10:00:00+08:00")
        self.assertIs(event.quote.quality, DataQuality.GOOD)
        self.assertEqual(event.quote.turnover_rate, 3.2)
        self.assertEqual(event.quote.amplitude, 20.7)
        self.assertEqual(event.quote.lot_size, 100)
        self.assertEqual(event.quote.sector_code, "AI")

    def test_duplicate_gap_and_out_of_order_sequences(self) -> None:
        base = {
            "code": "HK.00100",
            "time": "2026-08-31 10:00:00",
            "price": 356.6,
            "volume": 100,
            "turnover": 35_660,
            "ticker_direction": "BUY",
        }
        first = self.adapter.adapt_ticker({**base, "sequence": 10}, received_time=RECEIVED)
        duplicate = self.adapter.adapt_ticker({**base, "sequence": 10}, received_time=RECEIVED)
        gap = self.adapter.adapt_ticker(
            {**base, "time": "2026-08-31 10:00:02", "sequence": 13},
            received_time=RECEIVED,
        )
        out_of_order = self.adapter.adapt_ticker(
            {**base, "time": "2026-08-31 10:00:01", "sequence": 12},
            received_time=RECEIVED,
        )

        self.assertEqual(len(first), 1)
        self.assertEqual(duplicate, ())
        self.assertEqual([event.event_type for event in gap], [
            EventType.DATA_QUALITY_CHANGED,
            EventType.TICK_RECEIVED,
        ])
        self.assertIs(gap[-1].tick.quality, DataQuality.DEGRADED)
        self.assertEqual(len(out_of_order), 1)
        self.assertIsInstance(out_of_order[0], DataQualityEvent)
        stats = self.adapter.snapshot()
        self.assertEqual(stats.duplicates, 1)
        self.assertEqual(stats.sequence_gaps, 2)
        self.assertEqual(stats.out_of_order, 1)

    def test_no_sequence_uses_business_key_deduplication(self) -> None:
        row = {
            "code": "HK.00100",
            "time": "2026-08-31 10:00:00",
            "price": 356.6,
            "volume": 100,
            "ticker_direction": "BULL",
        }
        first = self.adapter.adapt_ticker(row, received_time=RECEIVED)
        duplicate = self.adapter.adapt_ticker(row, received_time=RECEIVED)

        self.assertIsInstance(first[-1], TickEvent)
        self.assertIs(first[-1].tick.direction, TickDirection.BUY)
        self.assertEqual(duplicate, ())

    def test_missing_order_book_side_is_degraded(self) -> None:
        events = self.adapter.adapt_order_book(
            "HK.00100",
            {"Bid": [(356.4, 1000, 3)], "Ask": []},
            received_time=RECEIVED,
        )

        self.assertIsInstance(events[0], DataQualityEvent)
        self.assertIsInstance(events[1], OrderBookEvent)
        self.assertIs(events[1].order_book.quality, DataQuality.DEGRADED)
        self.assertEqual(events[1].order_book.best_bid, 356.4)
        self.assertIsNone(events[1].order_book.best_ask)

    def test_v2_sdk_ingress_contains_no_business_side_effects(self) -> None:
        path = Path(__file__).resolve().parents[2] / "simple_trade" / "api" / "ticker_push_handler.py"
        source_text = path.read_text(encoding="utf-8")
        tree = ast.parse(source_text)
        methods = {
            node.name: (ast.get_source_segment(source_text, node) or "").lower()
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name in {"on_recv_rsp", "_handle_ticker_push", "_feed_v2_shadow"}
        }
        boundary_source = "\n".join(methods.values())
        for forbidden in (
            "db_manager",
            "wechat",
            "_feed_momentum",
            "_feed_capital_accumulator",
            "_persist_to_db",
        ):
            self.assertNotIn(forbidden, boundary_source)

    def test_sdk_callback_boundary_only_queues_owned_batch(self) -> None:
        class FakeColumn:
            iloc = ["HK.00100"]

        class FakeFrame:
            empty = False
            columns = ("code",)

            def __getitem__(self, key):
                return FakeColumn()

            def copy(self, deep=True):
                return FakeFrame()

        handler = TickerPushHandler()
        handler._ensure_processor = lambda: None
        handler._handle_ticker_push(FakeFrame())

        self.assertEqual(handler._process_queue.qsize(), 1)
        self.assertEqual(handler._tick_count, 0)
        self.assertEqual(handler._db_buffer, [])


if __name__ == "__main__":
    unittest.main()
