"""Frozen small hypothesis grid; background precedes the signal date."""
from itertools import product
import numpy as np

from scripts.analysis.minute_entry_study.models import INDEX, N, rolling_sum
from .models import EntryRule, ExitRule, Market, Opportunity, Signal


def entry_grid() -> list[EntryRule]:
    rules = [EntryRule('confirmed'),EntryRule('immediate')]
    rules += [EntryRule('low',ratio,pos,1,structure)
              for ratio,pos,structure in product((.55,.7),(.3,.5),(False,True))]
    rules += [EntryRule('flow',ratio,.5,volume,structure)
              for ratio,volume,structure in product((.55,.7),(1,1.5),(False,True))]
    return rules


def exit_grid() -> list[ExitRule]:
    return [ExitRule(days,atr,reward,protect) for days,atr,reward,protect in
            product((1,3,5),(1,1.5),(2,3),(False,True))]


def signal_for(opportunity: Opportunity, rule: EntryRule) -> Signal | None:
    o, t, bg = opportunity,opportunity.tape,opportunity.background
    # Keep the same daily-data eligibility for controls and both research routes.
    if not bg.valid or not np.isfinite(bg.atr) or bg.atr <= 0:
        return None
    point = None
    if rule.family == 'immediate':
        point = t.gate
    elif rule.family == 'confirmed':
        matches = [e.index for e in t.events if e.kind == 'BUY_CONFIRMED' and e.eligible]
        point = min(matches) if matches else None
    else:
        f,p = t.features,t.mean
        idx = np.arange(N)
        mask = ((idx >= t.gate) & (idx <= INDEX[870]) & f['coverage5'] & (p >= 1)
                & (f['ratio5'] >= rule.ratio) & (f['vwap_distance'] >= 0)
                & (f['vwap_distance'] <= .025) & (f['anchor_return'] <= .04)
                & (rolling_sum(f['notional'],5) >= 100000))
        if rule.family == 'low':
            prior = np.r_[np.nan,p[:-1]]
            mask &= (f['position'] <= rule.position) & (f['position'] >= -.1) & (p > prior)
            if rule.structure and not bg.stabilizing:
                return None
        elif rule.family == 'flow':
            prior = np.r_[np.full(5,np.nan),p[:-5]]
            # Time-normalized DAILY turnover proxy, not a historical intraday profile.
            expected = bg.mean_turnover*(idx+1)/N
            cumulative = np.cumsum(np.nan_to_num(f['notional']))
            mask &= f['sustain3'] & (f['net5'] > 0) & (p >= prior*1.001)
            mask &= cumulative >= expected*rule.volume_multiple
            if rule.structure:
                mask &= (p >= bg.ma5) & (bg.ma5 >= bg.ma20)
        else:
            raise ValueError(rule.family)
        points = np.flatnonzero(mask)
        point = int(points[0]) if len(points) else None
    if point is None or point > INDEX[870]:
        return None
    return Signal(t.code,o.day_index,o.day_index*N+point,o.theme,bg.atr,t.anchor,o.day_index*N+t.gate)


def signals(market: Market, rule: EntryRule) -> list[Signal]:
    return sorted((s for o in market.opportunities if (s:=signal_for(o,rule)) is not None),
                  key=lambda s:(s.index,s.code))
