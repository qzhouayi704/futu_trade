#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for mega_buy broker consistency filtering and signal strength downgrading.
"""

import sys
import os
import pytest
from datetime import datetime

# Adjust path to import project modules
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)

from simple_trade.services.trading.decision.engine import UnifiedTradeDecisionEngine
from simple_trade.services.trading.decision.models import TradeSignalEvent, TradeDecision
from simple_trade.services.sniper.intraday_sniper import SniperSignal


class DummyContainer:
    def __init__(self):
        self.futu_trade_service = None
        self.db_manager = None
        self.trade_frequency_guard = None
        self.trading_phase_manager = None
        self.stock_scorer = None
        self.quote_cache = None


class DummyFutuTradeService:
    def __init__(self, positions):
        self.positions = positions

    def is_trade_ready(self):
        return True

    def get_positions(self):
        return {
            'success': True,
            'positions': self.positions
        }


@pytest.mark.asyncio
async def test_mega_buy_held_stock_no_downgrade():
    """
    Test that a mega_buy signal for an already held stock is NOT downgraded
    even if the broker consistency check has a 'medium' severity (retail-dominated).
    """
    container = DummyContainer()
    # Mock position: we hold '00700'
    container.futu_trade_service = DummyFutuTradeService(positions=[{'code': '00700', 'qty': 100}])
    
    engine = UnifiedTradeDecisionEngine(container, simulate=True)
    
    # Mock SniperSignal
    signal = SniperSignal(
        time="10:00",
        stock_code="00700",
        stock_name="Tencent",
        signal_type="mega_buy",
        is_red=False,
        price=350.0,
        detail="单分钟净买入+100万",
        action="✅ 关注买入机会",
        severity="medium" # Retail-dominated
    )
    
    # Intercept on_signal to check what event gets generated
    intercepted_events = []
    async def mock_on_signal(event):
        intercepted_events.append(event)
        
    engine.on_signal = mock_on_signal
    
    await engine.on_sniper_signal(signal)
    
    assert len(intercepted_events) == 1
    event = intercepted_events[0]
    assert event.stock_code == "00700"
    # Because it is a held stock, its strength must remain 90.0 (no downgrade)
    assert event.strength == 90.0
    assert "[席位降级]" not in event.reason


@pytest.mark.asyncio
async def test_mega_buy_non_held_high_severity_no_downgrade():
    """
    Test that a mega_buy signal for a non-held stock is NOT downgraded
    if the broker consistency check confirms institutional buying (severity is 'high').
    """
    container = DummyContainer()
    # Mock position: empty
    container.futu_trade_service = DummyFutuTradeService(positions=[])
    
    engine = UnifiedTradeDecisionEngine(container, simulate=True)
    
    signal = SniperSignal(
        time="10:00",
        stock_code="00001",
        stock_name="CK Hutchison",
        signal_type="mega_buy",
        is_red=False,
        price=50.0,
        detail="单分钟净买入+100万 (🔥席位确认: 机构吸筹中)",
        action="✅ 关注买入机会",
        severity="high" # Institutional confirmed
    )
    
    intercepted_events = []
    async def mock_on_signal(event):
        intercepted_events.append(event)
        
    engine.on_signal = mock_on_signal
    
    await engine.on_sniper_signal(signal)
    
    assert len(intercepted_events) == 1
    event = intercepted_events[0]
    assert event.stock_code == "00001"
    # Institutional confirmed signals keep their strength
    assert event.strength == 90.0
    assert "[席位降级]" not in event.reason


@pytest.mark.asyncio
async def test_mega_buy_non_held_medium_severity_downgrade():
    """
    Test that a mega_buy signal for a non-held stock is downgraded to 50.0
    if the broker consistency check has 'medium' severity (retail-dominated or trap).
    """
    container = DummyContainer()
    container.futu_trade_service = DummyFutuTradeService(positions=[])
    
    engine = UnifiedTradeDecisionEngine(container, simulate=True)
    
    signal = SniperSignal(
        time="10:00",
        stock_code="00001",
        stock_name="CK Hutchison",
        signal_type="mega_buy",
        is_red=False,
        price=50.0,
        detail="单分钟净买入+100万 (⚠️席位确认: 散户主导)",
        action="✅ 关注买入机会",
        severity="medium" # Retail-dominated
    )
    
    intercepted_events = []
    async def mock_on_signal(event):
        intercepted_events.append(event)
        
    engine.on_signal = mock_on_signal
    
    await engine.on_sniper_signal(signal)
    
    assert len(intercepted_events) == 1
    event = intercepted_events[0]
    assert event.stock_code == "00001"
    # Non-held and retail-dominated: must be downgraded to 50.0
    assert event.strength == 50.0
    assert "[席位降级: 非持仓股且无机构席位确认]" in event.reason
