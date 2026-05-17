#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Write stock_scorer.py with proper encoding"""

path = r'd:\Program Files\futu_trade_sys\simple_trade\services\strategy\stock_scorer.py'

code = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Stock Scoring Engine - Dual Mode (TREND + REVERSAL)

Based on 4899-sample broad-spectrum backtest.
System auto-selects higher-scoring mode.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class ScoreDetail:
    dimension: str
    value: Optional[float]
    score: int
    max_score: int
    note: str = ""


@dataclass
class ScoringResult:
    stock_code: str
    stock_name: str
    total_score: int
    passed: bool
    mode: str = ""
    veto_reason: str = ""
    details: List[ScoreDetail] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'total_score': self.total_score,
            'passed': self.passed,
            'mode': self.mode,
            'veto_reason': self.veto_reason,
            'details': [
                {'dimension': d.dimension, 'value': d.value,
                 'score': d.score, 'max': d.max_score, 'note': d.note}
                for d in self.details
            ],
            'timestamp': self.timestamp,
        }


# -- TREND mode: low-position volume breakout + capital confirmation --
TREND_CONFIG = {
    'change_5d': {'max_score': 25, 'optimal_range': (2.0, 8.0), 'marginal_range': (0.0, 15.0), 'default': 0},
    'amplitude': {'max_score': 25, 'optimal_range': (5.0, 15.0), 'marginal_range': (3.0, 25.0), 'default': 0},
    'vol_ratio': {'max_score': 20, 'tiers': [(5.0, 15), (3.0, 20), (2.0, 15), (1.5, 10), (1.0, 5)], 'default': 0},
    'flow':      {'max_score': 15, 'tiers': [(0.3, 15), (0.15, 10), (0.0, 5)], 'default': 0},
    'kline_pos': {'max_score': 10, 'optimal_range': (0.1, 0.5), 'marginal_range': (0.0, 0.7), 'default': 0},
    'prev_change': {'max_score': 5, 'reverse_tiers': [(3.0, 5), (7.0, 3), (12.0, 1)], 'default': 0},
}

TREND_B_EXEMPTION = {
    'vol_ratio_min': 2.5,
    'flow_ratio_min': 0.2,
    'change_5d_relaxed': {'max_score': 25, 'optimal_range': (2.0, 20.0), 'marginal_range': (-5.0, 30.0), 'default': 0},
}

# -- REVERSAL mode: oversold bounce --
REVERSAL_CONFIG = {
    'amplitude':     {'max_score': 30, 'optimal_range': (5.0, 20.0), 'marginal_range': (3.0, 35.0), 'default': 0},
    'prev_change':   {'max_score': 25, 'optimal_range': (-8.0, -2.0), 'marginal_range': (-15.0, -1.0), 'default': 0},
    'change_5d':     {'max_score': 20, 'optimal_range': (-15.0, -3.0), 'marginal_range': (-25.0, -1.0), 'default': 0},
    'flow_momentum': {'max_score': 15, 'tiers': [(-0.5, 15), (-0.3, 10), (-0.1, 5)], 'default': 0},
    'vol_ratio':     {'max_score': 10, 'tiers': [(2.0, 10), (1.0, 7), (0.7, 5)], 'default': 0},
}

VETO_RULES = {
    'prev_day_change_max': 20.0,
    'prev_day_vol_ratio_min': 1.5,
    'amplitude_max': 45.0,
    'kline_position_max': 1.0,
    'same_stock_max_losses': 2,
}

PASSING_SCORE = 60


