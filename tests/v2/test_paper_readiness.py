from contextlib import closing
from dataclasses import asdict, replace
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from simple_trade.v2.application.paper_session.readiness import evaluate_readiness
from simple_trade.v2.domain.capture import BookCaptureConfig
from simple_trade.v2.domain.paper_readiness import CapacityAssumptions, ReviewAcknowledgements, StorageFacts
from simple_trade.v2.domain.planning.codec import encode
from simple_trade.v2.infrastructure.book_capture.archive import SqliteBookArchive
from simple_trade.v2.infrastructure.paper.readiness_probe import paths_alias, probe_storage
from simple_trade.v2.infrastructure.paper.session_store import SqlitePaperSessionStore
from tests.v2.test_paper_session import NOW, config


GIB = 1024 ** 3
REVIEWS = ReviewAcknowledgements(True, True, True, True)
ASSUMPTIONS = CapacityAssumptions(128, 256, "small-test-fixture-not-measured")


def inputs(tmp_path):
    paper = config(tmp_path)
    capture = BookCaptureConfig(path=tmp_path / "capture.sqlite")
    facts = (StorageFacts(str(capture.path), False, True, "disk", 10 * GIB, 0),
             StorageFacts(str(paper.path), False, True, "disk", 10 * GIB, 0))
    return paper, capture, dict(when=NOW, expected_strategy_version="test-v1", reviews=REVIEWS,
                               assumptions=ASSUMPTIONS, storage=facts, isolated_paths=True,
                               system_free_bytes=10 * GIB, protected_stock_count=0)


def codes(report):
    return {item.code for item in report.issues if item.level == "BLOCKER"}


def test_explicit_paper_ready_never_grants_execution(tmp_path):
    paper, capture, values = inputs(tmp_path)
    report = evaluate_readiness(paper, capture, **values)
    assert report.ready_for_paper_trial
    assert report.execution_allowed is False
    assert not paper.path.exists() and not capture.path.exists()
    assert report.projection.capture_records > report.projection.paper_commands
    assert "LIVE_FEED_NOT_VERIFIED" in {item.code for item in report.issues}


@pytest.mark.parametrize("changes,expected", [
    ({"reviews": ReviewAcknowledgements()}, "REVIEW_REQUIRED_COSTS"),
    ({"expected_strategy_version": "other"}, "STRATEGY_VERSION_MISMATCH"),
    ({"system_free_bytes": int(1.4 * GIB)}, "SYSTEM_DISK_RESERVE_LOW"),
    ({"system_free_bytes": None}, "SYSTEM_DISK_RESERVE_LOW"),
    ({"when": NOW + timedelta(days=1)}, "SCHEDULE_EXPIRED"),
    ({"isolated_paths": False}, "DATABASE_PATHS_NOT_ISOLATED"),
    ({"assumptions": None}, "CAPACITY_ASSUMPTIONS_MISSING"),
    ({"protected_stock_count": 8}, "CAPTURE_TARGET_BUDGET_INSUFFICIENT"),
])
def test_blockers_are_explicit(tmp_path, changes, expected):
    paper, capture, values = inputs(tmp_path)
    report = evaluate_readiness(paper, capture, **(values | changes))
    assert not report.ready_for_paper_trial and expected in codes(report)


def test_whole_day_eight_stock_input_exceeds_default_command_budget(tmp_path):
    paper, capture, values = inputs(tmp_path)
    paper = replace(paper, experiment=replace(paper.experiment, stock_codes=tuple(f"HK.{i:05d}" for i in range(8))))
    report = evaluate_readiness(paper, capture, **(values | {"when": NOW.replace(hour=9)}))
    assert report.projection.remaining_schedule_seconds == 19800
    assert report.projection.capture_records >= 316800
    assert "RECORD_BUDGET_INSUFFICIENT" in codes(report)


