"""Pure cross-session leases and non-executing subscription recommendations."""
from dataclasses import dataclass, replace
from datetime import datetime, time

from scripts.analysis.minute_entry_study.models import HK, INDEX
from ...data import theme_of
from ..protocol import FrozenProtocol
from .models import ContinuityObservation, Event, ExposureObservation, SignalObservation, Track, local, protocol_days


def transition(tracks: tuple[Track, ...], event: Event, protocol: FrozenProtocol) -> tuple[Track, ...]:
    by_code = {t.code: t for t in tracks}
    if isinstance(event, SignalObservation):
        day = event.received_at.date().isoformat()
        days = protocol_days(protocol)
        eligible = (event.stage == 'FIRST' and event.direction == 'RISING' and event.large_inflow
                    and event.sequence == 1 and theme_of(event.sector) and day in days
                    and event.emitted_at.date() == event.received_at.date()
                    and event.received_at.hour*60+event.received_at.minute in INDEX)
        if eligible:
            start = days.index(day)
            if start+5 > len(days):
                raise ValueError('calendar does not cover five-session tracking lease')
            previous = by_code.get(event.code)
            by_code[event.code] = Track(event.code, previous.first_at if previous else event.received_at,
                max(previous.until_day, days[start+4]) if previous else days[start+4],
                previous.active_arms if previous else (), previous.reconciled_through if previous else None)
    elif isinstance(event, ExposureObservation):
        previous = by_code.get(event.code)
        if previous is None:
            raise ValueError('research exposure requires a known tracked FIRST')
        by_code[event.code] = replace(previous, active_arms=event.active_arms,
                                     reconciled_through=event.through_day or previous.reconciled_through)
    return tuple(sorted(by_code.values(), key=lambda t: (t.first_at, t.code)))


@dataclass(frozen=True)
class Selection:
    protected: tuple[str, ...]
    research: tuple[str, ...]
    deferred: tuple[str, ...]
    over_capacity: bool
    execution_allowed: bool = False


def select(tracks: tuple[Track, ...], when: datetime, protected_codes: tuple[str, ...], capacity: int) -> Selection:
    when = local(when)
    if capacity < 0:
        raise ValueError('nonnegative capacity required')
    protected = tuple(sorted(set(protected_codes)))
    active = [t for t in tracks if t.first_at <= when and (t.active_arms
              or t.reconciled_through is None or t.reconciled_through < t.until_day or when <=
              datetime.combine(datetime.fromisoformat(t.until_day).date(), time(16, 30), HK))]
    active.sort(key=lambda t: (not bool(t.active_arms), t.first_at, t.code))
    choices = [t.code for t in active if t.code not in protected]
    available = max(0, capacity-len(protected))
    return Selection(protected, tuple(choices[:available]), tuple(choices[available:]),
                     len(protected)+len(choices) > capacity)


@dataclass(frozen=True)
class ContinuityStatus:
    code: str
    state: str
    latest_received_at: str | None
    wall_clock_gaps: int
    reconnects: int
    reported_drops: int
    counter_resets: int
    disconnected_samples: int
    zero_volume_reported: bool
    complete_tick_capture_certified: bool = False


def continuity(events: tuple[Event, ...], code: str, when: datetime, max_age_seconds: int = 90) -> ContinuityStatus:
    when = local(when)
    if max_age_seconds <= 0:
        raise ValueError('positive continuity maximum age required')
    series = [e for e in events if isinstance(e, ContinuityObservation) and e.code == code and e.received_at <= when]
    if not series:
        return ContinuityStatus(code, 'UNKNOWN_NO_EVIDENCE', None, 0, 0, 0, 0, 0, False)
    gaps = sum((b.received_at-a.received_at).total_seconds() > max_age_seconds for a, b in zip(series, series[1:]))
    reconnects = sum(a.connection_id != b.connection_id for a, b in zip(series, series[1:]))
    resets = sum(a.connection_id == b.connection_id and b.dropped_total < a.dropped_total for a, b in zip(series, series[1:]))
    disconnected = sum(not e.connected or not e.subscribed for e in series)
    drops = series[0].dropped_total
    for a, b in zip(series, series[1:]):
        drops += b.dropped_total if a.connection_id != b.connection_id else max(0, b.dropped_total-a.dropped_total)
    last = series[-1]
    if (when-last.received_at).total_seconds() > max_age_seconds:
        state = 'UNKNOWN_STALE_EVIDENCE'
    elif not last.connected or not last.subscribed:
        state = 'DISCONNECTED_OR_UNSUBSCRIBED'
    else:
        state = 'HEARTBEAT_PRESENT_NOT_TICK_CERTIFIED'
    return ContinuityStatus(code, state, last.received_at.isoformat(), gaps, reconnects, drops, resets,
                            disconnected, last.cumulative_volume == 0)
