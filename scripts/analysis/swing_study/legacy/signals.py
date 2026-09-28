"""Frozen timing alternatives; all gates use information available at the signal."""
import numpy as np
from scripts.analysis.minute_entry_study.models import INDEX, N, rolling_sum
from ..models import ExitRule, Signal
from .models import Episode, Fold, Policy, Study


def policies(route: str) -> list[Policy]:
    return [Policy(route, 'first'), Policy(route, 'one', .55), Policy(route, 'one', .7), Policy(route, 'formal')]


def exits() -> list[ExitRule]:
    return [ExitRule(d, a, r) for d in (1, 3, 5) for a in (1., 1.5) for r in (2., 3.)]


def folds() -> list[Fold]:
    return [Fold('F1', 19, 20, 29), Fold('F2', 29, 30, 39), Fold('F3', 39, 40, 51)]


def route_eligible(episode: Episode, route: str) -> bool:
    bg, first = episode.opportunity.background, episode.first
    if not bg.valid or not np.isfinite(bg.atr) or bg.atr <= 0:
        return False
    if route == 'all':
        return True
    if route == 'low':
        position = (first.price-bg.low20)/(bg.high20-bg.low20) if bg.high20 > bg.low20 else np.nan
        return -.1 <= position <= .5
    if route == 'flow':
        return first.buy_ratio >= .55 and first.window_net > 0
    raise ValueError(route)


def signal_for(episode: Episode, policy: Policy) -> Signal | None:
    if not route_eligible(episode, policy.route):
        return None
    o, first = episode.opportunity, episode.first
    t, bg = o.tape, o.background
    point = None
    if policy.timing == 'first':
        point = first.index
    elif policy.timing == 'formal':
        matching = [e.index for e in episode.events if e.stage == 'CONFIRMED']
        point = min(matching) if matching else None
    elif policy.timing == 'one':
        idx, f, p = np.arange(N), t.features, t.mean
        prior = np.r_[np.nan, p[:-1]]
        mask = ((idx >= first.index) & (idx < episode.end_index) & (idx <= INDEX[870])
                & f['coverage5'] & (f['ratio5'] >= policy.ratio) & (p > prior)
                & (f['vwap_distance'] >= 0) & (f['vwap_distance'] <= .025)
                & (f['anchor_return'] <= .04) & (rolling_sum(f['notional'], 5) >= 100000))
        matches = np.flatnonzero(mask)
        point = int(matches[0]) if len(matches) else None
    else:
        raise ValueError(policy.timing)
    if point is None or point >= episode.end_index or point > INDEX[870]:
        return None
    return Signal(first.code, o.day_index, o.day_index*N+point, o.theme, bg.atr,
                  first.price, o.day_index*N+first.index)


def signals(study: Study, policy: Policy) -> list[Signal]:
    return sorted((s for e in study.episodes if (s := signal_for(e, policy)) is not None),
                  key=lambda s: (s.index, s.code, s.gate))


def training_score(stats: dict) -> float | None:
    from ..metrics import score
    if stats['closed'] < 25 or stats['active_days'] < 8 or stats['unresolved'] > .1*stats['filled']:
        return None
    return score(stats)


def choose(rows: list[dict], route: str | None = None) -> dict | None:
    eligible = [r for r in rows if r['score'] is not None and (route is None or r['policy']['route'] == route)]
    return max(eligible, key=lambda r: (r['score'], r['stats']['closed'], r['key'])) if eligible else None