class StockScorer:
    """Dual-mode stock scoring engine (TREND / REVERSAL)."""

    def __init__(self):
        self._scored_cache: Dict[str, ScoringResult] = {}
        self._daily_losses: Dict[str, int] = {}
        self._score_date: str = datetime.now().strftime('%Y-%m-%d')

    def score_stock(self, stock_code: str, stock_name: str,
                    indicators: Dict[str, Any]) -> ScoringResult:
        """Score a stock using both modes, return higher score."""
        trend_score, trend_details = self._score_trend(indicators)
        reversal_score, reversal_details = self._score_reversal(indicators)

        if trend_score >= reversal_score:
            mode, total, details = 'TREND', trend_score, trend_details
        else:
            mode, total, details = 'REVERSAL', reversal_score, reversal_details

        veto = self._check_veto(stock_code, indicators)
        passed = total >= PASSING_SCORE and not veto
        result = ScoringResult(
            stock_code=stock_code, stock_name=stock_name,
            total_score=total, passed=passed, mode=mode,
            veto_reason=veto, details=details,
        )
        self._scored_cache[stock_code] = result
        return result

    def _score_trend(self, ind: Dict[str, Any]) -> tuple:
        """TREND mode: trend breakout scoring."""
        details = []
        total = 0
        vol_ratio = ind.get('vol_ratio')
        flow_ratio = ind.get('flow_ratio')
        change_5d = ind.get('change_5d')

        # 1. 5d change (25%) - B-type exemption for strong volume+flow
        is_b = (vol_ratio is not None and vol_ratio >= TREND_B_EXEMPTION['vol_ratio_min']
                and flow_ratio is not None and flow_ratio >= TREND_B_EXEMPTION['flow_ratio_min'])
        cfg = TREND_B_EXEMPTION['change_5d_relaxed'] if is_b else TREND_CONFIG['change_5d']
        label = '5d_change(B-relax)' if is_b else '5d_change'
        s, d = self._score_range(cfg, change_5d, label)
        details.append(d); total += s

        # 2. Amplitude (25%)
        s, d = self._score_range(TREND_CONFIG['amplitude'], ind.get('day_amplitude'), 'amplitude')
        details.append(d); total += s

        # 3. Volume ratio (20%)
        s, d = self._score_tiered(TREND_CONFIG['vol_ratio'], ind.get('vol_ratio'), 'vol_ratio')
        details.append(d); total += s

        # 4. Capital flow positive (15%)
        s, d = self._score_tiered(TREND_CONFIG['flow'], ind.get('flow_ratio'), 'flow')
        details.append(d); total += s

        # 5. Kline position (10%)
        s, d = self._score_range(TREND_CONFIG['kline_pos'], ind.get('kline_pos_20d'), 'kline_pos')
        details.append(d); total += s

        # 6. Prev day change reverse (5%)
        s, d = self._score_reverse(TREND_CONFIG['prev_change'], ind.get('prev_day_change'), 'prev_change')
        details.append(d); total += s

        return total, details

    def _score_reversal(self, ind: Dict[str, Any]) -> tuple:
        """REVERSAL mode: oversold bounce scoring."""
        details = []
        total = 0

        # 1. Amplitude (30%)
        s, d = self._score_range(REVERSAL_CONFIG['amplitude'], ind.get('day_amplitude'), 'amplitude[R]')
        details.append(d); total += s

        # 2. Prev day drop (25%) - deep drop = bounce signal
        s, d = self._score_range(REVERSAL_CONFIG['prev_change'], ind.get('prev_day_change'), 'prev_drop[R]')
        details.append(d); total += s

        # 3. 5d drop (20%) - oversold zone
        s, d = self._score_range(REVERSAL_CONFIG['change_5d'], ind.get('change_5d'), '5d_oversold[R]')
        details.append(d); total += s

        # 4. Flow momentum reverse (15%) - outflow = bounce opportunity
        s, d = self._score_tiered_reverse(REVERSAL_CONFIG['flow_momentum'], ind.get('flow_ratio'), 'flow_rev[R]')
        details.append(d); total += s

        # 5. Volume ratio (10%)
        s, d = self._score_tiered(REVERSAL_CONFIG['vol_ratio'], ind.get('vol_ratio'), 'vol_ratio[R]')
        details.append(d); total += s

        return total, details

    def score_snapshot(self, snapshot) -> ScoringResult:
        """Score from StockSnapshot (recommended interface)."""
        indicators = {
            'change_5d': snapshot.change_5d,
            'kline_pos_20d': snapshot.kline_position_20d,
            'day_amplitude': snapshot.amplitude,
            'vol_ratio': snapshot.volume_ratio,
            'prev_day_change': snapshot.prev_day_change,
            'flow_ratio': snapshot.net_inflow_ratio,
        }
        return self.score_stock(snapshot.code, snapshot.name, indicators)

    def get_candidates(self, min_score: int = PASSING_SCORE) -> List[ScoringResult]:
        """Get passing candidates sorted by score desc."""
        return sorted(
            [r for r in self._scored_cache.values() if r.passed and r.total_score >= min_score],
            key=lambda x: x.total_score, reverse=True,
        )

    def get_score(self, stock_code: str) -> Optional[ScoringResult]:
        """Get cached score for a stock."""
        return self._scored_cache.get(stock_code)

    def record_loss(self, stock_code: str):
        """Record a loss for intraday veto tracking."""
        self._daily_losses[stock_code] = self._daily_losses.get(stock_code, 0) + 1
        logger.info(f"[StockScorer] {stock_code} loss count: {self._daily_losses[stock_code]}")

    def check_intraday_veto(self, stock_code: str) -> str:
        """Check intraday same-stock loss veto."""
        max_losses = VETO_RULES['same_stock_max_losses']
        losses = self._daily_losses.get(stock_code, 0)
        if losses >= max_losses:
            return f"same-day losses {losses}>={max_losses}"
        return ""

    def reset_daily(self):
        """Reset daily state."""
        self._daily_losses.clear()
        self._scored_cache.clear()
        self._score_date = datetime.now().strftime('%Y-%m-%d')
        logger.info("[StockScorer] daily reset")

    # -- Generic scoring methods --

    @staticmethod
    def _score_range(cfg: dict, value, label: str) -> tuple:
        if value is None:
            return 0, ScoreDetail(label, None, 0, cfg['max_score'], 'no data')
        opt_lo, opt_hi = cfg['optimal_range']
        mar_lo, mar_hi = cfg['marginal_range']
        if opt_lo <= value <= opt_hi:
            score = cfg['max_score']
        elif mar_lo <= value <= mar_hi:
            score = cfg['max_score'] // 2
        else:
            score = cfg['default']
        return score, ScoreDetail(label, round(value, 3), score, cfg['max_score'])

    @staticmethod
    def _score_tiered(cfg: dict, value, label: str) -> tuple:
        if value is None:
            return 0, ScoreDetail(label, None, 0, cfg['max_score'], 'no data')
        score = cfg['default']
        for threshold, points in cfg['tiers']:
            if value >= threshold:
                score = points
                break
        return score, ScoreDetail(label, round(value, 3), score, cfg['max_score'])

    @staticmethod
    def _score_tiered_reverse(cfg: dict, value, label: str) -> tuple:
        if value is None:
            return 0, ScoreDetail(label, None, 0, cfg['max_score'], 'no data')
        score = cfg['default']
        for threshold, points in cfg['tiers']:
            if value <= threshold:
                score = points
                break
        return score, ScoreDetail(label, round(value, 3), score, cfg['max_score'])

    @staticmethod
    def _score_reverse(cfg: dict, value, label: str) -> tuple:
        if value is None:
            return 0, ScoreDetail(label, None, 0, cfg['max_score'], 'no data')
        score = cfg['default']
        for threshold, points in cfg['reverse_tiers']:
            if value <= threshold:
                score = points
                break
        return score, ScoreDetail(label, round(value, 3), score, cfg['max_score'])

    def _check_veto(self, stock_code: str, indicators: Dict[str, Any]) -> str:
        prev = indicators.get('prev_day_change')
        vol_ratio = indicators.get('vol_ratio')
        vol_min = VETO_RULES['prev_day_vol_ratio_min']
        if prev is not None and prev > VETO_RULES['prev_day_change_max']:
            if vol_ratio is None or vol_ratio < vol_min:
                return f"prev_change {prev:.1f}%>{VETO_RULES['prev_day_change_max']}%"

        amp = indicators.get('day_amplitude')
        if amp is not None and amp > VETO_RULES['amplitude_max']:
            return f"amplitude {amp:.1f}%>{VETO_RULES['amplitude_max']}%"

        kp = indicators.get('kline_pos_20d')
        if kp is not None and kp > VETO_RULES['kline_position_max']:
            return f"kline_pos {kp:.3f}>{VETO_RULES['kline_position_max']}"

        return self.check_intraday_veto(stock_code)
'''

with open(path, 'w', encoding='utf-8') as f:
    f.write(code)
print(f'Written {len(code)} chars')
