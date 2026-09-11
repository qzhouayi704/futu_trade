import unittest
import time
from unittest.mock import MagicMock

from futu import SubType

from simple_trade.services.subscription.subscription_helper import SubscriptionHelper


class FakeSubscriptionManager:
    def __init__(self, *, fail_candidate: bool = False, max_ticker: int = 2) -> None:
        self.subscribed_stocks = {"HK.00001", "HK.00002"}
        self.ticker_subscribed_stocks = {"HK.00001", "HK.00002"}
        self._max_ticker_subscription = max_ticker
        self.fail_candidate = fail_candidate
        self.subscribe_times = {code: 0.0 for code in self.ticker_subscribed_stocks}

    def get_subscribe_time(self, code):
        return self.subscribe_times.get(code, 0.0)

    def unsubscribe_multi_types(self, codes, sub_types):
        if SubType.TICKER in sub_types:
            self.ticker_subscribed_stocks.difference_update(codes)
        return {"success": True}

    def subscribe_multi_types(self, codes, sub_types):
        if "HK.00100" in codes and self.fail_candidate:
            return {"success": False, "message": "test failure"}
        for code in codes:
            if SubType.QUOTE in sub_types:
                self.subscribed_stocks.add(code)
            if SubType.TICKER in sub_types:
                self.ticker_subscribed_stocks.add(code)
                self.subscribe_times[code] = time.time()
        return {"success": True, "message": "ok"}


def make_helper(manager: FakeSubscriptionManager) -> SubscriptionHelper:
    helper = SubscriptionHelper.__new__(SubscriptionHelper)
    helper.subscription_manager = manager
    helper.priority_stocks = {"HK.00001"}
    helper.candidate_priority_stocks = set()
    helper._candidate_priority_order = ()
    helper._get_active_stocks = MagicMock(return_value=[])
    return helper


class CandidateSubscriptionHelperTests(unittest.TestCase):
    def test_candidate_replaces_only_non_priority_ticker(self) -> None:
        manager = FakeSubscriptionManager()
        helper = make_helper(manager)

        result = helper.subscribe_for_candidate_data("hk.00100")

        self.assertTrue(result["success"])
        self.assertEqual(result["replaced"], "HK.00002")
        self.assertIn("HK.00001", manager.ticker_subscribed_stocks)
        self.assertIn("HK.00100", manager.ticker_subscribed_stocks)
        self.assertNotIn("HK.00002", manager.ticker_subscribed_stocks)

    def test_failed_candidate_restores_replaced_ticker(self) -> None:
        manager = FakeSubscriptionManager(fail_candidate=True)
        helper = make_helper(manager)

        result = helper.subscribe_for_candidate_data("HK.00100")

        self.assertFalse(result["success"])
        self.assertEqual(manager.ticker_subscribed_stocks, {"HK.00001", "HK.00002"})

    def test_ranked_sync_keeps_protected_stocks_and_headroom(self) -> None:
        manager = FakeSubscriptionManager(max_ticker=5)
        manager.subscribed_stocks = {
            "HK.POS", "HK.CAND", "HK.A1", "HK.A2", "HK.A3", "HK.STALE",
        }
        manager.ticker_subscribed_stocks = {"HK.POS", "HK.STALE"}
        manager.subscribe_times = {"HK.POS": 0.0, "HK.STALE": 0.0}
        helper = make_helper(manager)
        helper.priority_stocks = {"HK.POS"}
        helper.set_candidate_priority_stocks(["HK.CAND"])
        helper._TICKER_PRIORITY_HEADROOM = 1

        helper._sync_ticker_subscriptions([
            {"code": "HK.A1"}, {"code": "HK.A2"}, {"code": "HK.A3"},
        ])

        self.assertEqual(
            manager.ticker_subscribed_stocks,
            {"HK.POS", "HK.CAND", "HK.A1", "HK.A2"},
        )
        self.assertNotIn("HK.STALE", manager.ticker_subscribed_stocks)

    def test_candidate_does_not_evict_subscription_younger_than_one_minute(self) -> None:
        manager = FakeSubscriptionManager()
        manager.subscribe_times["HK.00002"] = time.time()
        helper = make_helper(manager)

        result = helper.subscribe_for_candidate_data("HK.00100")

        self.assertFalse(result["success"])
        self.assertEqual(manager.ticker_subscribed_stocks, {"HK.00001", "HK.00002"})


if __name__ == "__main__":
    unittest.main()
