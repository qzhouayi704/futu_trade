from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from simple_trade.services.core.async_quote_pusher import AsyncQuotePusher


def _make_pusher():
    db_manager = SimpleNamespace(execute_query=MagicMock(return_value=[]))
    score = SimpleNamespace(
        passed=True,
        total_score=88,
        mode="trend",
        details=[],
        trade_params=None,
    )
    scorer = SimpleNamespace(
        score_all_strategies=MagicMock(return_value={"best": score})
    )
    container = SimpleNamespace(
        config=None,
        db_manager=db_manager,
        stock_scorer=scorer,
        ticker_service=None,
    )
    socket_manager = SimpleNamespace(emit_to_all=AsyncMock())
    pusher = AsyncQuotePusher(
        container=container,
        socket_manager=socket_manager,
        state_manager=MagicMock(),
        quote_pipeline=MagicMock(),
    )
    return pusher, socket_manager


@pytest.mark.asyncio
async def test_scored_anomaly_broadcasts_and_forwards_trade_signal():
    pusher, socket_manager = _make_pusher()
    pusher._try_create_anomaly_trades = MagicMock()
    anomaly = SimpleNamespace(
        code="HK.00700",
        name="腾讯控股",
        price=600.0,
        change_rate=5.0,
        volume_ratio=2.0,
        anomaly_type="capital_inflow",
        has_shrinkage=False,
        detected_at="2026-09-01T10:00:00+08:00",
        cap_tier="A",
        capital_score=90,
        signal_change=1,
    )

    await pusher._score_and_alert_anomalies([anomaly])

    socket_manager.emit_to_all.assert_awaited_once()
    event, payload = socket_manager.emit_to_all.await_args.args
    assert event == "anomaly_scored"
    assert payload["alerts"][0]["code"] == "HK.00700"
    pusher._try_create_anomaly_trades.assert_called_once_with(payload["alerts"])


@pytest.mark.asyncio
async def test_pool_anomaly_uses_socket_manager_broadcast_contract():
    pusher, socket_manager = _make_pusher()
    anomaly = SimpleNamespace(
        code="HK.00700",
        name="腾讯控股",
        change_rate=5.0,
        volume_ratio=2.0,
        turnover_rate=1.0,
        price=600.0,
        anomaly_type="capital_inflow",
        has_shrinkage=False,
        detected_at="2026-09-01T10:00:00+08:00",
        detail="test",
    )

    await pusher._broadcast_anomalies([anomaly])

    socket_manager.emit_to_all.assert_awaited_once()
    event, payload = socket_manager.emit_to_all.await_args.args
    assert event == "pool_anomaly"
    assert payload["anomalies"][0]["code"] == "HK.00700"
