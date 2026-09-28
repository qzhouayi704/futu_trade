"""End-of-day prefix replay through the unchanged, registered research engine."""
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass, replace
from datetime import date, datetime, time
import hashlib
from pathlib import Path
import numpy as np

from scripts.analysis.minute_entry_study.models import HK, INDEX, N, WALL
from ...data import background
from ...engine import run
from ...legacy.data import make_episodes
from ...legacy.models import LegacyEvent, Study
from ...legacy.signals import signals
from ...metrics import portfolio
from ...models import Market, ReplayResult, StockPath
from ..protocol import FrozenProtocol, SourceHash, scheduled_days
from .collector import verify_frozen
from .models import DailyContextObservation, Event, ExposureObservation, MinuteObservation, SignalObservation, encode, local, logical_key
from .store import SQLiteJournal
from .tracker import ContinuityStatus, continuity


@dataclass(frozen=True)
class AccountSnapshot:
    closed_only_return_pct: float | None
    return_pct: float | None
    open_positions: int
    cash_hkd: float
    missing_mark_minutes: int
    observed_mark_drawdown_pct: float | None
    strict_drawdown_pct: float | None
    mean_capital_occupation_pct: float
    trades: int


@dataclass(frozen=True)
class ArmResult:
    name: str
    replay: ReplayResult
    account: AccountSnapshot


@dataclass(frozen=True)
class AuditCount:
    name: str
    count: int


@dataclass(frozen=True)
class ReplayReport:
    dataset_kind: str
    as_of: str
    through_day: str
    days: tuple[str, ...]
    input_sha256: str
    protocol_sha256: str
    adapter_sources: tuple[SourceHash, ...]
    audit: tuple[AuditCount, ...]
    continuity: tuple[ContinuityStatus, ...]
    arms: tuple[ArmResult, ...]
    exposures: tuple[ExposureObservation, ...]
    status: str = 'LOCAL_EOD_REPLAY_NOT_LIVE_CERTIFIED'
    strategy_validated: bool = False
    live_execution_allowed: bool = False


def adapter_hashes() -> tuple[SourceHash, ...]:
    directory = Path(__file__).parent
    return tuple(SourceHash(f'forward/runtime/{p.name}', hashlib.sha256(p.read_bytes()).hexdigest())
                 for p in sorted(directory.glob('*.py')))


