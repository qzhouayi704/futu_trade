"""Production payload boundary and fail-closed diagnostic source assessments."""
from collections.abc import Mapping
from datetime import datetime, timezone, tzinfo
import json
import math

from scripts.analysis.minute_entry_study.models import HK
from ..protocol import FrozenProtocol
from ..runtime.collector import Collector
from ..runtime.models import SignalObservation, local
from .models import DIAGNOSTIC, IntakeReport, Rejection, SignalRow, Snapshot, StockAudit


class NotSequenceEvent(ValueError):
    """A valid general capital alert is not a FIRST/confirmation sequence event."""


def parse_time(value: str, naive_zone: tzinfo) -> datetime:
    when = datetime.fromisoformat(value)
    if when.tzinfo is None:
        when = when.replace(tzinfo=naive_zone)
    return local(when)


def signal_payload(payload: Mapping[str, object], *, event_id: str, received_at: datetime,
                   source: str, action: str) -> SignalObservation:
    """No clock fallback, current-sector enrichment or invented signal fields."""
    for name in ('stock_code', 'trade_date', 'inflow_stage', 'plate_name', 'direction'):
        if not isinstance(payload[name], str):
            raise ValueError(f'invalid text field: {name}')
    for name in ('is_large_inflow', 'legacy_observe_only'):
        if type(payload[name]) is not bool:
            raise ValueError(f'invalid boolean field: {name}')
    if type(payload['inflow_sequence_no']) is not int:
        raise ValueError('invalid sequence')
    timestamp = float(payload['timestamp'])
    if not math.isfinite(timestamp):
        raise ValueError('invalid epoch timestamp')
    emitted = datetime.fromtimestamp(timestamp, timezone.utc).astimezone(HK)
    if payload['trade_date'] != emitted.date().isoformat():
        raise ValueError('payload trading date differs from epoch')
    if not payload['inflow_stage']:
        raise NotSequenceEvent('general capital alert has no inflow sequence stage')
    return SignalObservation(event_id, payload['stock_code'], local(received_at), source, emitted,
        payload['inflow_stage'], float(payload['last_price']), float(payload['inflow_first_price']),
        payload['inflow_sequence_no'], payload['plate_name'], payload['direction'],
        payload['is_large_inflow'], float(payload['window_buy_ratio']), float(payload['window_main_net']),
        payload['legacy_observe_only'], action)


def persisted_signal(row: SignalRow, observed_at: datetime) -> SignalObservation:
    if row.source != 'capital_trend' or type(row.row_id) is not int or row.row_id < 1:
        raise ValueError('unexpected signal source or identity')
    payload = json.loads(row.detail_json)
    emitted = datetime.fromtimestamp(float(payload['timestamp']), timezone.utc).astimezone(HK)
    persisted = parse_time(row.persisted_text, timezone.utc)
    textual = parse_time(row.emitted_text, HK)
    if abs((textual-emitted).total_seconds()) > 2 or (persisted-emitted).total_seconds() < -2:
        raise ValueError('emission/persistence timestamps disagree')
    available = max(persisted, emitted)  # SQLite CURRENT_TIMESTAMP has second resolution.
    if available > observed_at:
        raise ValueError('signal lies beyond snapshot')
    if row.day != emitted.date().isoformat() or row.code != payload['stock_code']:
        raise ValueError('row identity differs from payload')
    return signal_payload(payload, event_id=f'legacy-sqlite:{row.row_id}', received_at=available,
                          source=DIAGNOSTIC+':SQLITE_CREATED_AT_NOT_SDK_RECEIPT', action=row.action)


