"""Incremental big-order flow windows with split-order event grouping."""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from math import exp, log, tanh
import threading

from ...domain.enums import CapitalMemoryState, DataQuality, TickDirection
from ...domain.features import CapitalBaseline
from ...domain.market import CapitalMemory, TickAggregate, TickTrade
from .quality import worst_quality


DEFAULT_WINDOWS = (60, 300, 900, 1800, 3600)


@dataclass(frozen=True, slots=True)
class CapitalFlowUpdate:
    accepted: bool
    is_large_order: bool
    is_independent_event: bool
    event_group: int | None


@dataclass(frozen=True, slots=True)
class _FlowSample:
    exchange_time: datetime
    price: float
    amount: float
    direction: TickDirection
    sequence: int | None
    event_group: int


@dataclass(frozen=True, slots=True)
class _ActiveSample:
    exchange_time: datetime
    amount: float
    direction: TickDirection


@dataclass(slots=True)
class _FlowEvent:
    started_at: datetime
    last_at: datetime
    amount: float
    direction: TickDirection
    event_group: int


@dataclass(slots=True)
class _StockState:
    trade_date: object
    samples: deque[_FlowSample] = field(default_factory=deque)
    active_samples: deque[_ActiveSample] = field(default_factory=deque)
    events: deque[_FlowEvent] = field(default_factory=deque)
    seen_keys: set[tuple[object, ...]] = field(default_factory=set)
    seen_order: deque[tuple[object, ...]] = field(default_factory=deque)
    group_counter: int = 0
    last_flow: _FlowSample | None = None
    cumulative_main_net: float = 0.0
    cumulative_peak: float = 0.0
    cumulative_trough: float = 0.0
    last_sequence: int | None = None
    quality: DataQuality = DataQuality.GOOD
    seeded: bool = False


