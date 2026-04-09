"""
ScalpingEngine 单元测试

覆盖：
- on_tick 分发至各计算器
- on_order_book 分发至 SpoofingFilter
- 断线重连逻辑（3 次失败后推送告警）
- start/stop 生命周期
- 日内高点跟踪
- POC 定期计算
- 可选组件为 None 时不报错
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from simple_trade.services.scalping.engine import (
    ScalpingEngine,
    _MAX_RECONNECT_ATTEMPTS,
    _POC_CALC_INTERVAL,
)
from simple_trade.services.scalping.models import (
    OrderBookData,
    OrderBookLevel,
    TickData,
    TickDirection,
)


# ==================== Fixtures ====================


def _make_tick(
    stock_code: str = "HK.00700",
    price: float = 350.0,
    volume: int = 200,
    timestamp: float = 1_700_000_000_000.0,
) -> TickData:
    return TickData(
        stock_code=stock_code,
        price=price,
        volume=volume,
        direction=TickDirection.BUY,
        timestamp=timestamp,
        ask_price=350.2,
        bid_price=349.8,
    )


def _make_order_book(
    stock_code: str = "HK.00700",
    timestamp: float = 1_700_000_000_000.0,
) -> OrderBookData:
    ask = [
        OrderBookLevel(price=350.1 + i * 0.1, volume=100, order_count=5)
        for i in range(10)
    ]
    bid = [
        OrderBookLevel(price=350.0 - i * 0.1, volume=100, order_count=5)
        for i in range(10)
    ]
    return OrderBookData(
        stock_code=stock_code,
        ask_levels=ask,
        bid_levels=bid,
        timestamp=timestamp,
    )


def _build_engine(**overrides) -> ScalpingEngine:
    """构建带 mock 依赖的 ScalpingEngine"""
    defaults = dict(
        subscription_helper=MagicMock(),
        realtime_query=MagicMock(),
        socket_manager=AsyncMock(),
        delta_calculator=MagicMock(),
        tape_velocity=MagicMock(),
        spoofing_filter=MagicMock(),
        poc_calculator=MagicMock(),
        signal_engine=MagicMock(),
    )
    # 让 async 方法返回协程
    defaults["tape_velocity"].check_ignition = AsyncMock(return_value=None)
    defaults["spoofing_filter"].on_order_book = AsyncMock()
    defaults["signal_engine"].evaluate_breakout = AsyncMock(return_value=None)
    defaults["signal_engine"].evaluate_support_bounce = AsyncMock(
        return_value=None
    )
    defaults["poc_calculator"].calculate_poc = AsyncMock(return_value=None)
    defaults.update(overrides)
    return ScalpingEngine(**defaults)


# ==================== start / stop ====================


@pytest.mark.asyncio
async def test_start_subscribes_and_tracks():
    engine = _build_engine()
    await engine.start(["HK.00700", "HK.09988"])
    assert engine.active_stocks == {"HK.00700", "HK.09988"}
    engine._subscription_helper.set_priority_stocks.assert_called_once()
    engine._subscription_helper.subscribe_target_stocks.assert_called_once()


@pytest.mark.asyncio
async def test_start_skips_already_active():
    engine = _build_engine()
    await engine.start(["HK.00700"])
    engine._subscription_helper.reset_mock()
    await engine.start(["HK.00700"])
    engine._subscription_helper.set_priority_stocks.assert_not_called()


@pytest.mark.asyncio
async def test_stop_clears_state():
    engine = _build_engine()
    await engine.start(["HK.00700"])
    await engine.stop(["HK.00700"])
    assert "HK.00700" not in engine.active_stocks
    engine._delta_calculator.reset.assert_called_with("HK.00700")


@pytest.mark.asyncio
async def test_stop_all():
    engine = _build_engine()
    await engine.start(["HK.00700", "HK.09988"])
    await engine.stop()
    assert len(engine.active_stocks) == 0
    engine._subscription_helper.unsubscribe_all.assert_called_once()


# ==================== on_tick 分发 ====================


@pytest.mark.asyncio
async def test_on_tick_dispatches_to_core_calculators():
    engine = _build_engine()
    await engine.start(["HK.00700"])
    tick = _make_tick()

    await engine.on_tick("HK.00700", tick)

    engine._delta_calculator.on_tick.assert_called_once_with("HK.00700", tick)
    engine._tape_velocity.on_tick.assert_called_once_with("HK.00700", tick)
    # POC 现在接收 direction 参数（来自 DeltaCalculator 返回值）
    engine._poc_calculator.on_tick.assert_called_once()
    poc_call_args = engine._poc_calculator.on_tick.call_args
    assert poc_call_args[0][0] == "HK.00700"
    assert poc_call_args[0][1] == tick
    engine._signal_engine.record_price.assert_called_once()


@pytest.mark.asyncio
async def test_on_tick_ignores_inactive_stock():
    engine = _build_engine()
    tick = _make_tick(stock_code="HK.99999")
    await engine.on_tick("HK.99999", tick)
    engine._delta_calculator.on_tick.assert_not_called()


@pytest.mark.asyncio
async def test_on_tick_with_credibility_filter_blocks():
    """TickCredibilityFilter 返回 should_dispatch=False 时不分发"""
    mock_filter = MagicMock()
    mock_filter.filter_tick.return_value = (False, True)  # OUTLIER
    engine = _build_engine(tick_credibility_filter=mock_filter)
    await engine.start(["HK.00700"])

    await engine.on_tick("HK.00700", _make_tick())

    mock_filter.filter_tick.assert_called_once()
    engine._delta_calculator.on_tick.assert_not_called()


@pytest.mark.asyncio
async def test_on_tick_with_credibility_filter_passes():
    """TickCredibilityFilter 返回 should_dispatch=True 时正常分发"""
    mock_filter = MagicMock()
    mock_filter.filter_tick.return_value = (True, False)
    engine = _build_engine(tick_credibility_filter=mock_filter)
    await engine.start(["HK.00700"])

    await engine.on_tick("HK.00700", _make_tick())

    engine._delta_calculator.on_tick.assert_called_once()


@pytest.mark.asyncio
async def test_on_tick_optional_components_none():
    """可选组件为 None 时不报错"""
    engine = _build_engine()
    await engine.start(["HK.00700"])
    # 默认所有可选组件为 None，不应抛异常
    await engine.on_tick("HK.00700", _make_tick())


@pytest.mark.asyncio
async def test_on_tick_dispatches_to_optional_components():
    """可选组件存在时正常分发"""
    mock_div = MagicMock()
    mock_brk = MagicMock()
    mock_vwap = MagicMock()
    mock_vwap.on_tick_async = AsyncMock()
    mock_sl = MagicMock()
    engine = _build_engine(
        divergence_detector=mock_div,
        breakout_monitor=mock_brk,
        vwap_guard=mock_vwap,
        stop_loss_monitor=mock_sl,
    )
    await engine.start(["HK.00700"])
    tick = _make_tick()

    await engine.on_tick("HK.00700", tick)

    mock_div.on_tick.assert_called_once_with("HK.00700", tick)
    mock_brk.on_tick.assert_called_once_with("HK.00700", tick)
    mock_vwap.on_tick_async.assert_called_once_with("HK.00700", tick)
    mock_sl.on_tick.assert_called_once_with("HK.00700", tick)


# ==================== on_order_book ====================


@pytest.mark.asyncio
async def test_on_order_book_dispatches_to_spoofing_filter():
    engine = _build_engine()
    await engine.start(["HK.00700"])
    ob = _make_order_book()

    await engine.on_order_book("HK.00700", ob)

    engine._spoofing_filter.on_order_book.assert_awaited_once_with(
        "HK.00700", ob
    )


@pytest.mark.asyncio
async def test_on_order_book_ignores_inactive():
    engine = _build_engine()
    ob = _make_order_book(stock_code="HK.99999")
    await engine.on_order_book("HK.99999", ob)
    engine._spoofing_filter.on_order_book.assert_not_awaited()


# ==================== 日内高点跟踪 ====================


@pytest.mark.asyncio
async def test_day_high_tracking():
    engine = _build_engine()
    await engine.start(["HK.00700"])

    await engine.on_tick("HK.00700", _make_tick(price=350.0))
    assert engine.day_highs["HK.00700"] == 350.0

    await engine.on_tick("HK.00700", _make_tick(price=352.0))
    assert engine.day_highs["HK.00700"] == 352.0

    # 价格回落不应更新高点
    await engine.on_tick("HK.00700", _make_tick(price=349.0))
    assert engine.day_highs["HK.00700"] == 352.0


# ==================== POC 定期计算 ====================


@pytest.mark.asyncio
async def test_poc_calculated_periodically():
    engine = _build_engine()
    await engine.start(["HK.00700"])

    # 第一笔 Tick 触发 POC 计算（last=0, now > 5s）
    t0 = 1_700_000_000_000.0
    await engine.on_tick("HK.00700", _make_tick(timestamp=t0))
    engine._poc_calculator.calculate_poc.assert_awaited_once()

    engine._poc_calculator.calculate_poc.reset_mock()

    # 2 秒后不应再次计算
    await engine.on_tick(
        "HK.00700", _make_tick(timestamp=t0 + 2_000)
    )
    engine._poc_calculator.calculate_poc.assert_not_awaited()

    # 6 秒后应再次计算
    await engine.on_tick(
        "HK.00700", _make_tick(timestamp=t0 + 6_000)
    )
    engine._poc_calculator.calculate_poc.assert_awaited_once()


# ==================== 信号评估 ====================


@pytest.mark.asyncio
async def test_signal_evaluation_called():
    engine = _build_engine()
    await engine.start(["HK.00700"])

    await engine.on_tick("HK.00700", _make_tick(price=350.0))

    engine._signal_engine.evaluate_breakout.assert_awaited_once()
    engine._signal_engine.evaluate_support_bounce.assert_awaited_once()


# ==================== 断线重连 ====================


@pytest.mark.asyncio
async def test_reconnect_success_on_first_retry():
    engine = _build_engine()
    await engine.start(["HK.00700"])

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await engine._reconnect("HK.00700")

    # 重连成功，计数归零
    assert engine._reconnect_attempts.get("HK.00700") == 0


@pytest.mark.asyncio
async def test_reconnect_fails_after_max_attempts():
    engine = _build_engine()
    await engine.start(["HK.00700"])
    engine._subscription_helper.subscribe_target_stocks.side_effect = (
        Exception("连接失败")
    )

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await engine._reconnect("HK.00700")

    assert (
        engine._reconnect_attempts["HK.00700"] == _MAX_RECONNECT_ATTEMPTS
    )
    engine._socket_manager.emit_to_all.assert_awaited()


# ==================== 计算器异常不影响其他 ====================


@pytest.mark.asyncio
async def test_calculator_exception_does_not_block():
    """某个计算器抛异常不影响其他计算器"""
    engine = _build_engine()
    engine._delta_calculator.on_tick.side_effect = RuntimeError("boom")
    await engine.start(["HK.00700"])

    await engine.on_tick("HK.00700", _make_tick())

    # DeltaCalculator 异常，但 TapeVelocity 仍被调用
    engine._tape_velocity.on_tick.assert_called_once()
    engine._poc_calculator.on_tick.assert_called_once()


# ==================== stop 重置可选组件 ====================


@pytest.mark.asyncio
async def test_stop_resets_optional_components():
    mock_div = MagicMock()
    mock_vwap = MagicMock()
    mock_sl = MagicMock()
    mock_tcf = MagicMock()
    engine = _build_engine(
        divergence_detector=mock_div,
        vwap_guard=mock_vwap,
        stop_loss_monitor=mock_sl,
        tick_credibility_filter=mock_tcf,
    )
    await engine.start(["HK.00700"])
    await engine.stop(["HK.00700"])

    mock_div.reset.assert_called_with("HK.00700")
    mock_vwap.reset.assert_called_with("HK.00700")
    mock_sl.reset.assert_called_with("HK.00700")
    mock_tcf.reset.assert_called_with("HK.00700")
