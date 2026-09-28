"""Rule grid fixed before reading validation returns."""
from itertools import product

import numpy as np

from .models import N, INDEX, Rule, Tape


def choices() -> list[Rule]:
    rules = [Rule(family) for family in ('recorded_confirmed','recorded_shadow','recorded_watching','candidate_immediate')]
    for w, ratio, extension, breadth in product((3,5,10), (.5,.6,.7), (.015,.03), (0,.4)):
        rules.append(Rule('breakout', w, ratio, 2, extension, .5, breadth))
    for w, ratio, position, extension, breadth in product((3,5), (.5,.6,.7), (.3,.5), (.01,.02), (0,.4)):
        rules.append(Rule('low_reclaim', w, ratio, 2, extension, position, breadth))
    for w, ratio, sustain, extension, breadth in product((3,5,10), (.55,.65,.75), (2,3), (.015,.03), (0,.4)):
        rules.append(Rule('sustained_flow', w, ratio, sustain, extension, .5, breadth))
    return rules


def signal_index(tape: Tape, rule: Rule) -> int | None:
    if rule.family.startswith('recorded_'):
        matching = [event.index for event in tape.events if
                    (rule.family == 'recorded_confirmed' and event.kind == 'BUY_CONFIRMED' and event.eligible)
                    or (rule.family == 'recorded_shadow' and event.kind == 'BUY_CONFIRMED')
                    or (rule.family == 'recorded_watching' and event.state in {'WATCHING','CONFIRMED'}
                        and event.kind in {'CANDIDATE_ENTERED','CANDIDATE_UPDATED','BUY_CONFIRMED'})]
        return min(matching) if matching else None
    if rule.family == 'candidate_immediate':
        return tape.gate
    f, p = tape.features, tape.mean
    idx = np.arange(N)
    mask = ((idx >= tape.gate) & (idx <= INDEX[870]) & f['valid'] & f[f'coverage{rule.window}']
            & (f[f'ratio{rule.window}'] >= rule.ratio)
            & (f['vwap_distance'] >= -.003) & (f['vwap_distance'] <= rule.extension)
            & (f['anchor_return'] <= rule.extension)
            & (p >= 1))
    # All rules require already observed recent turnover; no full-day liquidity screen.
    from .models import rolling_sum
    mask &= rolling_sum(f['notional'], 5) >= 100000
    if rule.breadth:
        mask &= f['breadth'] >= rule.breadth
    if rule.family == 'breakout':
        mask &= (p >= f[f'prior_high{rule.window}'] * 1.0005)
    elif rule.family == 'low_reclaim':
        prior = np.r_[np.nan, p[:-1]]
        mask &= (f['position'] <= rule.position) & (p > prior)
        mask &= (f['vwap_distance'] >= 0) & (idx <= INDEX[690])
    elif rule.family == 'sustained_flow':
        mask &= f[f'sustain{rule.sustain}'] & (f[f'net{rule.window}'] > 0)
        prior = np.r_[np.full(rule.window, np.nan), p[:-rule.window]]
        mask &= p >= prior * 1.001
    else:
        raise ValueError(rule.family)
    possible = np.flatnonzero(mask)
    return int(possible[0]) if len(possible) else None
