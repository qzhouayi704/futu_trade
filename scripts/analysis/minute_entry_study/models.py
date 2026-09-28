"""Typed research records and causal feature construction."""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path

import numpy as np


HK = timezone(timedelta(hours=8))
WALL = tuple(range(570, 720)) + tuple(range(780, 960))
INDEX = {wall: index for index, wall in enumerate(WALL)}
N = len(WALL)


def wall_minute(text: str) -> int:
    return int(text[:2]) * 60 + int(text[3:5])


def stamp(text: str) -> datetime:
    parsed = datetime.fromisoformat(text)
    return parsed.replace(tzinfo=HK) if parsed.tzinfo is None else parsed.astimezone(HK)


def available_index(exchange: str, received: str) -> int:
    moment = max(stamp(exchange), stamp(received))
    # Event evidence is usable by the end of this minute, never beforehand.
    return bisect_left(WALL, moment.hour * 60 + moment.minute)


@dataclass(frozen=True)
class Event:
    kind: str
    index: int
    price: float
    state: str
    eligible: bool
    reason: str
    version: str


@dataclass
class Tape:
    day: str
    code: str
    name: str
    mean: np.ndarray
    high: np.ndarray
    low: np.ndarray
    buy: np.ndarray
    sell: np.ndarray
    volume: np.ndarray
    gate: int
    anchor: float
    prev_close: float
    prior_low: float
    prior_high: float
    ma20: float
    events: tuple[Event, ...]
    features: dict[str, np.ndarray] = field(default_factory=dict)


@dataclass(frozen=True)
class Rule:
    family: str
    window: int = 5
    ratio: float = .6
    sustain: int = 2
    extension: float = .02
    position: float = .5
    breadth: float = 0
    stage_weight: float = 1

    @property
    def key(self) -> str:
        return (f'{self.family}-w{self.window}-b{self.ratio:g}-n{self.sustain}'
                f'-x{self.extension:g}-p{self.position:g}-m{self.breadth:g}-a{self.stage_weight:g}')


@dataclass(frozen=True)
class Exit:
    stop: float = .02
    target: float = .04
    hold: int = 60
    trail: float = 0

    @property
    def key(self) -> str:
        return f's{self.stop:g}-t{self.target:g}-h{self.hold}-r{self.trail:g}'


@dataclass(frozen=True)
class Trade:
    day: str
    code: str
    signal: int
    entry: int
    exit: int | None
    entry_price: float
    exit_price: float | None
    net: float | None
    gross: float | None
    reason: str
    gap_minutes: int
    weight: float
    added: bool
    entry_vs_anchor: float
    signal_delay: int


@dataclass
class Dataset:
    tapes: list[Tape]
    days: list[str]
    sha256: str
    coverage: dict[str, int]
    versions: dict[str, int]


def rolling_sum(array: np.ndarray, window: int) -> np.ndarray:
    cumulative = np.r_[0., np.cumsum(np.nan_to_num(array))]
    result = cumulative[1:].copy()
    result[window:] -= cumulative[1:-window]
    return result


def prior_max(array: np.ndarray, window: int) -> np.ndarray:
    result = np.full(len(array), np.nan)
    for index in range(window, len(array)):
        segment = array[index-window:index]
        if np.isfinite(segment).all():
            result[index] = max(segment)
    return result


def build_features(tape: Tape) -> None:
    p = tape.mean
    valid = np.isfinite(p) & (p > 0)
    f = tape.features
    f['valid'] = valid
    weighted = np.cumsum(np.where(valid, p * tape.volume, 0))
    volumes = np.cumsum(np.where(valid, tape.volume, 0))
    f['vwap_proxy'] = np.divide(weighted, volumes, out=np.full(N, np.nan), where=volumes > 0)
    f['vwap_distance'] = p / f['vwap_proxy'] - 1
    f['anchor_return'] = p / tape.anchor - 1
    f['position'] = ((p - tape.prior_low) / (tape.prior_high - tape.prior_low)
                     if tape.prior_high > tape.prior_low else np.full(N, np.nan))
    f['notional'] = p * tape.volume
    f['buy_minute'] = np.divide(tape.buy, tape.buy+tape.sell, out=np.full(N, np.nan), where=tape.buy+tape.sell > 0)
    for window in (3, 5, 10):
        buy, sell = rolling_sum(tape.buy, window), rolling_sum(tape.sell, window)
        f[f'ratio{window}'] = np.divide(buy, buy+sell, out=np.full(N, np.nan), where=buy+sell > 0)
        f[f'prior_high{window}'] = prior_max(tape.high, window)
        f[f'coverage{window}'] = rolling_sum(valid.astype(float), window) >= window
        f[f'net{window}'] = buy-sell
    for sustain in (2, 3):
        f[f'sustain{sustain}'] = rolling_sum((f['buy_minute'] >= .5).astype(float), sustain) >= sustain


