import unittest
from unittest.mock import MagicMock

from futu import SubType

from simple_trade.services.subscription.subscription_helper import SubscriptionHelper


class FakeSubscriptionManager:
    def __init__(self, *, fail_candidate: bool = False) -> None:
        self.subscribed_stocks = {"HK.00001", "HK.00002"}
        self.ticker_subscribed_stocks = {"HK.00001", "HK.00002"}
        self._max_ticker_subscription = 2
        self.fail_candidate = fail_candidate

    def unsubscribe_multi_types(self, codes, sub_types):
        if SubType.TICKER in sub_types:
            self.ticker_subscribed_stocks.difference_update(codes)
        return {"success": True}

    def subscribe_multi_types(self, codes, sub_types):
        code = codes[0]
        if code == "HK.00100" and self.fail_candidate:
            return {"success": False, "message": "test failure"}
        if SubType.QUOTE in sub_types:
            self.subscribed_stocks.add(code)
        if SubType.TICKER in sub_types:
            self.ticker_subscribed_stocks.add(code)
        return {"success": True, "message": "ok"}


def make_helper(manager: FakeSubscriptionManager) -> SubscriptionHelper:
    helper = SubscriptionHelper.__new__(SubscriptionHelper)
    helper.subscription_manager = manager
    helper.priority_stocks = {"HK.00001"}
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


if __name__ == "__main__":
    unittest.main()