def test_same_filesystem_space_is_not_spent_twice(tmp_path):
    paper, capture, values = inputs(tmp_path)
    facts = tuple(replace(item, free_bytes=800 * 1024 ** 2) for item in values["storage"])
    report = evaluate_readiness(paper, capture, **(values | {"storage": facts}))
    assert "SHARED_DISK_BUDGET_INSUFFICIENT" in codes(report)
    facts = (facts[0], replace(facts[1], device="second-disk"))
    report = evaluate_readiness(paper, capture, **(values | {"storage": facts}))
    assert "SHARED_DISK_BUDGET_INSUFFICIENT" not in codes(report)


def test_existing_size_records_and_wrong_probe_path_block(tmp_path):
    paper, capture, values = inputs(tmp_path)
    facts = (replace(values["storage"][0], file_bytes=capture.max_bytes, records=capture.max_records),
             replace(values["storage"][1], path=str(tmp_path / "unrelated.db")))
    report = evaluate_readiness(paper, capture, **(values | {"storage": facts}))
    assert {"FILE_BUDGET_INSUFFICIENT", "RECORD_BUDGET_INSUFFICIENT", "STORAGE_FACTS_MISMATCH"} <= codes(report)


def test_close_cutoff_cannot_leave_a_false_ready_entry_window(tmp_path):
    paper, capture, values = inputs(tmp_path)
    report = evaluate_readiness(paper, capture, **(values | {"when": NOW.replace(hour=15, minute=58)}))
    assert "NO_VALID_ENTRY_WINDOW" in codes(report)


def test_probe_does_not_create_or_modify_databases(tmp_path):
    target = tmp_path / "missing.sqlite"
    facts = probe_storage(target, role="capture")
    assert not facts.exists and not target.exists() and facts.parent_ready
    facts = probe_storage(tmp_path / "missing-folder" / "missing.sqlite", role="capture")
    assert facts.blocked_reason == "PARENT_DIRECTORY_MISSING"
    assert not (tmp_path / "missing-folder").exists()
    with closing(sqlite3.connect(target)) as conn, conn:
        conn.execute("CREATE TABLE trading (value TEXT)")
    before = target.read_bytes()
    assert probe_storage(target, role="capture").blocked_reason == "DATABASE_IDENTITY_MISMATCH"
    assert target.read_bytes() == before


def test_capture_and_paper_active_runs_are_not_blessed_for_reuse(tmp_path):
    paper, capture, _ = inputs(tmp_path)
    SqliteBookArchive(capture).start("active", NOW)
    assert probe_storage(capture.path, role="capture").blocked_reason == "CAPTURE_ACTIVE_OR_UNCLEAN"
    store = SqlitePaperSessionStore(paper)
    frozen = encode({**asdict(paper), "path": str(paper.path)})
    store.begin_run("active", frozen)
    assert probe_storage(paper.path, role="paper", paper=paper).blocked_reason == "PAPER_ACTIVE_OR_UNCLEAN"
    store.finish_run("active", None)
    assert probe_storage(paper.path, role="paper", paper=paper).blocked_reason is None
    changed = replace(paper, experiment=replace(paper.experiment, entry_ttl_seconds=90))
    assert probe_storage(paper.path, role="paper", paper=changed).blocked_reason == "PAPER_CONFIGURATION_CHANGED"


def test_hardlink_is_not_an_isolated_path(tmp_path):
    original, linked = tmp_path / "original.db", tmp_path / "linked.db"
    original.write_bytes(b"original")
    linked.hardlink_to(original)
    assert paths_alias(original, linked)
    assert paths_alias(original, tmp_path / "." / "original.db")
    assert not paths_alias(original, tmp_path / "other.db")


def test_probe_rejects_oversized_state_before_decoding(tmp_path):
    paper, _, _ = inputs(tmp_path)
    SqlitePaperSessionStore(paper)
    with closing(sqlite3.connect(paper.path)) as conn, conn:
        conn.execute("UPDATE paper_account SET state_json=?", ("x" * (4 * 1024 ** 2 + 1),))
    assert probe_storage(paper.path, role="paper", paper=paper).blocked_reason == "PAPER_ACCOUNT_STATE_TOO_LARGE_OR_INVALID"


