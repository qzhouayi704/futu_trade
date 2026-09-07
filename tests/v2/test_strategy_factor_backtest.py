from pathlib import Path
from types import SimpleNamespace
import sys

import numpy as np
import pytest


ANALYSIS_DIR = Path(__file__).resolve().parents[2] / "scripts" / "analysis"
if str(ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(ANALYSIS_DIR))

import big_order_flow_eval as flow
import low_position_accumulation_grid as grid
import strategy_factor_backtest as subject
from simple_trade.v2.application.strategy.portfolio import CandidateSignalRules


def event(day: str, factor: float, eod: float, flow_key: str):
    return SimpleNamespace(
        day=day,
        code=f"HK.{day[-2:]}",
        flow_key=flow_key,
        signal_factor=factor,
        eod=eod,
        mfe60=max(eod, 0.02),
        mfe_eod=max(eod, 0.03),
        mae60=min(eod, -0.005),
    )


def test_split_days_reserves_last_ten_complete_days():
    days = [f"2026-08-{value:02d}" for value in range(1, 21)]

    train, test = subject.split_days(days, validation_days=10)

    assert train == set(days[:10])
    assert test == set(days[10:])


def test_bucket_boundaries_are_half_open():
    bins = (("low", None, 0.0), ("middle", 0.0, 1.0), ("high", 1.0, None))

    assert subject.bucket_label(-0.01, bins) == "low"
    assert subject.bucket_label(0.0, bins) == "middle"
    assert subject.bucket_label(1.0, bins) == "high"


def test_training_selection_does_not_read_holdout_outcomes():
    spec = grid.FlowSpec(15, 2.0, 1.0, 0.60, 2, 5)
    loose = subject.StrategyConfig("test", spec, (
        subject.FilterSpec("factor", "signal_factor", "ge", 0.0),
    ))
    strict = subject.StrategyConfig("test", spec, (
        subject.FilterSpec("factor", "signal_factor", "ge", 1.0),
    ))
    train_days = {f"2026-07-{value:02d}" for value in range(1, 17)}
    training = []
    for index, day in enumerate(sorted(train_days)):
        training.append(event(day, 0.0, 0.002, spec.key))
        training.append(event(day, 1.0, 0.015, spec.key))
    holdout = [event("2026-08-01", 0.0, 0.50, spec.key)]

    first, _ = subject.select_best_config(
        [loose, strict], {spec.key: training + holdout}, train_days
    )
    holdout[0].eod = -0.50
    second, _ = subject.select_best_config(
        [loose, strict], {spec.key: training + holdout}, train_days
    )

    assert first == strict
    assert second == strict


def test_activity_percentile_uses_only_amount_available_at_each_minute():
    index = flow.IDX["10:00"]
    records = {}
    derived = {}
    previous_close = {}
    for offset, code in enumerate(("HK.00001", "HK.00002", "HK.00003"), start=1):
        prices = np.full(flow.NG, 10.0 + offset)
        buy = np.zeros(flow.NG)
        buy[: index + 1] = float(offset)
        records[code] = {"tmb": buy, "tms": np.zeros(flow.NG)}
        derived[code] = {"p": prices}
        previous_close[(code, "2026-08-01")] = 10.0

    before = grid.build_universe_intraday_context(
        records, derived, "2026-08-01", previous_close, set(records)
    )
    records["HK.00001"]["tmb"][index + 10:] = 1_000_000_000.0
    after = grid.build_universe_intraday_context(
        records, derived, "2026-08-01", previous_close, set(records)
    )

    assert before["HK.00001"]["activity_percentile"][index] == after["HK.00001"]["activity_percentile"][index]
    assert before["HK.00003"]["activity_percentile"][index] == 1.0


def test_intraday_context_skips_stock_with_insufficient_derived_prices():
    records = {
        "HK.00001": {"tmb": np.zeros(flow.NG), "tms": np.zeros(flow.NG)},
    }

    result = grid.build_universe_intraday_context(
        records,
        {"HK.00001": None},
        "2026-08-01",
        {("HK.00001", "2026-08-01"): 10.0},
        {"HK.00001"},
    )

    assert result == {}


def test_filter_rejects_missing_factor_instead_of_treating_it_as_zero():
    item = subject.FilterSpec("relative", "relative_strength", "ge", 0.0)

    assert subject.matches_filter(SimpleNamespace(relative_strength=None), item) is False


def test_target_rotation_uses_one_point_five_percent_when_reached():
    spec = grid.FlowSpec(15, 2.0, 1.0, 0.60, 2, 5)
    reached = event("2026-08-01", 1.0, -0.02, spec.key)
    missed = event("2026-08-02", 1.0, 0.01, spec.key)
    reached.mfe_eod = 0.02
    missed.mfe_eod = 0.01

    result = subject.summarize([reached, missed])

    expected = ((0.015 - subject.ROUND_TRIP_COST) + (0.01 - subject.ROUND_TRIP_COST)) / 2
    assert result["target_1_5_mean"] == expected


