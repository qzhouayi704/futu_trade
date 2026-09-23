#!/usr/bin/env python3
"""Read-only paper preflight. Never starts services, captures or orders."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for name, path in (("simple_trade", ROOT / "simple_trade"), ("simple_trade.utils", ROOT / "simple_trade" / "utils")):
    if name not in sys.modules:
        package = ModuleType(name)
        package.__path__ = [str(path)]
        package.__package__ = name
        sys.modules[name] = package

from simple_trade.v2.application.paper_session.readiness import evaluate_readiness
from simple_trade.v2.domain.capture import BookCaptureConfig
from simple_trade.v2.domain.paper_readiness import CapacityAssumptions, ReviewAcknowledgements
from simple_trade.v2.domain.paper_session import PaperSessionConfig
from simple_trade.v2.domain.planning.codec import encode
from simple_trade.v2.infrastructure.paper.readiness_probe import paths_alias, probe_storage


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    capture_input = parser.add_mutually_exclusive_group(required=True)
    capture_input.add_argument("--capture-path", type=Path)
    capture_input.add_argument("--capture-config", type=Path)
    parser.add_argument("--trading-db", type=Path, required=True)
    parser.add_argument("--strategy-version", required=True)
    parser.add_argument("--capacity-report", type=Path)
    parser.add_argument("--protected-stocks", type=int, required=True)
    parser.add_argument("--system-path", type=Path, default=Path(Path.home().anchor))
    parser.add_argument("--at", type=datetime.fromisoformat)
    for name in ("schedule", "securities", "costs", "parameters"):
        parser.add_argument(f"--reviewed-{name}", action="store_true")
    args = parser.parse_args()
    try:
        paper = PaperSessionConfig.from_file(args.config)
        capture = (BookCaptureConfig.from_file(args.capture_config) if args.capture_config
                   else BookCaptureConfig(path=args.capture_path))
        if not args.trading_db.is_absolute() or not args.trading_db.is_file():
            raise ValueError("trading database must be an explicitly identified existing absolute file")
        targets = (paper.path, capture.path, args.trading_db)
        isolated = not any(paths_alias(left, right) for i, left in enumerate(targets) for right in targets[i + 1:])
        assumptions = None
        if args.capacity_report:
            if args.capacity_report.stat().st_size > 262144:
                raise ValueError("capacity report is too large")
            sample = json.loads(args.capacity_report.read_text(encoding="utf-8-sig"))
            if sample.get("schema_version") != 1 or sample.get("mode") != "SYNTHETIC_CAPACITY_ONLY":
                raise ValueError("unsupported capacity report")
            assumptions = CapacityAssumptions(**sample["sizing_assumptions"])
        report = evaluate_readiness(
            paper, capture, when=args.at or datetime.now(timezone.utc),
            expected_strategy_version=args.strategy_version,
            reviews=ReviewAcknowledgements(args.reviewed_schedule, args.reviewed_securities,
                                           args.reviewed_costs, args.reviewed_parameters),
            assumptions=assumptions,
            storage=(probe_storage(capture.path, role="capture"), probe_storage(paper.path, role="paper", paper=paper)),
            isolated_paths=isolated, system_free_bytes=shutil.disk_usage(args.system_path).free,
            protected_stock_count=args.protected_stocks,
        )
        print(encode(report))
        return 0 if report.ready_for_paper_trial else 2
    except Exception as error:
        print(encode({"ready_for_paper_trial": False, "execution_allowed": False,
                      "error": f"{type(error).__name__}:{error}"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
