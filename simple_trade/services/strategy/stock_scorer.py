#!/usr/bin/env python3
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

# 及格线: 评分≥此值才进入候选
PASSING_SCORE = 60


@dataclass
class TradeParams:
    """交易参数建议 — 基于逐笔数据回测结论"""
    trade_type: str         # 'INTRADAY' | 'DAILY' | 'BOTH'
    buy_dip_pct: float      # 回撤买入百分比
    take_profit_pct: float  # 止盈百分比
    stop_loss_pct: float    # 止损百分比
    max_hold_days: int = 1  # 最大持仓天数 (日内=0, 日线≥1)
    confidence: str = ''    # 'HIGH' | 'MEDIUM' | 'LOW'
    reason: str = ''

    def to_dict(self) -> Dict[str, Any]:
        return {
            'trade_type': self.trade_type,
            'buy_dip_pct': self.buy_dip_pct,
            'take_profit_pct': self.take_profit_pct,
            'stop_loss_pct': self.stop_loss_pct,
            'max_hold_days': self.max_hold_days,
            'confidence': self.confidence,
            'reason': self.reason,
        }


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
    trade_params: Optional[TradeParams] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        result = {
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
        if self.trade_params:
            result['trade_params'] = self.trade_params.to_dict()
        return result


# -- TREND mode: volume + ticker power driven (not position-dependent) --
# 振幅参数基于1763万条逐笔数据回测：
#   振幅<8% 日内胜率12-34%, 振幅≥12% 日内胜率50-78%, ≥15% 日期望1.37%
# 5D Change放宽: 活跃股62%在此维度得零分, 放宽至(-5, 20)覆盖强趋势股
# ticker_power: 基于逐笔成交主动买卖力量比(buy_sell_ratio - 1.0)
#   BSR>=1.5(power>=0.5)=强势做多, BSR>=1.2(power>=0.2)=偏多, BSR>=1.0(power>=0.0)=中性
TREND_CONFIG = {
    'change_5d': {'max_score': 20, 'optimal_range': (-2.0, 15.0), 'marginal_range': (-5.0, 25.0), 'default': 0},
    'amplitude': {'max_score': 20, 'optimal_range': (5.0, 20.0), 'marginal_range': (3.0, 30.0), 'default': 0},
    'vol_ratio': {'max_score': 25, 'tiers': [(5.0, 20), (3.0, 25), (2.0, 18), (1.5, 12), (1.0, 5)], 'default': 0},
    'ticker_power': {'max_score': 25, 'tiers': [(0.5, 25), (0.2, 18), (0.0, 8)], 'default': 8},
    'kline_pos': {'max_score': 5, 'optimal_range': (0.0, 1.0), 'marginal_range': (0.0, 1.0), 'default': 5},
    'prev_change': {'max_score': 5, 'reverse_tiers': [(3.0, 5), (7.0, 3), (12.0, 1)], 'default': 0},
}

TREND_B_EXEMPTION = {
    'vol_ratio_min': 2.5,
    'ticker_power_min': 0.2,
    'change_5d_relaxed': {'max_score': 25, 'optimal_range': (2.0, 20.0), 'marginal_range': (-5.0, 30.0), 'default': 0},
}

# -- REVERSAL mode: oversold bounce at LOW position --
# 对齐 TrendReversalStrategy 的6个买入条件:
#   背景(40%): 低位+近期下跌 = "跌够了"
#   反转(60%): 距低点反弹+今日收涨+资金流入+放量 = "开始反转了"
REVERSAL_CONFIG = {
    # 背景条件(40%): 条件①②对应
    'kline_pos':     {'max_score': 15, 'optimal_range': (0.0, 0.2), 'marginal_range': (0.0, 0.4), 'default': 0},
    'change_5d':     {'max_score': 15, 'optimal_range': (-15.0, -3.0), 'marginal_range': (-25.0, -1.0), 'default': 0},
    'prev_change':   {'max_score': 10, 'optimal_range': (-8.0, -2.0), 'marginal_range': (-15.0, -1.0), 'default': 0},
    # 反转信号(60%): 条件③④⑤⑥对应
    'rise_from_low': {'max_score': 15, 'tiers': [(5.0, 15), (3.0, 12), (2.0, 10), (1.0, 5)], 'default': 0},
    'today_change':  {'max_score': 10, 'tiers': [(3.0, 10), (1.0, 8), (0.0, 5)], 'default': 0},
    'ticker_power':  {'max_score': 15, 'tiers': [(0.5, 15), (0.2, 12), (0.0, 6)], 'default': 6},
    'vol_ratio':     {'max_score': 15, 'tiers': [(3.0, 15), (2.0, 12), (1.5, 8), (1.2, 5)], 'default': 0},
    'amplitude':     {'max_score': 5, 'optimal_range': (3.0, 15.0), 'marginal_range': (2.0, 25.0), 'default': 0},
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

        # 根据模式和振幅生成交易参数建议
        trade_params = self._recommend_trade_params(mode, indicators) if passed else None

        result = ScoringResult(
            stock_code=stock_code, stock_name=stock_name,
            total_score=total, passed=passed, mode=mode,
            veto_reason=veto, details=details,
            trade_params=trade_params,
        )
        self._scored_cache[stock_code] = result
        return result

    def _score_trend(self, ind: Dict[str, Any]) -> tuple:
        """TREND mode: trend breakout scoring."""
        details = []
        total = 0
        vol_ratio = ind.get('vol_ratio')
        ticker_power = ind.get('ticker_power')
        change_5d = ind.get('change_5d')

        # 1. 5d change (25%) - B-type exemption for strong volume+ticker power
        is_b = (vol_ratio is not None and vol_ratio >= TREND_B_EXEMPTION['vol_ratio_min']
                and ticker_power is not None and ticker_power >= TREND_B_EXEMPTION['ticker_power_min'])
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

        # 4. Ticker power — 逐笔主动买卖力量 (25%)
        s, d = self._score_tiered(TREND_CONFIG['ticker_power'], ticker_power, 'ticker_power')
        details.append(d); total += s

        # 5. Kline position (10%)
        s, d = self._score_range(TREND_CONFIG['kline_pos'], ind.get('kline_pos_20d'), 'kline_pos')
        details.append(d); total += s

        # 6. Prev day change reverse (5%)
        s, d = self._score_reverse(TREND_CONFIG['prev_change'], ind.get('prev_day_change'), 'prev_change')
        details.append(d); total += s

        return total, details

    def _score_reversal(self, ind: Dict[str, Any]) -> tuple:
        """REVERSAL mode: 对齐TrendReversalStrategy的6个买入条件."""
        details = []
        total = 0

        # === 背景条件(40%): "跌够了" ===
        # 对应条件②: 距最高点跌幅够深
        s, d = self._score_range(REVERSAL_CONFIG['kline_pos'], ind.get('kline_pos_20d'), 'kline_pos[R]')
        details.append(d); total += s

        # 对应条件①: 近期持续下跌
        s, d = self._score_range(REVERSAL_CONFIG['change_5d'], ind.get('change_5d'), '5d_drop[R]')
        details.append(d); total += s

        s, d = self._score_range(REVERSAL_CONFIG['prev_change'], ind.get('prev_day_change'), 'prev_drop[R]')
        details.append(d); total += s

        # === 反转信号(60%): "开始反转了" ===
        # 对应条件③: 距最低点反弹≥2%
        s, d = self._score_tiered(REVERSAL_CONFIG['rise_from_low'], ind.get('rise_from_low'), 'rise_low[R]')
        details.append(d); total += s

        # 对应条件④: 今日收涨（阳线反转）
        s, d = self._score_tiered(REVERSAL_CONFIG['today_change'], ind.get('today_change'), 'today_up[R]')
        details.append(d); total += s

        # 对应条件⑤: 反弹伴随主动买入力量
        s, d = self._score_tiered(REVERSAL_CONFIG['ticker_power'], ind.get('ticker_power'), 'ticker_power[R]')
        details.append(d); total += s

        # 对应条件⑤⑥: 放量确认
        s, d = self._score_tiered(REVERSAL_CONFIG['vol_ratio'], ind.get('vol_ratio'), 'vol_ratio[R]')
        details.append(d); total += s

        # 振幅(交易可行性)
        s, d = self._score_range(REVERSAL_CONFIG['amplitude'], ind.get('day_amplitude'), 'amplitude[R]')
        details.append(d); total += s

        return total, details

    def score_snapshot(self, snapshot) -> ScoringResult:
        """Score from StockSnapshot (recommended interface)."""
        # ticker_power: 从逐笔买卖力量比转换 (BSR - 1.0)
        # 优先使用 ticker 数据，若无则回退到旧 flow_ratio
        bsr = getattr(snapshot, 'ticker_buy_sell_ratio', None)
        if bsr is not None and bsr > 0:
            ticker_power = bsr - 1.0
        else:
            # 回退：旧资金流数据作为兜底
            ticker_power = getattr(snapshot, 'net_inflow_ratio', None)
        indicators = {
            'change_5d': snapshot.change_5d,
            'kline_pos_20d': snapshot.kline_position_20d,
            'day_amplitude': snapshot.amplitude,
            'vol_ratio': snapshot.volume_ratio,
            'prev_day_change': snapshot.prev_day_change,
            'ticker_power': ticker_power,
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

    @staticmethod
    def _recommend_trade_params(mode: str, indicators: Dict[str, Any]) -> TradeParams:
        """根据评分模式和市场指标，推荐日内或日线交易参数。

        回测数据源：
        - TREND: 1763万条逐笔成交, 140个高波动日
        - REVERSAL: 17.2万条日K线, 601只股票, 55283个信号
        """
        amp = indicators.get('day_amplitude', 0) or 0
        chg5d = indicators.get('change_5d', 0) or 0

        if mode == 'REVERSAL':
            # REVERSAL = 日线交易, 委托TrendReversalStrategy执行
            # 回测优化: 追踪止盈(涨15%后回撤8%卖)+20%止损+30天 胜率53% 笔均+2.15%
            # 入场: 次日开盘买入(比收盘便宜~1%)
            if chg5d <= -15:
                confidence = 'HIGH'
                reason = f'深度超卖(5日跌{chg5d:.1f}%)，反弹确定性高'
            elif chg5d <= -8:
                confidence = 'HIGH'
                reason = f'超卖反弹(5日跌{chg5d:.1f}%)，PF=2.07'
            else:
                confidence = 'MEDIUM'
                reason = f'低位反转(5日跌{chg5d:.1f}%)，需等待反弹确认'
            return TradeParams(
                trade_type='DAILY',
                buy_dip_pct=0.0,              # 次日开盘买入, 不需要回撤
                take_profit_pct=15.0,         # 追踪止盈激活点
                stop_loss_pct=20.0,           # 宽止损，给反弹空间
                max_hold_days=30,             # 长持仓等反弹
                confidence=confidence,
                reason=reason
            )

        # TREND mode — 统一参数, 阶梯低吸入场
        # 回测优化: SL=8%+Trail10/3+3D, 阶梯低吸(前收-1%优先/前收兜底)
        # 收盘买: 胜率46% 笔均+0.91% | 阶梯低吸: 胜率80% 笔均+6.14%
        if amp >= 8:
            confidence = 'HIGH'
            reason = f'高振幅{amp:.1f}%，阶梯低吸入场(前收-1%/前收)'
        elif amp >= 5:
            confidence = 'MEDIUM'
            reason = f'中振幅{amp:.1f}%，阶梯低吸入场'
        else:
            confidence = 'LOW'
            reason = f'低振幅{amp:.1f}%，阶梯低吸入场'
        return TradeParams(
            trade_type='DAILY',
            buy_dip_pct=1.0,              # 阶梯: 先挂前收-1%, 未成交则前收
            take_profit_pct=10.0,         # 追踪���盈激活点
            stop_loss_pct=8.0,            # 止损8%
            max_hold_days=3,              # 持仓3天
            confidence=confidence,
            reason=reason
        )

