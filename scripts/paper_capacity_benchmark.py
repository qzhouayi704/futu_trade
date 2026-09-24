#!/usr/bin/env python3
"""Bounded synthetic SQLite workload, not a strategy backtest or live feed test."""

import argparse
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import math
from pathlib import Path
import platform
import shutil
import sys
import tempfile
import time
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for name, path in (("simple_trade", ROOT / "simple_trade"), ("simple_trade.utils", ROOT / "simple_trade" / "utils")):
    if name not in sys.modules:
        package = ModuleType(name)
        package.__path__ = [str(path)]
        package.__package__ = name
        sys.modules[name] = package

from simple_trade.v2.application.paper_session.service import PaperSessionService
from simple_trade.v2.domain.capture import BookCaptureConfig, CapturedBook, CaptureStats
from simple_trade.v2.domain.decisions import DecisionEvent
from simple_trade.v2.domain.enums import DataQuality, EventType
from simple_trade.v2.domain.events import FeatureSnapshotEvent
from simple_trade.v2.domain.features import FeatureSnapshot, MarketContext, PriceAcceptance, PricePosition
from simple_trade.v2.domain.market import QuoteSnapshot, TickAggregate
from simple_trade.v2.domain.paper_session import PaperExperiment, PaperSessionConfig, PaperSessionInterval
from simple_trade.v2.domain.planning.codec import encode
from simple_trade.v2.domain.planning.models import PaperExitPolicy, PaperPolicy
from simple_trade.v2.infrastructure.book_capture.archive import SqliteBookArchive
from simple_trade.v2.infrastructure.paper.session_store import SqlitePaperSessionStore


D = Decimal
BASE = datetime(2026, 9, 23, 10, tzinfo=timezone(timedelta(hours=8)))


def percentile95(values: list[float]) -> float:
    return sorted(values)[math.ceil(len(values) * 0.95) - 1]


def _experiment(codes: tuple[str, ...], exit_policy: PaperExitPolicy) -> PaperExperiment:
    return PaperExperiment(
        experiment_id="synthetic-capacity-v1", strategy_id="capacity-fixture", strategy_version="synthetic-v1",
        stock_codes=codes, schedule_source="synthetic-window-not-a-trading-calendar",
        intervals=(PaperSessionInterval(BASE.replace(hour=9, minute=30), BASE.replace(hour=12)),),
        allow_sampled_server_time=True, policy=PaperPolicy(initial_cash=D("100000"), fee_rate=D("0.001"), minimum_fee=D("3")),
        atr_stop_multiple=D("1"), minimum_stop_fraction=D("0.02"), maximum_stop_fraction=D("0.10"),
        pullback_fraction=D("0.005"), chase_fraction=D("0.005"), entry_ttl_seconds=120,
        exit_before_close_seconds=300, maximum_signal_age_seconds=5,
        exit_policy=exit_policy,
    )


def _signal(code: str) -> DecisionEvent:
    stamp = BASE.isoformat()
    return DecisionEvent(
        event_type=EventType.BUY_CONFIRMED, stock_code=code, exchange_time=BASE, received_time=BASE,
        source="synthetic.capacity", strategy_version="synthetic-v1", event_id=f"signal:{code}",
        new_state="CONFIRMED", reason_code="SYNTHETIC_NOT_A_REAL_SIGNAL",
        payload={"alert_eligible": True, "lifecycle_strategy_source": "capacity-fixture", "feature_snapshot": {
            "stock_code": code, "computed_at": stamp, "quality": "GOOD",
            "quote": {"stock_code": code, "quality": "GOOD", "last_price": 10, "exchange_time": stamp,
                      "lot_size_observation": {"stock_code": code, "lot_size": 100, "source": "synthetic",
                                               "observed_at": stamp, "quote_exchange_time": stamp}},
            "price_position": {"as_of": stamp, "quality": "GOOD", "atr_percent": 3},
        }},
    )


