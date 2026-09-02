from pathlib import Path
from types import SimpleNamespace
import sys

import numpy as np


ANALYSIS_DIR = Path(__file__).resolve().parents[2] / "scripts" / "analysis"
if str(ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(ANALYSIS_DIR))

import big_order_flow_eval as flow
import low_position_accumulation_grid as grid
import strategy_factor_backtest as subject


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
