#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
from types import SimpleNamespace

from simple_trade.config.legacy_signal_policy import (
    ALL_LEGACY_FLOW_RULE_IDS,
    LegacySignalMode,
    legacy_flow_advisory_rule_ids,
    resolve_legacy_signal_policy,
)


def test_v2_alert_defaults_legacy_to_observe():
    from simple_trade.services.analysis.flow.flow_signal_rules import ALL_RULES

    policy = resolve_legacy_signal_policy({"V2_ENABLED": "1", "V2_MODE": "alert"})

    assert policy.mode is LegacySignalMode.OBSERVE
    assert policy.detection_enabled is True
    assert policy.action_enabled is False
    assert legacy_flow_advisory_rule_ids(
        {"V2_ENABLED": "1", "V2_MODE": "alert"}
    ) == ALL_LEGACY_FLOW_RULE_IDS
    assert {rule.rule_id for rule in ALL_RULES} == set(ALL_LEGACY_FLOW_RULE_IDS)


def test_explicit_active_is_a_rollback_override():
    env = {
        "V2_ENABLED": "1",
        "V2_MODE": "alert",
        "LEGACY_SIGNAL_MODE": "active",
        "FLOW_ADVISORY_RULES": "R1,R13",
    }

    policy = resolve_legacy_signal_policy(env)

    assert policy.mode is LegacySignalMode.ACTIVE
    assert policy.action_enabled is True
    assert legacy_flow_advisory_rule_ids(env) == frozenset({"R1", "R13"})


def test_invalid_mode_fails_closed_to_observe():
    policy = resolve_legacy_signal_policy({"LEGACY_SIGNAL_MODE": "typo"})

    assert policy.mode is LegacySignalMode.OBSERVE
    assert policy.action_enabled is False


def test_off_disables_detection_and_actions():
    policy = resolve_legacy_signal_policy({"LEGACY_SIGNAL_MODE": "off"})

    assert policy.mode is LegacySignalMode.OFF
    assert policy.detection_enabled is False
    assert policy.action_enabled is False


def test_legacy_recommendation_endpoint_is_empty_in_observe_mode(monkeypatch):
    from simple_trade.routers.trading.pre_trade_check import get_recommendations

    monkeypatch.setenv("LEGACY_SIGNAL_MODE", "observe")
    container = SimpleNamespace(db_manager=object())

    response = asyncio.run(get_recommendations(container))

    assert response.success is True
    assert response.data["buy_recommendations"] == []
    assert response.data["sell_recommendations"] == []
    assert response.data["legacy_mode"] == "observe"


def test_flow_rule_api_removes_action_wording_in_observe_mode():
    from simple_trade.routers.data.flow_signal import _rules_for_runtime

    rules = _rules_for_runtime({"mode": "observe", "action_enabled": False})

    assert rules
    assert all(rule["action_enabled"] is False for rule in rules)
    assert all("不参与当前系统买卖决策" in rule["suggestion"] for rule in rules)
    assert all(rule["legacy_suggestion"] for rule in rules)


def test_flow_history_keeps_sample_but_removes_action_wording(monkeypatch):
    from simple_trade.routers.data.flow_signal import get_flow_signal_history

    class FakeDb:
        def execute_query(self, sql, _params):
            if "COUNT(*)" in sql:
                return [(1,)]
            return [(
                7, "R13", "日内波段高抛", "HK.03690", "美团",
                "SELL", 78.0, "旧规则触发", 0.8, "high", "立即减仓",
                "2026-09-02 13:00:00",
            )]

    monkeypatch.setenv("LEGACY_SIGNAL_MODE", "observe")
    response = asyncio.run(get_flow_signal_history(
        limit=50,
        signal_type=None,
        stock_code=None,
        container=SimpleNamespace(db_manager=FakeDb()),
    ))

    signal = response.data["signals"][0]
    assert signal["advisory"] is True
    assert signal["action_suggestion"] == "历史样本，仅供复盘，不参与当前买卖决策"
    assert signal["legacy_action_suggestion"] == "立即减仓"


def test_legacy_position_advisor_stops_generating_actions(monkeypatch):
    from simple_trade.services.analysis.position_advisor import PositionAdvisor

    monkeypatch.setenv("LEGACY_SIGNAL_MODE", "observe")
    advisor = PositionAdvisor(db_manager=object())
    positions = [{
        "stock_code": "HK.03690",
        "stock_name": "美团",
        "qty": 100,
        "nominal_price": 78.0,
    }]

    result = asyncio.run(advisor.generate_all_advice(positions))

    assert result == []
