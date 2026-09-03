#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from unittest.mock import MagicMock

from simple_trade.services.analysis.flow.capital_flow_signal_engine import (
    CapitalFlowSignalEngine,
)


def test_observe_mode_does_not_sync_old_rotation_engine(monkeypatch):
    monkeypatch.setenv("LEGACY_SIGNAL_MODE", "observe")
    engine = CapitalFlowSignalEngine()
    engine._ensure_table = MagicMock()
    engine._fetch_capital_flows = MagicMock(return_value={})
    engine._build_context = MagicMock(return_value=None)
    engine._sync_to_rotator = MagicMock()

    result = engine.check_signals(
        [{"code": "HK.03690", "last_price": 78.0, "prev_close": 76.0}],
        {},
    )

    assert result == []
    engine._sync_to_rotator.assert_not_called()