def load(path: Path) -> Dataset:
    raw = path.read_bytes()
    data = json.loads(gzip.decompress(raw))
    counts: Counter[str] = Counter()
    versions: Counter[str] = Counter()
    grouped: dict[tuple[str, str], list[Event]] = defaultdict(list)
    initial_prev: dict[tuple[str, str], float] = {}
    for _, kind, code, exchange, received, state, reason, version, eligible, fs, _ in data['events']:
        moment = max(stamp(exchange), stamp(received))
        if moment.date() != stamp(exchange).date():
            counts['cross_day_delayed_events'] += 1
            continue
        key = (moment.date().isoformat(), code)
        index = available_index(exchange, received)
        if index >= N or WALL[index] != moment.hour * 60 + moment.minute:
            counts['out_of_session_events'] += 1
            continue
        quote = fs.get('quote') or {}
        grouped[key].append(Event(kind, index, float(quote['last_price']), state, bool(eligible), reason, version))
        initial_prev.setdefault(key, float(quote.get('prev_close') or 0))
        versions[version] += 1
    histories: dict[str, dict[str, tuple[float, ...]]] = defaultdict(dict)
    for code, day, close, high, low, turnover in data['daily']:
        if close and high and low:
            histories[code][day] = (float(close), float(high), float(low), float(turnover or 0))
    rows_by_key: dict[tuple[str, str], list[list]] = defaultdict(list)
    for code, day, *row in data['minutes']:
        rows_by_key[(day, code)].append(row)
    tapes = []
    for key, events in sorted(grouped.items()):
        day, code = key
        events.sort(key=lambda event: event.index)
        candidates = [e for e in events if e.state in {'SETUP','WATCHING','CONFIRMED'}
                      and e.kind in {'CANDIDATE_ENTERED','CANDIDATE_UPDATED','BUY_CONFIRMED'}]
        if not candidates:
            continue
        counts['candidate_stock_days'] += 1
        first = candidates[0]
        arrays = [np.full(N, np.nan) for _ in range(6)]
        for minute, mean, high, low, buy, sell, volume in rows_by_key.get(key, []):
            idx = INDEX.get(wall_minute(minute))
            values = (mean, high, low, buy or 0, sell or 0, volume or 0)
            if idx is None:
                continue
            if (not all(v is not None and math.isfinite(float(v)) for v in values)
                    or low <= 0 or high < low or mean < low-1e-8 or mean > high+1e-8):
                counts['invalid_minute_rows'] += 1
                continue
            values = (min(high,max(low,mean)),high,low,buy or 0,sell or 0,volume or 0)
            for array, value in zip(arrays, values):
                array[idx] = value
        if not np.isfinite(arrays[0][first.index:]).any():
            counts['no_post_candidate_minutes'] += 1
            continue
        previous = [row for dt, row in sorted(histories[code].items()) if dt < day][-20:]
        prior_low = min((r[2] for r in previous), default=float('nan'))
        prior_high = max((r[1] for r in previous), default=float('nan'))
        ma20 = sum(r[0] for r in previous)/len(previous) if previous else float('nan')
        tape = Tape(day, code, data['names'].get(code,''), *arrays, first.index, first.price,
                    initial_prev.get(key, 0), prior_low, prior_high, ma20, tuple(events))
        build_features(tape)
        tapes.append(tape)
        coverage = float(np.isfinite(tape.mean[first.index:]).mean())
        counts['post_gate_coverage_ge90pct'] += coverage >= .9
        counts['no_1550_1559_bar'] += not np.isfinite(tape.mean[-10:]).any()
    days = sorted({t.day for t in tapes})
    for day in days:
        peers = [t for t in tapes if t.day == day]
        up, total = np.zeros(N), np.zeros(N)
        for tape in peers:
            # Only already discovered stocks with an observed current minute.
            valid = tape.features['valid'] & (np.arange(N) >= tape.gate)
            if tape.prev_close > 0:
                total += valid
                up += valid & (tape.mean > tape.prev_close)
        breadth = np.divide(up, total, out=np.full(N, np.nan), where=total >= 20)
        for tape in peers:
            tape.features['breadth'] = breadth
    counts['usable_stock_days'] = len(tapes)
    counts['regular_minute_rows'] = sum(int(np.isfinite(t.mean).sum()) for t in tapes)
    return Dataset(tapes, days, hashlib.sha256(raw).hexdigest(), dict(counts), dict(versions))
