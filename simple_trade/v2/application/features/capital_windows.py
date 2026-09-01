"""Incremental big-order flow windows with split-order event grouping."""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
import threading

from ...domain.enums import DataQuality, TickDirection
from ...domain.features import CapitalBaseline
from ...domain.market import TickAggregate, TickTrade
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


@dataclass(slots=True)
class _StockState:
    trade_date: object
    samples: deque[_FlowSample] = field(default_factory=deque)
    seen_keys: set[tuple[object, ...]] = field(default_factory=set)
    seen_order: deque[tuple[object, ...]] = field(default_factory=deque)
    group_counter: int = 0
    last_flow: _FlowSample | None = None
    cumulative_main_net: float = 0.0
    cumulative_peak: float = 0.0
    cumulative_trough: float = 0.0
    last_sequence: int | None = None
    quality: DataQuality = DataQuality.GOOD


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
    ) -> None:
        if not windows or any(value <= 0 for value in windows):
            raise ValueError("windows must contain positive seconds")
        if large_order_threshold <= 0 or split_merge_seconds < 0:
            raise ValueError("capital thresholds must be valid")
        if split_price_tolerance < 0 or dedupe_capacity <= 0:
            raise ValueError("dedupe parameters must be valid")
        self._windows = tuple(sorted(set(windows)))
        self._threshold = large_order_threshold
        self._merge_seconds = split_merge_seconds
        self._price_tolerance = split_price_tolerance
        self._dedupe_capacity = dedupe_capacity
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
            if not self.qualifies(tick):
                self._prune(state, tick.exchange_time)
                return CapitalFlowUpdate(True, False, False, None)

            key = (
                tick.exchange_time.isoformat(),
                round(tick.price, 6),
                tick.volume,
                tick.direction.value,
                tick.sequence,
            )
            if key in state.seen_keys:
                return CapitalFlowUpdate(False, True, False, None)
            state.seen_keys.add(key)
            state.seen_order.append(key)
            while len(state.seen_order) > self._dedupe_capacity:
                state.seen_keys.discard(state.seen_order.popleft())

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
