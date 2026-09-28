"""Deterministic fictional prices for plumbing checks, never market evidence."""
from datetime import date, datetime, time, timedelta

from scripts.analysis.minute_entry_study.models import HK, WALL
from ...models import Daily
from ..protocol import CLOSED, FrozenProtocol
from .models import ContinuityObservation, DailyContextObservation, Event, MinuteObservation, SignalObservation, protocol_days


def synthetic_events(protocol: FrozenProtocol, sessions: int = 5,
                     codes: tuple[str, ...] = ('HK.00100', 'HK.00699')) -> tuple[Event, ...]:
    days = protocol_days(protocol)[:sessions]
    events: list[Event] = []
    for offset, day_text in enumerate(days):
        day = date.fromisoformat(day_text)
        prior = []
        cursor = day-timedelta(days=1)
        while len(prior) < 21:
            if cursor.weekday() < 5 and cursor not in CLOSED:
                prior.append(Daily(cursor.isoformat(), 10., 11.5, 9.5, 20000000.))
            cursor -= timedelta(days=1)
        for code in codes:
            prefix = f'SYNTHETIC:{day_text}:{code}'
            events.append(DailyContextObservation(prefix+':daily', code, datetime.combine(day, time(9), HK),
                          'SYNTHETIC_FIXTURE', day_text, tuple(reversed(prior)), 'fictional-v1'))
            if offset < 2:
                for stage, minute, seq in (('FIRST', 34, 1), ('CONFIRMED', 40, 2)):
                    when = datetime.combine(day, time(9, minute, 30), HK)
                    events.append(SignalObservation(prefix+':'+stage, code, when, 'SYNTHETIC_FIXTURE', when,
                                  stage, 10., 10., seq, '科技'))
            for index, wall in enumerate(WALL):
                when = datetime.combine(day, time(wall//60, wall % 60), HK)
                price = 10.+min(index, 10)*.001
                events.append(MinuteObservation(prefix+f':minute:{index}', code, when+timedelta(seconds=61),
                              'SYNTHETIC_FIXTURE', when, price, price+.001, price-.001, 100000., 70000., 30000.))
            when = datetime.combine(day, time(16, 29, 30), HK)
            events.append(ContinuityObservation(prefix+':heartbeat', code, when, 'SYNTHETIC_FIXTURE',
                          True, True, f'connection-{offset}', offset, None))
    return tuple(sorted(events, key=lambda e: (e.received_at, e.event_id)))