def test_capture_config_file_is_explicit_and_conflicts_are_rejected(tmp_path, monkeypatch):
    cfg = BookCaptureConfig(path=tmp_path / "capture.sqlite", max_stocks=3, sample_interval_seconds=1)
    path = tmp_path / "capture.json"
    path.write_text(encode({**asdict(cfg), "path": str(cfg.path), "schema_version": 1}), encoding="utf-8")
    monkeypatch.setenv("V2_BOOK_CAPTURE_CONFIG", str(path))
    monkeypatch.delenv("V2_BOOK_CAPTURE_PATH", raising=False)
    assert BookCaptureConfig.from_env() == cfg
    monkeypatch.setenv("V2_BOOK_CAPTURE_PATH", str(tmp_path / "other.sqlite"))
    with pytest.raises(ValueError, match="conflicts"):
        BookCaptureConfig.from_env()


def test_cli_reports_missing_reviews_without_creating_output_databases(tmp_path):
    paper, capture, _ = inputs(tmp_path)
    source = tmp_path / "paper.json"
    source.write_text(encode({**asdict(paper), "path": str(paper.path), "schema_version": 1}), encoding="utf-8")
    main = tmp_path / "main.db"
    main.write_bytes(b"do not read or modify")
    script = Path(__file__).resolve().parents[2] / "scripts" / "check_paper_readiness.py"
    result = subprocess.run([sys.executable, str(script), "--config", str(source), "--capture-path", str(capture.path),
                             "--trading-db", str(main), "--strategy-version", "test-v1", "--protected-stocks", "0",
                             "--at", NOW.isoformat()], capture_output=True, text=True, timeout=15)
    payload = json.loads(result.stdout)
    assert result.returncode == 2 and payload["ready_for_paper_trial"] is False
    assert "REVIEW_REQUIRED_PARAMETERS" in {item["code"] for item in payload["issues"]}
    assert main.read_bytes() == b"do not read or modify"
    assert not capture.path.exists() and not paper.path.exists()


@pytest.mark.parametrize("mode", ["RESEARCH_ATR", "PRODUCTION_RULES"])
def test_benchmark_is_bounded_and_cleans_only_its_own_temporary_directory(tmp_path, mode):
    script = Path(__file__).resolve().parents[2] / "scripts" / "paper_capacity_benchmark.py"
    sentinel = tmp_path / "keep.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    result = subprocess.run([sys.executable, str(script), "--directory", str(tmp_path), "--records", "100",
                             "--stocks", "3", "--exit-policy", mode], capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["mode"] == "SYNTHETIC_CAPACITY_ONLY" and payload["execution_allowed"] is False
    assert payload["plan_count"] == 3 and payload["active_positions"] == 3
    assert payload["sizing_assumptions"]["capture_bytes_per_record"] > 0
    assumptions = CapacityAssumptions(**payload["sizing_assumptions"])
    assert assumptions.exit_policy == mode
    if mode == "PRODUCTION_RULES":
        assert payload["analysed_positions"] == 3
        assert payload["feature_commands"] > 0 and payload["feature_command_p95_ms"] > 0
    assert list(tmp_path.iterdir()) == [sentinel]
    result = subprocess.run([sys.executable, str(script), "--directory", str(tmp_path), "--records", "10001"],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 1 and list(tmp_path.iterdir()) == [sentinel]


def test_production_readiness_requires_matching_capacity_and_counts_features(tmp_path):
    paper, capture, values = inputs(tmp_path)
    paper = replace(paper, experiment=replace(paper.experiment, exit_policy="PRODUCTION_RULES"))
    report = evaluate_readiness(paper, capture, **values)
    assert {"EXIT_POLICY_CAPACITY_MISMATCH", "PRODUCTION_EXIT_CAPACITY_UNMEASURED"} <= codes(report)
    old_commands = report.projection.paper_commands
    assumptions = replace(ASSUMPTIONS, exit_policy="PRODUCTION_RULES", feature_interval_seconds=5)
    report = evaluate_readiness(paper, capture, **(values | {"assumptions": assumptions}))
    assert report.ready_for_paper_trial
    assert report.projection.paper_commands > old_commands
    assert report.projection.paper_growth_bytes == report.projection.paper_commands * assumptions.paper_bytes_per_command
    with pytest.raises(ValueError):
        replace(assumptions, feature_interval_seconds=None)
