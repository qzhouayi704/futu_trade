from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd

from simple_trade.routers.data.activity_refilter import _get_stocks_to_recheck
from simple_trade.services.realtime.activity_cache_policy import ActivityCachePolicy
from simple_trade.services.realtime.activity_calculator import ActivityCalculator
from simple_trade.services.core.stock_marker import StockMarkerService
from simple_trade.services.core.async_quote_pusher import AsyncQuotePusher
from simple_trade.services.subscription.subscription_helper import SubscriptionHelper


def test_activity_cache_policy_uses_state_specific_ttls():
    policy = ActivityCachePolicy()
    now = datetime(2026, 9, 3, 10, 0, 0)

    assert policy.is_fresh({
        'is_active': True,
        'activity_score': 0.8,
        'created_at': now - timedelta(seconds=299),
    }, now)
    assert not policy.is_fresh({
        'is_active': True,
        'activity_score': 0.8,
        'created_at': now - timedelta(seconds=300),
    }, now)
    assert not policy.is_fresh({
        'is_active': False,
        'activity_score': 0,
        'created_at': now - timedelta(seconds=120),
    }, now)
    assert not policy.is_fresh({
        'is_active': False,
        'activity_score': -1,
        'created_at': now - timedelta(seconds=30),
    }, now)


def test_activity_cache_policy_uses_opening_and_regular_cadence():
    policy = ActivityCachePolicy()

    assert policy.refilter_interval_seconds(datetime(2026, 9, 3, 9, 45)) == 120
    assert policy.refilter_interval_seconds(datetime(2026, 9, 3, 10, 0)) == 300
    assert policy.refilter_interval_seconds(datetime(2026, 9, 3, 13, 15)) == 120
    assert policy.refilter_interval_seconds(datetime(2026, 9, 3, 13, 30)) == 300


def test_incremental_refilter_only_returns_missing_or_expired(monkeypatch):
    now = datetime.now()
    records = {
        'HK.FRESH': {
            'is_active': True,
            'activity_score': 0.8,
            'created_at': now - timedelta(seconds=60),
        },
        'HK.EXPIRED': {
            'is_active': False,
            'activity_score': 0,
            'created_at': now - timedelta(seconds=121),
        },
    }
    container = SimpleNamespace(
        config=SimpleNamespace(
            realtime_activity_filter={},
            monitor_stocks_limit_by_market={'HK': 100, 'US': 0},
        ),
        db_manager=SimpleNamespace(
            stock_activity_queries=SimpleNamespace(
                get_daily_checked_stocks=lambda _date: records
            )
        ),
    )
    pool = {'stocks': [
        {'code': 'HK.FRESH', 'market': 'HK'},
        {'code': 'HK.EXPIRED', 'market': 'HK'},
        {'code': 'HK.NEW', 'market': 'HK'},
        {'code': 'US.SKIP', 'market': 'US'},
    ]}
    monkeypatch.setattr(
        'simple_trade.routers.data.activity_refilter.get_state_manager',
        lambda: SimpleNamespace(get_stock_pool=lambda: pool),
    )

    result = _get_stocks_to_recheck(container)

    assert {stock['code'] for stock in result} == {'HK.EXPIRED', 'HK.NEW'}


def test_discovery_score_admits_relative_hotspot_before_hard_threshold():
    config = SimpleNamespace(realtime_activity_filter={
        'discovery_score_threshold': 0.65,
        'emerging_liquidity_floor_ratio': 0.35,
    })
    calculator = ActivityCalculator(config=config)
    quotes = pd.DataFrame([
        {'code': 'HK.HOT', 'turnover_rate': 0.25, 'turnover': 4000000,
         'volume': 450000, 'last_price': 20, 'change_rate': 4.0},
        {'code': 'HK.COLD1', 'turnover_rate': 0.02, 'turnover': 100000,
         'volume': 20000, 'last_price': 10, 'change_rate': 0.1},
        {'code': 'HK.COLD2', 'turnover_rate': 0.01, 'turnover': 80000,
         'volume': 10000, 'last_price': 8, 'change_rate': -1.0},
    ])

    result = calculator.filter_stocks_by_activity(
        batch=[
            {'code': 'HK.HOT', 'market': 'HK'},
            {'code': 'HK.COLD1', 'market': 'HK'},
            {'code': 'HK.COLD2', 'market': 'HK'},
        ],
        quote_data=quotes,
        min_turnover_rate=0.3,
        min_turnover_amount=5000000,
        min_volume=500000,
        min_price_config={},
    )

    assert [stock['code'] for stock in result['active']] == ['HK.HOT']
    assert result['active'][0]['activity_reason'] == 'emerging_hotspot'


def test_subscription_cleanup_requires_two_inactive_refreshes():
    helper = SubscriptionHelper.__new__(SubscriptionHelper)
    helper.config = SimpleNamespace(
        realtime_activity_filter={'demotion_confirmation_cycles': 2}
    )
    helper.priority_stocks = set()
    helper._inactive_refresh_counts = {}
    helper.subscription_manager = MagicMock()
    helper.subscription_manager.subscribed_stocks = {'HK.OLD', 'HK.KEEP'}
    helper.subscription_manager.get_subscribe_time.return_value = 0
    helper.subscription_manager.unsubscribe.return_value = True

    assert helper.cleanup_inactive_subscriptions({'HK.KEEP'}) == 0
    assert not helper.subscription_manager.unsubscribe.called
    assert helper.cleanup_inactive_subscriptions({'HK.KEEP'}) == 1
    helper.subscription_manager.unsubscribe.assert_called_once_with(['HK.OLD'])


def test_low_activity_count_only_changes_once_per_day():
    db = MagicMock()
    db.execute_query.return_value = [(2, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))]
    marker = StockMarkerService(db)

    marker.mark_low_activity_stocks(['HK.TEST'], {'HK.TEST': 0.2})

    update_params = db.execute_update.call_args[0][1]
    assert update_params[0] == 2
    assert update_params[2] == 2


def test_active_recovery_clears_flag_without_repeated_same_day_decay():
    db = MagicMock()
    db.execute_query.return_value = [(datetime.now().strftime('%Y-%m-%d %H:%M:%S'),)]
    marker = StockMarkerService(db)

    marker.decrement_low_activity_count(['HK.TEST'])

    assert db.execute_update.call_args[0][1] == (0, 'HK.TEST')


def test_periodic_refilter_is_incremental_and_never_clears_daily_cache(monkeypatch):
    clear_records = MagicMock()
    pusher = AsyncQuotePusher.__new__(AsyncQuotePusher)
    pusher._last_refilter_time = 0
    pusher._activity_cache_policy = ActivityCachePolicy(
        opening_refilter_interval_seconds=1,
        regular_refilter_interval_seconds=1,
    )
    pusher.container = SimpleNamespace(
        db_manager=SimpleNamespace(
            stock_activity_queries=SimpleNamespace(
                clear_daily_activity_records=clear_records
            )
        )
    )
    trigger = MagicMock(return_value=True)
    monkeypatch.setattr(
        'simple_trade.services.core.async_quote_pusher.time.time', lambda: 100
    )
    monkeypatch.setattr(
        'simple_trade.services.core.async_quote_pusher.MarketTimeHelper.get_current_active_markets',
        lambda: ['HK'],
    )
    monkeypatch.setattr(
        'simple_trade.routers.data.activity_refilter.trigger_refilter_async', trigger
    )

    pusher._check_periodic_refilter()

    trigger.assert_called_once_with(pusher.container)
    clear_records.assert_not_called()
