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
        if SubType.QUOTE in sub_types:
            self.subscribed_stocks.difference_update(codes)
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
    def test_exposure_quote_replaces_candidate_when_quote_capacity_is_full(self) -> None:
        manager = FakeSubscriptionManager()
        manager._max_quote_subscription = 2
        original = manager.subscribe_multi_types
        def subscribe(codes, types):
            if SubType.QUOTE in types and len(manager.subscribed_stocks) >= 2:
                return {"success": False, "message": "quota full"}
            return original(codes, types)
        manager.subscribe_multi_types = subscribe
        helper = make_helper(manager)
        helper.set_candidate_priority_stocks(["HK.00002"])
        helper.set_exposure_priority_stocks(["HK.00100"])
        self.assertTrue(helper.subscribe_for_candidate_data("HK.00100", for_exposure=True)["success"])
        self.assertEqual(manager.subscribed_stocks, {"HK.00001", "HK.00100"})
        self.assertEqual(manager.ticker_subscribed_stocks, {"HK.00001", "HK.00100"})

    def test_exposure_quote_failure_restores_displaced_quote(self) -> None:
        manager = FakeSubscriptionManager(fail_candidate=True)
        manager._max_quote_subscription = 2
        helper = make_helper(manager)
        helper.set_exposure_priority_stocks(["HK.00100"])
        self.assertFalse(helper.subscribe_for_candidate_data("HK.00100", for_exposure=True)["success"])
        self.assertEqual(manager.subscribed_stocks, {"HK.00001", "HK.00002"})
        self.assertEqual(manager.ticker_subscribed_stocks, {"HK.00001", "HK.00002"})

    def test_exposure_quotes_obey_shared_capacity_and_ticker_reserve(self) -> None:
        from simple_trade.api.subscription_manager import SubscriptionManager
        client = MagicMock()
        client.subscribe_stocks.return_value = (0, None)
        client.unsubscribe_stocks.return_value = (0, None)
        manager = SubscriptionManager(futu_client=client)
        manager._total_quota = 5
        manager._ticker_quota_reserve = 3
        manager._quote_subscribed.update({"HK.00001", "HK.00002"})
        manager._ticker_subscribed.update({"HK.00001", "HK.00002"})
        helper = make_helper(manager)
        helper.set_exposure_priority_stocks(["HK.00100"])
        from unittest.mock import patch
        with patch('simple_trade.utils.rate_limiter.wait_for_api'):
            self.assertTrue(helper.subscribe_for_candidate_data("HK.00100", for_exposure=True)["success"])
        self.assertEqual(manager.subscribed_stocks, {"HK.00001", "HK.00100"})
        self.assertIn("HK.00100", manager.ticker_subscribed_stocks)
        self.assertEqual(len(manager.subscribed_stocks) + len(manager.ticker_subscribed_stocks), 5)

    def test_exposure_can_replace_candidate_but_not_another_position(self) -> None:
        manager = FakeSubscriptionManager()
        helper = make_helper(manager)
        helper.set_candidate_priority_stocks(["HK.00002"])
        helper.set_exposure_priority_stocks(["HK.00100", "HK.00001"])
        result = helper.subscribe_for_candidate_data("HK.00100", for_exposure=True)
        self.assertTrue(result["success"])
        self.assertEqual(result["replaced"], "HK.00002")
        self.assertEqual(manager.ticker_subscribed_stocks, {"HK.00001", "HK.00100"})
        helper.set_candidate_priority_stocks([])
        self.assertEqual(helper.get_exposure_priority_stocks(), {"HK.00100", "HK.00001"})

    def test_quote_is_kept_when_all_ticker_slots_protected(self) -> None:
        manager = FakeSubscriptionManager()
        helper = make_helper(manager)
        helper.set_exposure_priority_stocks(["HK.00001", "HK.00002", "HK.00100"])
        result = helper.subscribe_for_candidate_data("HK.00100", for_exposure=True)
        self.assertFalse(result["success"])
        self.assertIn("HK.00100", manager.subscribed_stocks)
        self.assertEqual(manager.ticker_subscribed_stocks, {"HK.00001", "HK.00002"})
        self.assertFalse(helper.subscribe_for_candidate_data("HK.00700")["success"])

    def test_exposure_respects_subscription_minimum_duration(self) -> None:
        manager = FakeSubscriptionManager()
        manager.subscribe_times["HK.00002"] = time.time()
        helper = make_helper(manager)
        helper.set_exposure_priority_stocks(["HK.00100"])
        self.assertFalse(helper.subscribe_for_candidate_data("HK.00100", for_exposure=True)["success"])
        self.assertIn("HK.00100", manager.subscribed_stocks)
        self.assertEqual(manager.ticker_subscribed_stocks, {"HK.00001", "HK.00002"})

    def test_failed_ticker_preserves_quote_and_restores_displaced_candidate(self) -> None:
        manager = FakeSubscriptionManager()
        original = manager.subscribe_multi_types
        def subscribe(codes, types):
            if codes == ["HK.00100"] and SubType.TICKER in types:
                return {"success": True}  # SDK success alone is not subscription evidence.
            return original(codes, types)
        manager.subscribe_multi_types = subscribe
        helper = make_helper(manager)
        helper.set_exposure_priority_stocks(["HK.00100"])
        self.assertFalse(helper.subscribe_for_candidate_data("HK.00100", for_exposure=True)["success"])
        self.assertIn("HK.00100", manager.subscribed_stocks)
        self.assertEqual(manager.ticker_subscribed_stocks, {"HK.00001", "HK.00002"})

    def test_released_exposure_does_not_start_stale_subscription_request(self) -> None:
        manager = FakeSubscriptionManager()
        helper = make_helper(manager)
        helper.set_exposure_priority_stocks([])
        self.assertTrue(helper.subscribe_for_candidate_data("HK.00100", for_exposure=True)["success"])
        self.assertNotIn("HK.00100", manager.subscribed_stocks)

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
