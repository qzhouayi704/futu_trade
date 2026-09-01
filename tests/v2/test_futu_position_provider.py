import unittest
from datetime import datetime, timezone

from simple_trade.v2.domain.enums import DataQuality
from simple_trade.v2.infrastructure.broker.futu_position_provider import FutuPositionProvider


NOW = datetime(2026, 8, 31, 2, 0, tzinfo=timezone.utc)


class FutuPositionProviderTests(unittest.TestCase):
    def test_positions_and_only_active_orders_are_strongly_typed(self) -> None:
        provider = FutuPositionProvider()
        result = provider.adapt_results(
            {"success": True, "positions": [{
                "stock_code": "HK.00100", "stock_name": "MINIMAX-W",
                "qty": 1000, "can_sell_qty": 800, "cost_price": 100,
                "nominal_price": 102,
            }]},
            {"success": True, "orders": [
                {"order_id": "open-1", "stock_code": "HK.00100",
                 "trd_side": "SELL", "order_status": "SUBMITTED", "qty": 200},
                {"order_id": "done-1", "stock_code": "HK.00100",
                 "trd_side": "SELL", "order_status": "FILLED_ALL", "qty": 100},
                {"order_id": "partial-1", "stock_code": "HK.00100",
                 "trd_side": "SELL", "order_status": "FILLED_PART", "qty": 300,
                 "dealt_qty": 100},
            ]},
            quote_rows=[{"code": "HK.00100", "last_price": 103, "lot_size": 100}],
            as_of=NOW,
        )

        self.assertTrue(result.authoritative)
        self.assertIs(result.quality, DataQuality.GOOD)
        self.assertEqual(len(result.active_orders), 2)
        self.assertEqual(result.positions[0].active_order_ids, ("open-1", "partial-1"))
        self.assertEqual(result.positions[0].current_price, 103)
        self.assertEqual(result.positions[0].lot_size, 100)

    def test_pipeline_empty_rows_are_not_authoritative(self) -> None:
        result = FutuPositionProvider().adapt_rows({}, as_of=NOW)

        self.assertFalse(result.authoritative)
        self.assertIs(result.quality, DataQuality.INVALID)
        self.assertIn("POSITION_QUERY_NOT_AUTHORITATIVE", result.reason_codes)


if __name__ == "__main__":
    unittest.main()