class CapitalWindowEngine:
    """Maintain 1/5/15/30/60 minute windows from one accepted tick stream."""

    def __init__(
        self,
        *,
        windows: tuple[int, ...] = DEFAULT_WINDOWS,
        large_order_threshold: float = 100_000.0,
        split_merge_seconds: float = 3.0,
        split_price_tolerance: float = 0.0015,
        dedupe_capacity: int = 50_000,
        memory_half_life_minutes: int = 30,
    ) -> None:
        if not windows or any(value <= 0 for value in windows):
            raise ValueError("windows must contain positive seconds")
        if large_order_threshold <= 0 or split_merge_seconds < 0:
            raise ValueError("capital thresholds must be valid")
        if split_price_tolerance < 0 or dedupe_capacity <= 0:
            raise ValueError("dedupe parameters must be valid")
        if memory_half_life_minutes <= 0:
            raise ValueError("memory_half_life_minutes must be positive")
        self._windows = tuple(sorted(set(windows)))
        self._threshold = large_order_threshold
        self._merge_seconds = split_merge_seconds
        self._price_tolerance = split_price_tolerance
        self._dedupe_capacity = dedupe_capacity
        self._memory_half_life_minutes = memory_half_life_minutes
        self._states: dict[str, _StockState] = {}
        self._baselines: dict[str, CapitalBaseline] = {}
        self._lock = threading.RLock()

    @property
    def windows(self) -> tuple[int, ...]:
        return self._windows

    def qualifies(self, tick: TickTrade) -> bool:
        return (
            tick.direction in {TickDirection.BUY, TickDirection.SELL}
            and tick.turnover >= self._threshold_for(tick.stock_code)
        )

    def set_baselines(self, baselines: tuple[CapitalBaseline, ...]) -> None:
        with self._lock:
            for baseline in baselines:
                self._baselines[baseline.stock_code] = baseline

    def on_tick(self, tick: TickTrade) -> CapitalFlowUpdate:
        code = tick.stock_code
        with self._lock:
            state = self._state_for(code, tick.exchange_time)
            state.quality = worst_quality(state.quality, tick.quality)
            if tick.sequence is not None:
                state.last_sequence = tick.sequence

            is_directional = tick.direction in {TickDirection.BUY, TickDirection.SELL}
            is_large = self.qualifies(tick)
            if not is_directional:
                self._prune(state, tick.exchange_time)
                return CapitalFlowUpdate(True, False, False, None)

            key = (
                tick.exchange_time.isoformat(),
                round(tick.price, 6),
                tick.volume,
                tick.direction.value,
            )
            if key in state.seen_keys:
                return CapitalFlowUpdate(False, is_large, False, None)
            state.seen_keys.add(key)
            state.seen_order.append(key)
            while len(state.seen_order) > self._dedupe_capacity:
                state.seen_keys.discard(state.seen_order.popleft())
            state.active_samples.append(
                _ActiveSample(
                    exchange_time=tick.exchange_time,
                    amount=tick.turnover,
                    direction=tick.direction,
                )
            )
            if not is_large:
                self._prune(state, tick.exchange_time)
                return CapitalFlowUpdate(True, False, False, None)

            independent = not self._same_split_group(state.last_flow, tick)
            if independent:
                state.group_counter += 1
            group = state.group_counter
            sample = _FlowSample(
                exchange_time=tick.exchange_time,
                price=tick.price,
                amount=tick.turnover,
                direction=tick.direction,
                sequence=tick.sequence,
                event_group=group,
            )
            state.samples.append(sample)
            if independent:
                state.events.append(
                    _FlowEvent(
                        started_at=tick.exchange_time,
                        last_at=tick.exchange_time,
                        amount=tick.turnover,
                        direction=tick.direction,
                        event_group=group,
                    )
                )
            else:
                event = state.events[-1]
                event.last_at = tick.exchange_time
                event.amount += tick.turnover
            state.last_flow = sample
            signed = tick.turnover if tick.direction is TickDirection.BUY else -tick.turnover
            state.cumulative_main_net += signed
            state.cumulative_peak = max(state.cumulative_peak, state.cumulative_main_net)
            state.cumulative_trough = min(state.cumulative_trough, state.cumulative_main_net)
            self._prune(state, tick.exchange_time)
            return CapitalFlowUpdate(True, True, independent, group)

    def seed(self, aggregate: TickAggregate) -> None:
        with self._lock:
            state = self._state_for(aggregate.stock_code, aggregate.as_of)
            state.cumulative_main_net = aggregate.cumulative_main_net
            state.cumulative_peak = aggregate.cumulative_peak
            state.cumulative_trough = aggregate.cumulative_trough
            state.last_sequence = aggregate.last_sequence
            state.quality = worst_quality(state.quality, aggregate.quality)
            state.seeded = True

    def snapshots(self, stock_code: str, as_of: datetime) -> tuple[TickAggregate, ...]:
        with self._lock:
            state = self._states.get(stock_code)
            if state is None or state.trade_date != as_of.date():
                return tuple(self._empty(stock_code, as_of, window) for window in self._windows)
            self._prune(state, as_of)
            samples = tuple(state.samples)
            return tuple(
                self._aggregate(stock_code, as_of, window, samples, state)
                for window in self._windows
            )

    def memory(self, stock_code: str, as_of: datetime) -> CapitalMemory:
        with self._lock:
            state = self._states.get(stock_code)
            if state is None or state.trade_date != as_of.date():
                return self._empty_memory(stock_code, as_of)
            self._prune(state, as_of)
            events = tuple(state.events)
            baseline = self._baselines.get(stock_code)
            threshold = self._threshold_for(stock_code)
            scale = self._flow_scale_for(stock_code)

            half_life_seconds = self._memory_half_life_minutes * 60.0
            decayed_buy_amount = 0.0
            decayed_sell_amount = 0.0
            decayed_buy_events = 0.0
            decayed_sell_events = 0.0
            for event in events:
                age = self._trading_seconds_between(event.last_at, as_of)
                weight = exp(-log(2.0) * age / half_life_seconds)
                if event.direction is TickDirection.BUY:
                    decayed_buy_amount += event.amount * weight
                    decayed_buy_events += weight
                else:
                    decayed_sell_amount += event.amount * weight
                    decayed_sell_events += weight

            recent_events = [
                event
                for event in events
                if self._trading_seconds_between(event.last_at, as_of) <= 900
            ]
            recent_buy_amount = sum(
                event.amount
                for event in recent_events
                if event.direction is TickDirection.BUY
            )
            recent_sell_amount = sum(
                event.amount
                for event in recent_events
                if event.direction is TickDirection.SELL
            )
            recent_buy_events = sum(
                event.direction is TickDirection.BUY for event in recent_events
            )
            recent_sell_events = sum(
                event.direction is TickDirection.SELL for event in recent_events
            )
            decayed_main_net = decayed_buy_amount - decayed_sell_amount
            recent_main_net = recent_buy_amount - recent_sell_amount
            recovery = self._day_recovery_ratio(state)
            memory_state = self._memory_state(
                day_main_net=state.cumulative_main_net,
                day_peak=state.cumulative_peak,
                decayed_buy_amount=decayed_buy_amount,
                decayed_sell_amount=decayed_sell_amount,
                decayed_buy_events=decayed_buy_events,
                decayed_sell_events=decayed_sell_events,
                recent_main_net=recent_main_net,
                recent_buy_events=recent_buy_events,
                recovery=recovery,
                threshold=threshold,
                scale=scale,
            )
            quality = worst_quality(
                state.quality,
                baseline.quality if baseline is not None else DataQuality.DEGRADED,
                DataQuality.DEGRADED if state.seeded and not events else DataQuality.GOOD,
            )
            return CapitalMemory(
                stock_code=stock_code,
                as_of=as_of,
                state=memory_state,
                score=self._memory_score(
                    day_main_net=state.cumulative_main_net,
                    decayed_main_net=decayed_main_net,
                    recent_main_net=recent_main_net,
                    decayed_buy_events=decayed_buy_events,
                    decayed_sell_events=decayed_sell_events,
                    scale=scale,
                ),
                day_main_net=round(state.cumulative_main_net, 4),
                day_peak=round(state.cumulative_peak, 4),
                day_trough=round(state.cumulative_trough, 4),
                day_recovery_ratio=round(recovery, 6),
                decayed_buy_amount=round(decayed_buy_amount, 4),
                decayed_sell_amount=round(decayed_sell_amount, 4),
                decayed_main_net=round(decayed_main_net, 4),
                decayed_buy_events=round(decayed_buy_events, 6),
                decayed_sell_events=round(decayed_sell_events, 6),
                recent_15m_main_net=round(recent_main_net, 4),
                recent_15m_buy_events=recent_buy_events,
                recent_15m_sell_events=recent_sell_events,
                half_life_minutes=self._memory_half_life_minutes,
                quality=quality,
                reason_codes=(f"CAPITAL_MEMORY_{memory_state.value}",),
            )

    def _state_for(self, stock_code: str, as_of: datetime) -> _StockState:
        state = self._states.get(stock_code)
        if state is None or state.trade_date != as_of.date():
            state = _StockState(trade_date=as_of.date())
            self._states[stock_code] = state
        return state

    def _same_split_group(self, previous: _FlowSample | None, tick: TickTrade) -> bool:
        if previous is None or previous.direction is not tick.direction:
            return False
        elapsed = (tick.exchange_time - previous.exchange_time).total_seconds()
        if elapsed < 0 or elapsed > self._merge_seconds:
            return False
        if abs(tick.price / previous.price - 1.0) > self._price_tolerance:
            return False
        if (
            previous.sequence is not None
            and tick.sequence is not None
            and tick.sequence - previous.sequence > 3
        ):
            return False
        return True

    def _prune(self, state: _StockState, as_of: datetime) -> None:
        cutoff = as_of.timestamp() - self._windows[-1]
        while state.samples and state.samples[0].exchange_time.timestamp() < cutoff:
            state.samples.popleft()
        while (
            state.active_samples
            and state.active_samples[0].exchange_time.timestamp() < cutoff
        ):
            state.active_samples.popleft()

    def _aggregate(
        self,
        stock_code: str,
        as_of: datetime,
        window: int,
        samples: tuple[_FlowSample, ...],
        state: _StockState,
    ) -> TickAggregate:
        cutoff = as_of.timestamp() - window
        selected = [sample for sample in samples if sample.exchange_time.timestamp() >= cutoff]
        baseline = self._baselines.get(stock_code)
        buys = [sample for sample in selected if sample.direction is TickDirection.BUY]
        sells = [sample for sample in selected if sample.direction is TickDirection.SELL]
        buy_groups = self._event_times(buys)
        sell_groups = self._event_times(sells)
        buy_amount = sum(sample.amount for sample in buys)
        sell_amount = sum(sample.amount for sample in sells)
        total = buy_amount + sell_amount
        active_samples = [
            sample
            for sample in state.active_samples
            if sample.exchange_time.timestamp() >= cutoff
        ]
        active_buy_amount = sum(
            sample.amount
            for sample in active_samples
            if sample.direction is TickDirection.BUY
        )
        active_sell_amount = sum(
            sample.amount
            for sample in active_samples
            if sample.direction is TickDirection.SELL
        )
        active_total = active_buy_amount + active_sell_amount
        return TickAggregate(
            stock_code=stock_code,
            as_of=as_of,
            window_seconds=window,
            buy_amount=round(buy_amount, 4),
            sell_amount=round(sell_amount, 4),
            main_net=round(buy_amount - sell_amount, 4),
            big_buy_count=len(buys),
            big_sell_count=len(sells),
            independent_buy_events=len(buy_groups),
            independent_sell_events=len(sell_groups),
            buy_sell_ratio=round(buy_amount / total, 6) if total > 0 else None,
            cumulative_main_net=round(state.cumulative_main_net, 4),
            cumulative_peak=round(state.cumulative_peak, 4),
            cumulative_trough=round(state.cumulative_trough, 4),
            last_sequence=state.last_sequence,
            sample_count=len(selected),
            quality=worst_quality(
                state.quality,
                baseline.quality if baseline is not None else DataQuality.DEGRADED,
            ),
            large_order_threshold=self._threshold_for(stock_code),
            flow_scale=self._flow_scale_for(stock_code),
            first_independent_buy_at=buy_groups[0] if buy_groups else None,
            last_independent_buy_at=buy_groups[-1] if buy_groups else None,
            first_independent_sell_at=sell_groups[0] if sell_groups else None,
            last_independent_sell_at=sell_groups[-1] if sell_groups else None,
            active_buy_amount=round(active_buy_amount, 4),
            active_sell_amount=round(active_sell_amount, 4),
            active_net=round(active_buy_amount - active_sell_amount, 4),
            active_buy_ratio=(
                round(active_buy_amount / active_total, 6)
                if active_total > 0
                else None
            ),
        )

    def _empty(self, stock_code: str, as_of: datetime, window: int) -> TickAggregate:
        return TickAggregate(
            stock_code=stock_code,
            as_of=as_of,
            window_seconds=window,
            buy_amount=0.0,
            sell_amount=0.0,
            main_net=0.0,
            big_buy_count=0,
            big_sell_count=0,
            independent_buy_events=0,
            independent_sell_events=0,
            buy_sell_ratio=None,
            cumulative_main_net=0.0,
            cumulative_peak=0.0,
            cumulative_trough=0.0,
            last_sequence=None,
            sample_count=0,
            quality=DataQuality.INVALID,
            large_order_threshold=self._threshold_for(stock_code),
            flow_scale=self._flow_scale_for(stock_code),
        )

    def _empty_memory(self, stock_code: str, as_of: datetime) -> CapitalMemory:
        return CapitalMemory(
            stock_code=stock_code,
            as_of=as_of,
            state=CapitalMemoryState.NEUTRAL,
            score=50.0,
            day_main_net=0.0,
            day_peak=0.0,
            day_trough=0.0,
            day_recovery_ratio=0.5,
            decayed_buy_amount=0.0,
            decayed_sell_amount=0.0,
            decayed_main_net=0.0,
            decayed_buy_events=0.0,
            decayed_sell_events=0.0,
            recent_15m_main_net=0.0,
            recent_15m_buy_events=0,
            recent_15m_sell_events=0,
            half_life_minutes=self._memory_half_life_minutes,
            quality=DataQuality.INVALID,
            reason_codes=("CAPITAL_MEMORY_EMPTY",),
        )

    @staticmethod
    def _day_recovery_ratio(state: _StockState) -> float:
        path = state.cumulative_peak - state.cumulative_trough
        if path <= 0:
            return 1.0 if state.cumulative_main_net > 0 else 0.5
        return max(
            0.0,
            min(1.0, (state.cumulative_main_net - state.cumulative_trough) / path),
        )

    @staticmethod
    def _memory_state(
        *,
        day_main_net: float,
        day_peak: float,
        decayed_buy_amount: float,
        decayed_sell_amount: float,
        decayed_buy_events: float,
        decayed_sell_events: float,
        recent_main_net: float,
        recent_buy_events: int,
        recovery: float,
        threshold: float,
        scale: float,
    ) -> CapitalMemoryState:
        decayed_net = decayed_buy_amount - decayed_sell_amount
        base = max(3.0 * threshold, scale)
        decayed_total = decayed_buy_amount + decayed_sell_amount
        buy_ratio = decayed_buy_amount / decayed_total if decayed_total > 0 else 0.5
        if (
            decayed_net <= -max(threshold, 0.75 * scale)
            and decayed_sell_events >= 1.0
        ):
            return CapitalMemoryState.DISTRIBUTING
        if (
            day_main_net < 0
            and decayed_net >= base
            and recent_main_net > 0
            and recent_buy_events >= 1
            and recovery >= 0.50
        ):
            return CapitalMemoryState.REVERSING
        if (
            day_main_net >= base
            and decayed_net >= base
            and recent_buy_events >= 2
            and decayed_buy_events > decayed_sell_events
        ):
            return CapitalMemoryState.ACCUMULATING
        if (
            decayed_net >= max(threshold, 0.75 * scale)
            and recent_buy_events >= 1
            and buy_ratio >= 0.65
        ):
            return CapitalMemoryState.ABSORBING
        if day_peak >= base and decayed_net < 0.25 * base:
            return CapitalMemoryState.DECAYING
        return CapitalMemoryState.NEUTRAL

    @staticmethod
    def _memory_score(
        *,
        day_main_net: float,
        decayed_main_net: float,
        recent_main_net: float,
        decayed_buy_events: float,
        decayed_sell_events: float,
        scale: float,
    ) -> float:
        normalizer = max(scale, 1.0)
        day_score = 50.0 + 50.0 * tanh(day_main_net / (3.0 * normalizer))
        event_total = decayed_buy_events + decayed_sell_events
        event_balance = (
            (decayed_buy_events - decayed_sell_events) / event_total
            if event_total > 0
            else 0.0
        )
        decayed_score = (
            50.0 + 40.0 * tanh(decayed_main_net / (2.0 * normalizer))
            + 10.0 * event_balance
        )
        recent_score = 50.0 + 50.0 * tanh(recent_main_net / normalizer)
        score = day_score * 0.25 + decayed_score * 0.45 + recent_score * 0.30
        return round(max(0.0, min(100.0, score)), 4)

    @staticmethod
    def _trading_seconds_between(start: datetime, end: datetime) -> float:
        if end <= start:
            return 0.0
        if start.date() != end.date():
            return max(0.0, (end - start).total_seconds())
        sessions = ((9, 30, 12, 0), (13, 0, 16, 0))
        seconds = 0.0
        for start_hour, start_minute, end_hour, end_minute in sessions:
            session_start = start.replace(
                hour=start_hour, minute=start_minute, second=0, microsecond=0
            )
            session_end = start.replace(
                hour=end_hour, minute=end_minute, second=0, microsecond=0
            )
            overlap_start = max(start, session_start)
            overlap_end = min(end, session_end)
            if overlap_end > overlap_start:
                seconds += (overlap_end - overlap_start).total_seconds()
        return seconds

    @staticmethod
    def _event_times(samples: list[_FlowSample]) -> tuple[datetime, ...]:
        first_by_group: dict[int, datetime] = {}
        for sample in samples:
            first_by_group.setdefault(sample.event_group, sample.exchange_time)
        return tuple(sorted(first_by_group.values()))

    def _threshold_for(self, stock_code: str) -> float:
        baseline = self._baselines.get(stock_code)
        return baseline.large_order_threshold if baseline is not None else self._threshold

    def _flow_scale_for(self, stock_code: str) -> float:
        baseline = self._baselines.get(stock_code)
        return baseline.flow_scale if baseline is not None else self._threshold