def _feature(code: str, when: datetime) -> FeatureSnapshotEvent:
    flow = TickAggregate(stock_code=code, as_of=when, window_seconds=900, buy_amount=500_000,
                         sell_amount=100_000, main_net=400_000, big_buy_count=3, big_sell_count=1,
                         independent_buy_events=3, independent_sell_events=1, buy_sell_ratio=5 / 6,
                         cumulative_main_net=400_000, cumulative_peak=400_000, cumulative_trough=0,
                         last_sequence=4, sample_count=4, quality=DataQuality.GOOD,
                         last_independent_buy_at=when, large_order_threshold=100_000, flow_scale=300_000)
    feature = FeatureSnapshot(stock_code=code, computed_at=when,
                              quote=QuoteSnapshot(stock_code=code, exchange_time=when, last_price=10, prev_close=10),
                              tick_windows=(flow,), activity_score=80, liquidity_score=80,
                              price_acceptance_score=80, quality=DataQuality.GOOD,
                              market_context=MarketContext(as_of=when, market_breadth=.6, market_sample_size=30,
                                  sector_code="SYNTHETIC", sector_breadth=.6, sector_sample_size=8,
                                  relative_strength=0, quality=DataQuality.GOOD),
                              price_position=PricePosition(as_of=when, daily_percentile=.3, atr_percent=3,
                                  drawdown_from_high=-1, distance_to_ma20=1, structure="MID", quality=DataQuality.GOOD),
                              price_acceptance=PriceAcceptance(as_of=when, score=80, confirmation_price=10,
                                  current_price=10, vwap=10, return_from_confirmation_pct=0,
                                  distance_to_vwap_pct=0, drawdown_from_peak_pct=0,
                                  accepted=True, quality=DataQuality.GOOD))
    return FeatureSnapshotEvent(event_type=EventType.FEATURE_SNAPSHOT_READY, stock_code=code,
                                exchange_time=when, received_time=when, source="synthetic.capacity",
                                strategy_version="synthetic-v1", snapshot=feature)


def benchmark(directory: Path, *, records: int, stocks: int,
              exit_policy: PaperExitPolicy = PaperExitPolicy.RESEARCH_ATR, feature_interval_seconds: int = 5) -> dict:
    directory = directory.resolve(strict=True)
    if not directory.is_dir() or not 100 <= records <= 10000 or not 1 <= stocks <= 8:
        raise ValueError("require existing directory, 100-10000 records, 1-8 stocks")
    exit_policy = PaperExitPolicy(exit_policy)
    if type(feature_interval_seconds) is not int or not 1 <= feature_interval_seconds <= 60:
        raise ValueError("feature interval must be 1-60 seconds")
    if shutil.disk_usage(directory).free < 1024 ** 3:
        raise ValueError("benchmark requires at least 1 GiB free disk space")
    with tempfile.TemporaryDirectory(prefix="paper-capacity-", dir=directory) as name:
        root = Path(name).resolve(strict=True)
        if root.parent != directory:
            raise ValueError("temporary benchmark directory escaped requested root")
        return _run(root, records, stocks, exit_policy, feature_interval_seconds)


