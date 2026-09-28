"""Validated, immutable observation contracts and JSON boundary codec."""
from dataclasses import asdict, dataclass, fields
from datetime import date, datetime, time, timedelta
import json
import math
from pathlib import Path
import re
from typing import Protocol, TypeAlias

from scripts.analysis.minute_entry_study.models import HK, INDEX
from ...models import Daily
from ..protocol import CALENDAR_END, FrozenProtocol, scheduled_days


def local(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('timezone required')
    return value.astimezone(HK)


def session(value: datetime) -> str:
    value = local(value)
    day = value.date()
    if not scheduled_days(day, day):
        raise ValueError('not a checked trading session')
    return day.isoformat()


@dataclass(frozen=True)
class Observation:
    event_id: str
    code: str
    received_at: datetime
    source: str

    def __post_init__(self) -> None:
        if not self.event_id or len(self.event_id) > 200 or not self.source or len(self.source) > 200:
            raise ValueError('bounded event id and source required')
        if not re.fullmatch(r'HK\.\d{5}', self.code):
            raise ValueError('HK stock code required')
        object.__setattr__(self, 'received_at', local(self.received_at))


@dataclass(frozen=True)
class SignalObservation(Observation):
    emitted_at: datetime
    stage: str
    price: float
    first_price: float
    sequence: int
    sector: str
    direction: str = 'RISING'
    large_inflow: bool = True
    buy_ratio: float = .6
    window_net: float = 100000.
    observe_only: bool = True
    action: str = 'OBSERVE'

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, 'emitted_at', local(self.emitted_at))
        if (type(self.large_inflow) is not bool or type(self.observe_only) is not bool
                or type(self.sequence) is not int):
            raise ValueError('strict signal boolean/integer fields required')
        if self.received_at < self.emitted_at:
            raise ValueError('signal received before emission')
        if not self.stage or self.sequence < 0 or not all(math.isfinite(x) for x in
                (self.price, self.first_price, self.buy_ratio, self.window_net)):
            raise ValueError('invalid signal fields')
        if self.price <= 0 or self.first_price < 0 or not 0 <= self.buy_ratio <= 1:
            raise ValueError('invalid signal prices or ratio')


@dataclass(frozen=True)
class MinuteObservation(Observation):
    minute_at: datetime
    mean: float
    high: float
    low: float
    volume: float
    buy: float
    sell: float

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, 'minute_at', local(self.minute_at))
        session(self.minute_at)
        if self.minute_at.second or self.minute_at.microsecond or self.minute_at.hour*60+self.minute_at.minute not in INDEX:
            raise ValueError('aligned regular-session minute required')
        if self.received_at < self.minute_at+timedelta(minutes=1):
            raise ValueError('incomplete minute')
        values = (self.mean, self.high, self.low, self.volume, self.buy, self.sell)
        if not all(math.isfinite(x) for x in values) or not 0 < self.low <= self.mean <= self.high or min(values[3:]) < 0:
            raise ValueError('invalid minute')

    @property
    def on_time(self) -> bool:
        return self.received_at <= self.minute_at+timedelta(seconds=61)


@dataclass(frozen=True)
class DailyContextObservation(Observation):
    for_day: str
    rows: tuple[Daily, ...]
    version: str

    def __post_init__(self) -> None:
        super().__post_init__()
        day = date.fromisoformat(self.for_day)
        session(datetime.combine(day, time(9), HK))
        if not isinstance(self.rows, tuple) or not self.version or len(self.rows) > 60 or len({r.day for r in self.rows}) != len(self.rows):
            raise ValueError('unique bounded daily history/version required')
        if tuple(sorted(self.rows, key=lambda r: r.day)) != self.rows:
            raise ValueError('daily rows must be sorted')
        for row in self.rows:
            if date.fromisoformat(row.day) >= day or not all(math.isfinite(x) for x in
                    (row.close, row.high, row.low, row.turnover)) or not 0 < row.low <= row.close <= row.high or row.turnover < 0:
                raise ValueError('invalid or future daily row')
            if datetime.combine(date.fromisoformat(row.day), time(16, 30), HK) > self.received_at:
                raise ValueError('daily close was not available when context was received')

    @property
    def preopen(self) -> bool:
        return self.received_at < datetime.combine(date.fromisoformat(self.for_day), time(9, 30), HK)


