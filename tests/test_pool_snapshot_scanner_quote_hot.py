import unittest
import time

from simple_trade.services.market_data.pool_snapshot_scanner import (
    AnomalyStock,
    PoolSnapshotScanner,
)


class FakeSubscriptionManager:
    subscribed_stocks = {"HK.00001"}
    ticker_subscribed_stocks = {"HK.00001"}


class FakeContainer:
    subscription_manager = FakeSubscriptionManager()


class PoolSnapshotScannerQuoteHotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scanner = PoolSnapshotScanner(FakeContainer())
        self.scanner._batch_get_capital_flow = lambda codes: {}

    def test_quote_activity_can_request_data_without_claiming_fund_flow(self) -> None:
        rows = [{
            "code": "HK.00100",
            "last_price": 101.0,
            "change_rate": 1.2,
            "volume_ratio": 2.0,
            "turnover_rate": 1.0,
            "turnover": 20_000_000,
            "volume": 200_000,
        }]

        result = self.scanner._filter_by_snapshot(rows)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["anomaly_type"], "quote_hot")
        self.assertLess(result[0]["capital_score"], self.scanner.CAPITAL_SCORE_MIN)

    def test_quote_hot_rotation_does_not_require_shrinkage_pattern(self) -> None:
        self.scanner._last_anomalies["HK.00100"] = AnomalyStock(
            code="HK.00100",
            name="Test",
            change_rate=1.2,
            volume_ratio=2.0,
            turnover_rate=1.0,
            price=101.0,
            anomaly_type="quote_hot",
            has_shrinkage=False,
            detected_at="10:00:00",
        )
        self.scanner._cooldown["HK.00100"] = time.time()

        self.assertEqual(self.scanner.get_rotation_candidates(), ["HK.00100"])

    def test_stale_quote_hot_signal_is_not_rotated_back_into_ticker_quota(self) -> None:
        self.scanner._last_anomalies["HK.00100"] = AnomalyStock(
            code="HK.00100",
            name="Test",
            change_rate=1.2,
            volume_ratio=2.0,
            turnover_rate=1.0,
            price=101.0,
            anomaly_type="quote_hot",
            has_shrinkage=False,
            detected_at="09:30:00",
        )
        self.scanner._cooldown["HK.00100"] = (
            time.time() - self.scanner._cooldown_seconds - 1
        )

        self.assertEqual(self.scanner.get_rotation_candidates(), [])
