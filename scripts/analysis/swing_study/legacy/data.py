"""Point-in-time legacy episode adapter and historical-price normalization."""
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path
import numpy as np

from scripts.analysis.minute_entry_study.models import HK, INDEX, N, WALL, Tape, build_features, stamp, wall_minute
from ..data import background, theme_of
from ..models import Daily, Market, Opportunity, StockPath
from .models import Episode, LegacyEvent, Study


TERMINAL = {'INVALIDATED', 'EXPIRED', 'REJECTED', 'TRAIL_EXIT', 'WATCH_TRAIL_EXIT'}


def event_time(epoch: float, text: str, created: str) -> tuple[datetime, float]:
    emitted = datetime.fromtimestamp(epoch, timezone.utc).astimezone(HK)
    if abs((stamp(text)-emitted).total_seconds()) > 2:
        raise ValueError('epoch/local timestamp disagreement')
    persisted = datetime.fromisoformat(created)
    if persisted.tzinfo is None:
        persisted = persisted.replace(tzinfo=timezone.utc)
    persisted = persisted.astimezone(HK)
    lag = (persisted-emitted).total_seconds()
    if lag < -2:
        raise ValueError('persistence precedes event')
    return max(emitted, persisted), lag


def normalize_events(rows: list, days: list[str], counts: Counter[str]) -> tuple[list[LegacyEvent], list[float]]:
    result, lags = [], []
    seen: set[int] = set()
    for eid, day, code, source, action, text, created, detail in rows:
        if eid in seen:
            raise ValueError('duplicate event id')
        seen.add(eid)
        counts['raw_events'] += 1
        if source != 'capital_trend' or day not in days:
            counts['outside_source_or_calendar'] += 1
            continue
        try:
            when, lag = event_time(float(detail['timestamp']), text, created)
            price = float(detail.get('last_price') or 0)
        except (ValueError, TypeError, KeyError, OverflowError):
            counts['invalid_timestamp_or_price'] += 1
            continue
        if when.date().isoformat() != day:
            counts['delayed_into_another_day'] += 1
            continue
        if not np.isfinite(price) or price <= 0:
            counts['invalid_timestamp_or_price'] += 1
            continue
        lags.append(lag)
        wall = when.hour*60+when.minute
        stage = str(detail.get('inflow_stage') or '')
        if wall not in INDEX and stage == 'FIRST':
            counts['first_outside_regular_session'] += 1
            continue
        result.append(LegacyEvent(int(eid), code, day, when, bisect_left(WALL, wall), stage,
            str(detail.get('direction') or ''), detail.get('is_large_inflow') is True,
            price, float(detail.get('inflow_first_price') or 0), int(detail.get('inflow_sequence_no') or 0),
            str(detail.get('plate_name') or ''), action, float(detail.get('window_buy_ratio') or 0),
            float(detail.get('window_main_net') or 0), detail.get('legacy_observe_only') is True))
    return sorted(result, key=lambda e: (e.when, e.event_id)), lags


def make_episodes(events: list[LegacyEvent], market: Market, counts: Counter[str]) -> list[Episode]:
    grouped: dict[tuple[str, str], list[LegacyEvent]] = defaultdict(list)
    for e in events:
        grouped[(e.day, e.code)].append(e)
    result = []
    for (day, code), series in sorted(grouped.items()):
        active: LegacyEvent | None = None
        following: list[LegacyEvent] = []

        def finish(end: int) -> None:
            if active is None:
                return
            d = market.days.index(day)
            path = market.paths[code]
            bg = path.backgrounds[d]
            sl = slice(d*N, (d+1)*N)
            tape = Tape(day, code, '', path.mean[sl], path.high[sl], path.low[sl], path.buy[sl],
                        path.sell[sl], path.volume[sl], active.index, active.price, bg.prior_close,
                        bg.low20, bg.high20, bg.ma20, ())
            build_features(tape)
            opportunity = Opportunity(d, theme_of(active.sector), active.sector, tape, bg, None, None)
            result.append(Episode(active, opportunity, tuple(following), end))
            counts['thematic_first_episodes'] += 1
            counts['episodes_invalid_daily_background'] += not bg.valid
            counts['episodes_observe_only'] += active.observe_only

        for e in series:
            if e.stage == 'FIRST':
                finish(e.index)
                active, following = None, []
                if e.direction == 'RISING' and e.large_inflow and e.sequence == 1 and theme_of(e.sector):
                    active = e
                else:
                    counts['nonqualifying_or_unthemed_first'] += 1
            elif active is not None:
                if e.stage in TERMINAL:
                    following.append(e)
                    finish(e.index)
                    active, following = None, []
                elif e.stage == 'CONFIRMED':
                    if (e.direction == 'RISING' and e.large_inflow and e.sequence >= 2
                            and abs(e.first_price/active.price-1) <= .001):
                        following.append(e)
                    else:
                        counts['confirmation_anchor_mismatch'] += 1
                else:
                    following.append(e)
            elif e.stage == 'CONFIRMED' and theme_of(e.sector):
                counts['themed_confirmation_without_known_first'] += 1
        finish(N)
    return sorted(result, key=lambda e: (e.first.when, e.first.event_id))