class LiveSignalIngress:
    """Worker-side hook only. Caller must provide the actual first receipt time.

    Does not register callbacks, start a worker, subscribe, or connect to any API.
    A live feed wiring layer must durably capture receipt metadata before retrying.
    """
    def __init__(self, collector: Collector | None = None, *, enabled: bool = False):
        if type(enabled) is not bool:
            raise ValueError('explicit boolean enable required')
        if enabled and (collector is None or collector.journal is None or collector.dataset_kind != 'LOCAL_OBSERVATIONS'):
            raise ValueError('explicitly enabled non-diagnostic local collector required')
        self.collector = collector
        self.enabled = enabled

    def on_signal(self, payload: Mapping[str, object], *, source_event_id: str,
                  received_at: datetime) -> bool:
        if not self.enabled:
            return False
        if not source_event_id:
            raise ValueError('stable source event id required')
        try:
            observation = signal_payload(payload, event_id='live-legacy:'+source_event_id,
                received_at=received_at, source='LOCAL_CAPITAL_TREND_EXPLICIT_RECEIPT', action='OBSERVE')
        except NotSequenceEvent:
            return False
        return self.collector.observe(observation)


def assess(snapshot: Snapshot, protocol: FrozenProtocol) -> IntakeReport:
    normalized, rejections = [], []
    if len({row.row_id for row in snapshot.signals}) != len(snapshot.signals):
        raise ValueError('duplicate persisted signal identity')
    for row in snapshot.signals:
        try:
            event = persisted_signal(row, snapshot.observed_at)
            if not snapshot.start_date <= row.day <= snapshot.end_date:
                raise ValueError('signal outside declared snapshot interval')
            if event.emitted_at.date().isoformat() < protocol.earliest_entry_date:
                rejections.append(Rejection(row.row_id, row.code, 'BEFORE_FROZEN_ENTRY_DATE'))
                continue
            if event.received_at.date() != event.emitted_at.date():
                rejections.append(Rejection(row.row_id, row.code, 'PERSISTED_ON_DIFFERENT_DAY'))
                continue
            normalized.append(event)
        except NotSequenceEvent:
            rejections.append(Rejection(row.row_id, row.code, 'GENERAL_ALERT_NOT_INFLOW_SEQUENCE'))
        except (ValueError, TypeError, KeyError, OverflowError, OSError):
            rejections.append(Rejection(row.row_id, row.code, 'INVALID_OR_INCOMPLETE_SOURCE_CONTRACT'))
    normalized.sort(key=lambda e: (e.received_at, int(e.event_id.split(':')[-1])))
    stocks = []
    for code in snapshot.codes:
        equal = after = before = invalid = 0
        ticks = [r for r in snapshot.ticks if r.code == code]
        for row in ticks:
            try:
                exchange = parse_time(row.trade_time, HK)
                stored = datetime.fromtimestamp(float(row.timestamp_ms)/1000, timezone.utc).astimezone(HK)
                delta = (stored-exchange).total_seconds()
                equal += abs(delta) < .001
                after += delta >= .001
                before += delta <= -.001
            except (ValueError, TypeError, OverflowError, OSError):
                invalid += 1
        events = [e for e in normalized if e.code == code]
        stocks.append(StockAudit(code, sum(r.code == code for r in snapshot.signals), len(events),
            sum(e.stage == 'FIRST' for e in events), len(ticks), equal, after, before, invalid,
            sum(r.code == code for r in snapshot.daily)))
    blockers = ('ARCHIVED_MINUTES_HAVE_NO_VERIFIED_FIRST_RECEIPT',
        'TICK_TIMESTAMP_PRODUCER_NOT_IDENTIFIABLE', 'DAILY_POINT_IN_TIME_VERSION_NOT_CAPTURED',
        'NO_PER_STOCK_HISTORICAL_CONNECTION_AND_DROP_EVIDENCE', 'FOCUS_SAMPLE_NOT_UNIVERSE_OR_COMPLETE_TICK_HISTORY')
    if not snapshot.subscription_snapshot_rows:
        blockers += ('NO_SUBSCRIPTION_SNAPSHOT_ROWS',)
    return IntakeReport(snapshot.observed_at.isoformat(), snapshot.sha256, snapshot.codes, tuple(stocks),
                        snapshot.minutes, tuple(rejections), blockers, tuple(normalized))