def test_strategy_layers_read_the_live_flow_thresholds():
    layers = subject.strategy_layers()
    absorption = layers["S1"].config.flow_spec
    momentum = layers["S3"].config.flow_spec

    assert absorption == grid.FlowSpec(
        CandidateSignalRules.FLOW_WINDOW_SECONDS // 60,
        CandidateSignalRules.ABSORPTION_MIN_THRESHOLD_MULTIPLE,
        CandidateSignalRules.ABSORPTION_MIN_SCALE_MULTIPLE,
        CandidateSignalRules.ABSORPTION_MIN_BUY_RATIO,
        CandidateSignalRules.ABSORPTION_MIN_BUY_EVENTS,
        CandidateSignalRules.ABSORPTION_MIN_EVENT_SPAN_SECONDS // 60,
    )
    assert momentum == grid.FlowSpec(
        CandidateSignalRules.FLOW_WINDOW_SECONDS // 60,
        CandidateSignalRules.MOMENTUM_MIN_THRESHOLD_MULTIPLE,
        CandidateSignalRules.MOMENTUM_MIN_SCALE_MULTIPLE,
        CandidateSignalRules.MOMENTUM_MIN_BUY_RATIO,
        CandidateSignalRules.MOMENTUM_MIN_BUY_EVENTS,
        CandidateSignalRules.MOMENTUM_MIN_EVENT_SPAN_SECONDS // 60,
    )
    assert layers["S2"].replay_coverage == "保守代理"
    momentum_filters = {item.name: item for item in layers["S3"].config.filters}
    assert momentum_filters["day_change"].value == (
        CandidateSignalRules.MOMENTUM_MIN_DAILY_CHANGE / 100.0
    )
    assert not any(
        item.name == "cutoff" for item in layers["S3"].config.filters
    )


def test_rule_experiments_compare_legacy_momentum_and_cutoff_independently():
    baselines = subject.production_baselines()
    selected = {
        "capital_absorption": subject.strategy_configs()["capital_absorption"][0]
    }

    experiments = subject.rule_experiments(baselines, selected)
    legacy = experiments["S3_LEGACY_NO_DAY_CHANGE"][1]
    cutoff = experiments["S3_CUTOFF"][1]

    assert "day_change" not in {item.name for item in legacy.filters}
    assert {item.name for item in cutoff.filters} - {
        item.name for item in baselines["S3"].filters
    } == {"cutoff"}
    assert {item.name for item in cutoff.filters} >= {"day_change", "cutoff"}


def test_matched_controls_prefer_same_position_and_similar_activity():
    signal = SimpleNamespace(
        code="HK.SIGNAL", pos20=0.30, activity_percentile=0.80
    )
    candidates = [
        subject.ControlCandidate(
            code=f"HK.LOW{index}", day="2026-09-01", index=1,
            position_band="low", activity_percentile=0.70 + index * 0.02,
            eod=0.01, mfe_eod=0.02, mae60=-0.01,
        )
        for index in range(6)
    ]
    candidates.append(subject.ControlCandidate(
        code="HK.HIGH", day="2026-09-01", index=1,
        position_band="high", activity_percentile=0.80,
        eod=0.50, mfe_eod=0.50, mae60=-0.01,
    ))

    selected, mode = subject.select_matched_controls(signal, candidates)

    assert mode == "同位置且活跃度相近"
    assert len(selected) == 6
    assert all(item.position_band == "low" for item in selected)


def test_matched_control_summary_reports_excess_after_equal_costs():
    signal = SimpleNamespace(
        code="HK.SIGNAL", day="2026-09-01", minute="10:00", index=1,
        pos20=0.30, activity_percentile=0.80,
        eod=0.03, mfe_eod=0.04, mae60=-0.01,
    )
    controls = [
        subject.ControlCandidate(
            code=f"HK.{index:05d}", day=signal.day, index=signal.index,
            position_band="low", activity_percentile=0.75,
            eod=0.01, mfe_eod=0.02 if index < 3 else 0.01,
            mae60=-0.02,
        )
        for index in range(6)
    ]

    rows = subject.matched_control_rows(
        [signal], {(signal.day, signal.index): controls}
    )
    summary = subject.matched_control_summary(rows)

    assert summary is not None
    assert summary["signal_net_eod_mean"] == 0.03 - subject.ROUND_TRIP_COST
    assert summary["control_net_eod_mean"] == 0.01 - subject.ROUND_TRIP_COST
    assert summary["excess_eod_mean"] == 0.02
    assert summary["outperform_ratio"] == 1.0
    assert summary["positive_day_ratio"] == 1.0
    assert summary["leave_best_day_out_excess_mean"] is None
    assert summary["signal_reached_1_5"] == 1.0
    assert summary["control_reached_1_5"] == 0.5


def test_matched_control_summary_reports_outlier_and_day_robustness():
    rows = [
        {
            "code": f"HK.{index:05d}",
            "day": day,
            "control_count": 6,
            "match_mode": "同位置",
            "signal_net_eod": signal,
            "control_net_eod": 0.0,
            "signal_reached_1_5": signal > 0.015,
            "control_reached_1_5": 0.25,
        }
        for index, (day, signal) in enumerate((
            ("2026-09-01", 0.01),
            ("2026-09-01", 0.02),
            ("2026-09-02", -0.01),
            ("2026-09-03", 0.03),
            ("2026-09-03", 0.20),
        ))
    ]

    summary = subject.matched_control_summary(rows)

    assert summary is not None
    assert summary["stocks"] == 5
    assert summary["positive_day_ratio"] == 2 / 3
    assert summary["excess_eod_trimmed_mean"] == 0.02
    assert summary["best_day"] == "2026-09-03"
    assert summary["leave_best_day_out_excess_mean"] == pytest.approx(0.02 / 3)


def test_matched_control_windows_keep_empty_five_day_periods():
    days = [f"2026-09-{value:02d}" for value in range(1, 11)]
    rows = [{
        "code": "HK.00001",
        "day": days[1],
        "control_count": 6,
        "match_mode": "同位置",
        "signal_net_eod": 0.02,
        "control_net_eod": 0.01,
        "signal_reached_1_5": True,
        "control_reached_1_5": 0.5,
    }]

    windows = subject.matched_control_windows(rows, days)

    assert len(windows) == 2
    assert windows[0]["metrics"]["n"] == 1
    assert windows[1]["metrics"] is None