def load(path: Path) -> Study:
    raw = path.read_bytes()
    data = json.loads(gzip.decompress(raw))
    if data['kind'] != 'LEGACY_SWING_DATA':
        raise ValueError('wrong input kind')
    start, end = date(2026, 7, 14), date(2026, 9, 24)
    days = [(start+timedelta(days=d)).isoformat() for d in range((end-start).days)
            if (start+timedelta(days=d)).weekday() < 5]
    archives = {r[0]: r[1] for r in data['archives']}
    if len(days) != 52 or any(archives.get(day) != 2 for day in days):
        raise ValueError('frozen 52-session versioned calendar not available')
    counts: Counter[str] = Counter()
    events, lags = normalize_events(data['events'], days, counts)
    codes = sorted({e.code for e in events})
    day_map = {day: i for i, day in enumerate(days)}
    groups: dict[tuple[str, str], list[tuple]] = defaultdict(list)
    for code, day, close, high, low, volume, turnover, created, eid in data['daily']:
        if (any(v is None or not np.isfinite(v) for v in (close, high, low))
                or low <= 0 or high < low or close <= 0):
            counts['invalid_daily_rows'] += 1
            continue
        groups[(code, day[:10])].append((close, high, low, volume or 0, turnover or 0))
        counts['daily_downloaded_after_date'] += created[:10] > day[:10]
    histories: dict[str, list[Daily]] = defaultdict(list)
    for (code, day), versions in sorted(groups.items()):
        last = versions[-1]
        price_conflict = any(max(abs(v[i]/last[i]-1) for i in range(3)) > .005 for v in versions)
        volume_conflict = any(abs(v[3]-last[3]) > max(1, last[3])*.01 for v in versions)
        turnover_conflict = any(abs(v[4]-last[4]) > max(1, last[4])*.01 for v in versions)
        conflict = price_conflict or volume_conflict or turnover_conflict
        counts['duplicate_daily_extra_rows'] += len(versions)-1
        counts['conflicting_daily_stock_dates'] += conflict
        histories[code].append(Daily(day, *last[:3], last[4], conflict))
    paths = {code: StockPath(code, *[np.full(len(days)*N, np.nan) for _ in range(6)],
                            [background(histories[code], day) for day in days]) for code in codes}
    seen: set[tuple[str, int]] = set()
    for code, day, minute, mean, high, low, buy, sell, volume in data['minutes']:
        idx = INDEX.get(wall_minute(minute))
        if idx is None or code not in paths or day not in day_map:
            continue
        values = (mean, high, low, volume or 0, buy or 0, sell or 0)
        if (any(v is None or not np.isfinite(v) for v in values) or low <= 0 or high < low
                or not low-1e-8 <= mean <= high+1e-8 or min(values[3:]) < 0):
            counts['invalid_minute_rows'] += 1
            continue
        point = day_map[day]*N+idx
        if (code, point) in seen:
            raise ValueError('duplicate minute')
        seen.add((code, point))
        p = paths[code]
        for array, value in zip((p.mean, p.high, p.low, p.volume, p.buy, p.sell), values):
            array[point] = value
    counts['valid_regular_minutes'] = len(seen)
    market = Market(days, paths, [], hashlib.sha256(raw).hexdigest(), {}, {})
    episodes = make_episodes(events, market, counts)
    market.opportunities = [e.opportunity for e in episodes]
    market.audit = dict(counts)
    return Study(market, episodes, events, dict(counts), dict(Counter(e.stage for e in events)), lags)
