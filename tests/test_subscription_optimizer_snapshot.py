from unittest.mock import Mock

import pandas as pd

from simple_trade.services.realtime.subscription_optimizer import SubscriptionOptimizer


def test_activity_discovery_uses_snapshot_without_subscribing():
    subscription_manager = Mock()
    quote_service = Mock()
    quote_service.get_market_snapshot.return_value = (
        0,
        pd.DataFrame(
            [
                {
                    "code": "HK.02706",
                    "last_price": 60.0,
                    "turnover": 10_000_000,
                    "turnover_rate": 2.0,
                    "volume": 1_000_000,
                }
            ]
        ),
    )
    optimizer = SubscriptionOptimizer(subscription_manager, quote_service)

    result = optimizer.process_batches(
        [{"code": "HK.02706", "name": "示例"}],
        lambda batch, quotes: {"active": batch, "inactive": []},
    )

    assert [item["code"] for item in result["active"]] == ["HK.02706"]
    quote_service.get_market_snapshot.assert_called_once_with(["HK.02706"])
    subscription_manager.subscribe.assert_not_called()
    subscription_manager.unsubscribe.assert_not_called()
