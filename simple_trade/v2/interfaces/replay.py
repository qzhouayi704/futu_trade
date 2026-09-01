"""Deterministic market-event replay driven by VirtualClock."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, time

from ..application.event_bus import EventBus
from ..domain.enums import DataQuality, EventType
from ..domain.events import DataQualityEvent, DomainEvent
from ..ports.clock import VirtualClock
from .event_digest import event_stream_digest


TradingDayProvider = Callable[[str, date], bool]


class MarketSessionPolicy:
    def __init__(self, trading_day_provider: TradingDayProvider | None = None) -> None:
        self._trading_day_provider = trading_day_provider or self._weekday_only

    def is_open(self, stock_code: str, exchange_time) -> bool:
        market = "US" if stock_code.startswith("US.") else "HK"
        if not self._trading_day_provider(market, exchange_time.date()):
            return False
        current = exchange_time.timetz().replace(tzinfo=None)
        if market == "HK":
            return time(9, 30) <= current < time(12, 0) or time(13, 0) <= current < time(16, 0)
        return time(9, 30) <= current < time(16, 0)

    @staticmethod
    def _weekday_only(market: str, day: date) -> bool:
        return day.weekday() < 5


@dataclass(frozen=True, slots=True)
class ReplaySummary:
    input_events: int
    published_events: int
    eligible_events: int
    closed_session_events: int
    out_of_order_events: int
    semantic_digest: str


class ReplayEngine:
    def __init__(
        self,
        bus: EventBus,
        clock: VirtualClock,
        session_policy: MarketSessionPolicy | None = None,
    ) -> None:
        self._bus = bus
        self._clock = clock
        self._session_policy = session_policy or MarketSessionPolicy()

    async def replay(self, events: Iterable[DomainEvent]) -> ReplaySummary:
        source_events = tuple(events)
        published = 0
        eligible = 0
        closed = 0
        out_of_order = 0

        for event in source_events:
            if event.exchange_time < self._clock.now():
                quality_event = self._quality_event(event, "OUT_OF_ORDER_REPLAY_TIME")
                if await self._bus.publish(quality_event):
                    published += 1
                out_of_order += 1
            else:
                self._clock.set(event.exchange_time)

            if self._session_policy.is_open(event.stock_code, event.exchange_time):
                eligible += 1
            else:
                quality_event = self._quality_event(event, "SESSION_CLOSED")
                if await self._bus.publish(quality_event):
                    published += 1
                closed += 1

            if await self._bus.publish(event):
                published += 1

        await self._bus.join()
        return ReplaySummary(
            input_events=len(source_events),
            published_events=published,
            eligible_events=eligible,
            closed_session_events=closed,
            out_of_order_events=out_of_order,
            semantic_digest=event_stream_digest(source_events),
        )

    @staticmethod
    def _quality_event(event: DomainEvent, reason_code: str) -> DataQualityEvent:
        return DataQualityEvent(
            event_type=EventType.DATA_QUALITY_CHANGED,
            stock_code=event.stock_code,
            exchange_time=event.exchange_time,
            received_time=event.received_time,
            source="v2.replay",
            schema_version=event.schema_version,
            strategy_version=event.strategy_version,
            sequence=event.sequence,
            quality=DataQuality.DEGRADED,
            reason_codes=(reason_code,),
        )