def _run(root: Path, records: int, stocks: int, exit_policy: PaperExitPolicy, feature_interval_seconds: int) -> dict:
    codes = tuple(f"HK.{i + 1:05d}" for i in range(stocks))
    cfg = PaperSessionConfig(path=root / "paper.sqlite", account_id="paper:synthetic-capacity", experiment=_experiment(codes, exit_policy))
    cap = BookCaptureConfig(path=root / "capture.sqlite")
    archive = SqliteBookArchive(cap)
    store = SqlitePaperSessionStore(cfg)
    run_config = encode({**asdict(cfg), "path": str(cfg.path)})
    store.begin_run("synthetic-run", run_config)
    archive.start("synthetic-session", BASE)
    service = PaperSessionService(store, cfg.experiment)
    for code in codes:
        service.signal(_signal(code), BASE)
    book_times, capture_times = [], []
    last_features: dict[str, datetime] = {}
    feature_times = []
    began = time.perf_counter()
    deadline = began + 180
    for offset in range(0, records, cap.batch_size):
        if time.perf_counter() > deadline:
            raise TimeoutError("synthetic workload exceeded 180-second budget")
        batch = []
        for i in range(offset, min(offset + cap.batch_size, records)):
            when = BASE + timedelta(seconds=2 + (i // stocks) * cap.sample_interval_seconds)
            batch.append(CapturedBook(
                session_id="synthetic-session", sequence=i + 1, connection_id="synthetic-connection",
                stock_code=codes[i % stocks], received_at=when, bid_time=when, ask_time=when,
                bid=D("9.99"), ask=D("10"), bid_size=10000, ask_size=10000,
            ))
        total = offset + len(batch)
        status = CaptureStats(True, "synthetic-session", codes, codes, (), total, 0, 0, 0, total, 0, 0, 0,
                              batch[-1].received_at, None)
        start = time.perf_counter()
        archive.write(tuple(batch), status)
        capture_times.append(time.perf_counter() - start)
        for book in batch:
            start = time.perf_counter()
            service.book(book, book.received_at)
            # The actual runner also reloads the account after every committed command.
            service.store.read()
            book_times.append(time.perf_counter() - start)
            if exit_policy is PaperExitPolicy.PRODUCTION_RULES and (
                book.stock_code not in last_features or
                (book.received_at - last_features[book.stock_code]).total_seconds() >= feature_interval_seconds
            ):
                start = time.perf_counter()
                service.feature(_feature(book.stock_code, book.received_at), book.received_at)
                service.store.read()
                feature_times.append(time.perf_counter() - start)
                last_features[book.stock_code] = book.received_at
    elapsed = time.perf_counter() - began
    store.finish_run("synthetic-run", None)
    archive.write((), status, ended_at=batch[-1].received_at)
    account = store.read()
    capture_bytes, paper_bytes = cap.path.stat().st_size, cfg.path.stat().st_size
    return {
        "schema_version": 1, "mode": "SYNTHETIC_CAPACITY_ONLY", "execution_allowed": False,
        "measured_at": datetime.now(timezone.utc), "platform": platform.system(),
        "records": records, "stocks": stocks, "elapsed_seconds": elapsed,
        "sequential_records_per_second": records / elapsed,
        "paper_command_p95_ms": percentile95(book_times) * 1000,
        "feature_command_p95_ms": percentile95(feature_times) * 1000 if feature_times else None,
        "feature_commands": len(feature_times), "exit_policy": exit_policy,
        "analysed_positions": sum(order.position_state is not None for order in account.orders),
        "archive_batch_p95_ms": percentile95(capture_times) * 1000,
        "archive_bytes": capture_bytes, "paper_bytes": paper_bytes,
        "plan_count": len(account.orders), "fill_count": len(account.fills),
        "active_positions": sum(order.held > 0 for order in account.orders),
        "sizing_assumptions": {
            "capture_bytes_per_record": math.ceil(capture_bytes / records * 2),
            "paper_bytes_per_command": math.ceil(paper_bytes / (records + stocks + len(feature_times)) * 2),
            "source": f"synthetic-v1:{records}-records:{stocks}-stocks:2x-average-not-a-hard-bound",
            "extra_commands": 1000,
            "exit_policy": exit_policy,
            "feature_interval_seconds": feature_interval_seconds if feature_times else None,
        },
        "limitations": ["合成固定价格，不是盈利回测", "本机顺序写入，不验证服务器并发或真实推送",
                        "两倍平均占用只是预算假设，不保证最坏情况", "临时账本在受控目录中清理，不保留为真实行情证据"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--records", type=int, default=4000)
    parser.add_argument("--stocks", type=int, default=3)
    parser.add_argument("--exit-policy", choices=[mode.value for mode in PaperExitPolicy], default="RESEARCH_ATR")
    parser.add_argument("--feature-interval", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.output and args.output.exists():
            raise ValueError("refusing to overwrite existing report")
        result = encode(benchmark(args.directory, records=args.records, stocks=args.stocks,
                                  exit_policy=PaperExitPolicy(args.exit_policy), feature_interval_seconds=args.feature_interval))
        if args.output:
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(result + "\n")
        print(result)
        return 0
    except Exception as error:
        print(encode({"mode": "SYNTHETIC_CAPACITY_ONLY", "error": f"{type(error).__name__}:{error}"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