@dataclass(frozen=True)
class ContinuityObservation(Observation):
    connected: bool
    subscribed: bool
    connection_id: str
    dropped_total: int
    cumulative_volume: float | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if type(self.connected) is not bool or type(self.subscribed) is not bool or type(self.dropped_total) is not int:
            raise ValueError('strict continuity boolean/integer fields required')
        if not self.connection_id or self.dropped_total < 0:
            raise ValueError('connection identity/nonnegative drop counter required')
        if self.cumulative_volume is not None and (not math.isfinite(self.cumulative_volume) or self.cumulative_volume < 0):
            raise ValueError('invalid independent volume')


@dataclass(frozen=True)
class ExposureObservation(Observation):
    active_arms: tuple[str, ...]
    through_day: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        allowed = {'candidate-3d', 'candidate-5d', 'control-3d', 'control-5d'}
        if not isinstance(self.active_arms, tuple) or len(set(self.active_arms)) != len(self.active_arms) or not set(self.active_arms) <= allowed:
            raise ValueError('unknown or duplicate research arm')
        if self.through_day is not None:
            if (self.through_day != session(self.received_at)
                    or self.received_at < datetime.combine(self.received_at.date(), time(16, 30), HK)):
                raise ValueError('exposure reconciliation requires same-day completed session')


Event: TypeAlias = SignalObservation | MinuteObservation | DailyContextObservation | ContinuityObservation | ExposureObservation
EVENT_TYPES = {t.__name__: t for t in (SignalObservation, MinuteObservation, DailyContextObservation, ContinuityObservation, ExposureObservation)}


def encode(event: Event) -> str:
    return json.dumps({'kind': type(event).__name__, 'data': asdict(event)}, ensure_ascii=False,
                      sort_keys=True, separators=(',', ':'), allow_nan=False, default=lambda x: x.isoformat())


def decode(payload: str) -> Event:
    envelope = json.loads(payload)
    cls = EVENT_TYPES[envelope['kind']]
    data = envelope['data']
    if set(data) != {f.name for f in fields(cls)}:
        raise ValueError('observation schema mismatch')
    for key in ('received_at', 'emitted_at', 'minute_at'):
        if key in data:
            data[key] = datetime.fromisoformat(data[key])
    if cls is DailyContextObservation:
        data['rows'] = tuple(Daily(**r) for r in data['rows'])
    if cls is ExposureObservation:
        data['active_arms'] = tuple(data['active_arms'])
    return cls(**data)


def logical_key(event: Event) -> str:
    if isinstance(event, MinuteObservation):
        return f'minute:{event.code}:{event.minute_at.isoformat()}'
    if isinstance(event, DailyContextObservation):
        return f'daily:{event.code}:{event.for_day}'
    return f'event:{event.event_id}'


@dataclass(frozen=True)
class Config:
    path: Path
    enabled: bool = False
    dataset_kind: str = 'LOCAL_OBSERVATIONS'
    max_events: int = 200000
    max_database_bytes: int = 128*1024*1024

    def __post_init__(self) -> None:
        if (type(self.enabled) is not bool or type(self.max_events) is not int or type(self.max_database_bytes) is not int
                or self.dataset_kind not in ('LOCAL_OBSERVATIONS', 'SYNTHETIC', 'ARCHIVE_DIAGNOSTIC') or self.max_events < 1 or self.max_database_bytes < 65536):
            raise ValueError('invalid local research configuration')


@dataclass(frozen=True)
class Track:
    code: str
    first_at: datetime
    until_day: str
    active_arms: tuple[str, ...] = ()
    reconciled_through: str | None = None


class Journal(Protocol):
    def events(self) -> tuple[Event, ...]: ...
    def append(self, event: Event) -> bool: ...
    def close(self) -> None: ...


def protocol_days(protocol: FrozenProtocol) -> tuple[str, ...]:
    return scheduled_days(date.fromisoformat(protocol.earliest_entry_date), CALENDAR_END)