def normalize(protocol: FrozenProtocol, events: tuple[Event, ...], through_day: str,
              as_of: datetime) -> tuple[Study, tuple[Event, ...]]:
    as_of = local(as_of)
    through = date.fromisoformat(through_day)
    days = list(scheduled_days(date.fromisoformat(protocol.earliest_entry_date), through))
    if (not days or days[-1] != through_day or as_of.date() != through
            or as_of < datetime.combine(through, time(16, 30), HK)):
        raise ValueError('only a completed checked trading session can be replayed')
    # Later events cannot change an earlier replay's evidence hash or decisions.
    prefix = tuple(e for e in events if e.received_at <= as_of)
    if len(prefix) > 200000 or len({e.event_id for e in prefix}) != len(prefix) or len({logical_key(e) for e in prefix}) != len(prefix):
        raise ValueError('bounded unique journal observations required')
    if any(a.received_at > b.received_at for a, b in zip(prefix, prefix[1:])):
        raise ValueError('receipt-ordered journal required')
    # Derived checkpoints are not new market evidence. Replaying unchanged inputs
    # must produce the same checkpoint, not a self-referential hash/new event loop.
    fingerprint = hashlib.sha256('\n'.join(encode(e) for e in prefix
        if not isinstance(e, ExposureObservation)).encode('utf-8')).hexdigest()
    counts: Counter[str] = Counter()
    day_map = {day: i for i, day in enumerate(days)}
    selected: list[LegacyEvent] = []
    contexts = {(e.code, e.for_day): e for e in prefix if isinstance(e, DailyContextObservation)}
    for index, e in enumerate(prefix):
        if not isinstance(e, SignalObservation):
            continue
        day = e.received_at.date().isoformat()
        wall = e.received_at.hour*60+e.received_at.minute
        if day not in day_map or e.emitted_at.date() != e.received_at.date() or (e.stage == 'FIRST' and wall not in INDEX):
            counts['signals_outside_observable_session'] += 1
            continue
        selected.append(LegacyEvent(index, e.code, day, e.received_at, bisect_left(WALL, wall), e.stage,
            e.direction, e.large_inflow, e.price, e.first_price, e.sequence, e.sector, e.action,
            e.buy_ratio, e.window_net, e.observe_only))
    codes = sorted({e.code for e in selected})
    if len(codes) > 200:
        raise ValueError('local replay stock capacity exceeded')
    paths: dict[str, StockPath] = {}
    for code in codes:
        backgrounds = []
        for day in days:
            ctx = contexts.get((code, day))
            usable = ctx is not None and ctx.preopen
            counts['missing_or_late_daily_contexts'] += not usable
            backgrounds.append(background(list(ctx.rows) if usable else [], day))
        paths[code] = StockPath(code, *[np.full(len(days)*N, np.nan) for _ in range(6)], backgrounds)
    for e in prefix:
        if not isinstance(e, MinuteObservation):
            continue
        day = e.minute_at.date().isoformat()
        if e.code not in paths or day not in day_map:
            continue
        if not e.on_time:
            counts['late_minutes_excluded'] += 1
            continue
        point = day_map[day]*N+INDEX[e.minute_at.hour*60+e.minute_at.minute]
        path = paths[e.code]
        for array, value in zip((path.mean, path.high, path.low, path.volume, path.buy, path.sell),
                                (e.mean, e.high, e.low, e.volume, e.buy, e.sell)):
            array[point] = value
        counts['on_time_minutes'] += 1
    counts['missing_stock_session_minutes'] = len(codes)*len(days)*N-counts['on_time_minutes']
    market = Market(days, paths, [], fingerprint, {}, {})
    episodes = make_episodes(selected, market, counts)
    market.opportunities = [e.opportunity for e in episodes]
    market.audit = dict(counts)
    return Study(market, episodes, selected, dict(counts), dict(Counter(e.stage for e in selected)), []), prefix


def replay(protocol: FrozenProtocol, events: tuple[Event, ...], through_day: str,
           as_of: datetime, dataset_kind: str = 'LOCAL_OBSERVATIONS') -> ReplayReport:
    verify_frozen(protocol)
    if dataset_kind not in ('LOCAL_OBSERVATIONS', 'SYNTHETIC'):
        raise ValueError('explicit supported dataset kind required')
    if any(e.source.startswith('ARCHIVE_DIAGNOSTIC') for e in events):
        raise ValueError('diagnostic archive observations cannot enter prospective performance replay')
    as_of = local(as_of)
    study, prefix = normalize(protocol, events, through_day, as_of)
    market = study.market
    entry_days = list(range(len(market.days)))
    arms = []
    for arm in protocol.arms:
        result = run(market, signals(study, arm.entry), arm.exit, protocol.costs,
                     entry_days, len(market.days)-1, protocol.maximum_positions)
        account = AccountSnapshot(**portfolio(market, result.trades, protocol.costs, 0, len(market.days)-1))
        if not result.trades:
            # No observed trades is not measured zero strategy performance.
            account = replace(account, closed_only_return_pct=None, return_pct=None,
                              observed_mark_drawdown_pct=None, strict_drawdown_pct=None)
        arms.append(ArmResult(arm.name, result, account))
    # Checkpoints are observations for the caller to append explicitly, not orders.
    # Include previously tracked codes so a now-flat replay can clear a prior exposure.
    codes = sorted({e.first.code for e in study.episodes})
    exposures = tuple(ExposureObservation(
        f'eod:{as_of.isoformat()}:{market.sha256[:16]}:{code}', code, as_of, 'LOCAL_FROZEN_EOD_REPLAY',
        tuple(arm.name for arm in arms if any(t.code == code and t.exit is None for t in arm.replay.trades)), through_day)
        for code in codes)
    return ReplayReport(dataset_kind, as_of.isoformat(), through_day, tuple(market.days), market.sha256,
        SQLiteJournal.fingerprint(protocol), adapter_hashes(),
        tuple(AuditCount(k, int(v)) for k, v in sorted(study.counts.items())),
        tuple(continuity(prefix, code, as_of) for code in market.paths), tuple(arms), exposures)
