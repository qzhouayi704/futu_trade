#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Stock Scoring Engine - TREND + BREAKOUT

Based on 2561-trade backtest (2026-04~05).
REVERSAL strategy archived to strategy_archive/reversal_v1.py
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
    'amplitude': {'max_score': 20, 'optimal_range': (5.0, 20.0), 'marginal_range': (3.0, 50.0), 'default': 0},
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

# REVERSAL strategy archived → strategy_archive/reversal_v1.py

# MOMENTUM mode: 动量接力 — 前日暴涨股次日低吸
# 适用条件: prev_day_change >= 15%
MOMENTUM_CONFIG = {
    'prev_surge': {'max_score': 15, 'tiers': [(30.0, 15), (20.0, 12), (15.0, 8)], 'default': 0},
    'today_change': {'max_score': 20, 'optimal_range': (-3.0, 10.0), 'marginal_range': (-8.0, 20.0), 'default': 0},
    'vol_ratio': {'max_score': 20, 'tiers': [(3.0, 20), (2.0, 16), (1.5, 12), (1.0, 6)], 'default': 0},
    'ticker_power': {'max_score': 15, 'tiers': [(0.5, 15), (0.2, 10), (0.0, 5)], 'default': 5},
    'amplitude': {'max_score': 15, 'optimal_range': (5.0, 25.0), 'marginal_range': (3.0, 40.0), 'default': 0},
    'recovery': {'max_score': 15, 'tiers': [(0.8, 15), (0.6, 12), (0.4, 8), (0.2, 4)], 'default': 0},
}
MOMENTUM_TRIGGER_MIN = 15.0

VETO_RULES = {
    'prev_day_change_max': 50.0,
    'prev_day_vol_ratio_min': 1.5,
    'amplitude_max': 45.0,
    'kline_position_max': 1.0,
    'same_stock_max_losses': 2,
}

PASSING_SCORE = 60


class StockScorer:
    """Stock scoring engine (TREND + BREAKOUT)."""

    def __init__(self):
        self._scored_cache: Dict[str, ScoringResult] = {}
        self._daily_losses: Dict[str, int] = {}
        self._score_date: str = datetime.now().strftime('%Y-%m-%d')

    def score_stock(self, stock_code: str, stock_name: str,
                    indicators: Dict[str, Any]) -> ScoringResult:
        """Score a stock using TREND mode."""
        trend_score, trend_details = self._score_trend(indicators)
        mode, total, details = 'TREND', trend_score, trend_details

        veto = self._check_veto(stock_code, indicators)
        passed = total >= PASSING_SCORE and not veto

        trade_params = self._recommend_trade_params(mode, indicators) if passed else None

        result = ScoringResult(
            stock_code=stock_code, stock_name=stock_name,
            total_score=total, passed=passed, mode=mode,
            veto_reason=veto, details=details,
            trade_params=trade_params,
        )
        self._scored_cache[stock_code] = result
        return result

    def score_all_strategies(self, stock_code: str, stock_name: str,
                              indicators: Dict[str, Any]) -> Dict[str, Any]:
        """返回 TREND + BREAKOUT + MOMENTUM 三套策略的独立评分结果。"""
        trend_score, trend_details = self._score_trend(indicators)
        breakout_score, breakout_details, breakout_triggered = self._score_breakout(indicators)
        momentum_score, momentum_details, momentum_triggered = self._score_momentum(indicators)

        veto = self._check_veto(stock_code, indicators)

        def _build(mode, score, details, apply_veto=True):
            v = veto if apply_veto else ''
            passed = score >= PASSING_SCORE and not v
            return ScoringResult(
                stock_code=stock_code, stock_name=stock_name,
                total_score=score, passed=passed, mode=mode,
                veto_reason=v if not passed else '', details=details,
            )

        trend_result = _build('TREND', trend_score, trend_details)
        breakout_result = _build('BREAKOUT', breakout_score, breakout_details)
        # MOMENTUM 不受前日涨幅否决（它就是为暴涨股设计的）
        momentum_result = _build('MOMENTUM', momentum_score, momentum_details, apply_veto=False)

        # 最佳策略
        all_results = [trend_result]
        if breakout_triggered:
            all_results.append(breakout_result)
        if momentum_triggered:
            all_results.append(momentum_result)
        best = max(all_results, key=lambda r: r.total_score)

        # 缓存最佳结果
        self._scored_cache[stock_code] = best

        return {
            'best': best,
            'trend': trend_result,
            'breakout': breakout_result,
            'momentum': momentum_result,
            'breakout_triggered': breakout_triggered,
            'momentum_triggered': momentum_triggered,
        }

    def _score_trend(self, ind: Dict[str, Any]) -> tuple:
        """TREND mode: trend breakout scoring."""
        details = []
        total = 0
        vol_ratio = ind.get('vol_ratio')
        ticker_power = ind.get('ticker_power')
        change_5d = ind.get('change_5d')

        # 1. 5日涨跌 (25%) - B类豁免：量比+逐笔力量足够强时放宽
        is_b = (vol_ratio is not None and vol_ratio >= TREND_B_EXEMPTION['vol_ratio_min']
                and ticker_power is not None and ticker_power >= TREND_B_EXEMPTION['ticker_power_min'])
        cfg = TREND_B_EXEMPTION['change_5d_relaxed'] if is_b else TREND_CONFIG['change_5d']
        label = '5日涨跌(放宽)' if is_b else '5日涨跌'
        s, d = self._score_range(cfg, change_5d, label)
        details.append(d); total += s

        # 2. 日内振幅 (25%)
        s, d = self._score_range(TREND_CONFIG['amplitude'], ind.get('day_amplitude'), '日内振幅')
        details.append(d); total += s

        # 3. 量比 (20%)
        s, d = self._score_tiered(TREND_CONFIG['vol_ratio'], ind.get('vol_ratio'), '量比')
        details.append(d); total += s

        # 4. 逐笔买卖力量 (25%)
        s, d = self._score_tiered(TREND_CONFIG['ticker_power'], ticker_power, '逐笔买卖力量')
        details.append(d); total += s

        # 5. K线位置 (10%)
        s, d = self._score_range(TREND_CONFIG['kline_pos'], ind.get('kline_pos_20d'), 'K线位置')
        details.append(d); total += s

        # 6. 前日涨跌（反向） (5%)
        s, d = self._score_reverse(TREND_CONFIG['prev_change'], ind.get('prev_day_change'), '前日涨跌')
        details.append(d); total += s

        return total, details

    # _score_reversal archived → strategy_archive/reversal_v1.py

    def _score_breakout(self, ind: Dict[str, Any]) -> tuple:
        """BREAKOUT mode: 蓄势突破评分。返回 (score, details, triggered)。"""
        details = []
        total = 0

        # 前置条件：必须有突破级别
        bl = ind.get('breakout_level', '')
        triggered = bool(bl)

        # 1. 突破级别 (15分)
        if bl == '20日高':
            s = 15
        elif bl == '10日高':
            s = 12
        elif bl == '5日高':
            s = 8
        else:
            s = 0
        details.append(ScoreDetail('突破级别', None, s, 15, bl or '未突破'))
        total += s

        # 2. 突破幅度 (15分) — 0~3%最佳
        bp = ind.get('breakout_pct')
        if bp is not None:
            if 0 <= bp <= 3:
                s = 15
            elif bp <= 5:
                s = 10
            elif bp <= 8:
                s = 6
            else:
                s = 3
            details.append(ScoreDetail('突破幅度', round(bp, 2), s, 15))
        else:
            details.append(ScoreDetail('突破幅度', None, 7, 15, '无数据(中性)'))
            total += 7

        total += s if bp is not None else 0

        # 3. 资金净流入占比 (15分)
        nir = ind.get('net_inflow_ratio')
        cfg_nir = {'max_score': 15, 'tiers': [(0.1, 15), (0.05, 12), (0.02, 8), (0.0, 4)], 'default': 0}
        s, d = self._score_tiered(cfg_nir, nir, '资金净流入')
        details.append(d); total += s

        # 4. 大单买比 (10分)
        bor = ind.get('big_order_buy_ratio')
        cfg_bor = {'max_score': 10, 'tiers': [(0.6, 10), (0.5, 7), (0.4, 4)], 'default': 0}
        s, d = self._score_tiered(cfg_bor, bor, '大单买比')
        details.append(d); total += s

        # 5. 资金连续天数 (10分)
        cd = ind.get('capital_continuity_days')
        cfg_cd = {'max_score': 10, 'tiers': [(5, 10), (3, 8), (2, 6), (1, 3)], 'default': 0}
        s, d = self._score_tiered(cfg_cd, cd, '资金连续流入')
        details.append(d); total += s

        # 6. 量比 (15分)
        s, d = self._score_tiered(
            {'max_score': 15, 'tiers': [(3.0, 15), (2.0, 12), (1.5, 8), (1.0, 4)], 'default': 0},
            ind.get('vol_ratio'), '量比')
        details.append(d); total += s

        # 7. 逐笔买卖力量 (10分)
        s, d = self._score_tiered(
            {'max_score': 10, 'tiers': [(0.5, 10), (0.2, 7), (0.0, 4)], 'default': 4},
            ind.get('ticker_power'), '逐笔买卖力量')
        details.append(d); total += s

        # 8. 涨幅适中 (10分)
        chg = ind.get('today_change') or ind.get('change_pct')
        if chg is not None:
            if 1 <= chg <= 5:
                s = 10
            elif 0 < chg < 1:
                s = 6
            elif 5 < chg <= 10:
                s = 7
            else:
                s = 3
            details.append(ScoreDetail('涨幅适中', round(chg, 2), s, 10))
            total += s
        else:
            details.append(ScoreDetail('涨幅适中', None, 5, 10, '无数据(中性)'))
            total += 5

        return total, details, triggered

    def _score_momentum(self, ind: Dict[str, Any]) -> tuple:
        """MOMENTUM mode: 动量接力评分。返回 (score, details, triggered)。"""
        details = []
        total = 0
        prev_change = ind.get('prev_day_change')
        triggered = prev_change is not None and prev_change >= MOMENTUM_TRIGGER_MIN

        # 1. 前日涨幅强度 (15分)
        s, d = self._score_tiered(MOMENTUM_CONFIG['prev_surge'], prev_change, '前日涨幅强度')
        details.append(d); total += s

        # 2. 今日涨跌幅 (20分) — 低开/小涨是好买点
        today_chg = ind.get('today_change') or ind.get('change_pct')
        s, d = self._score_range(MOMENTUM_CONFIG['today_change'], today_chg, '今日涨跌')
        details.append(d); total += s

        # 3. 量比 (20分)
        s, d = self._score_tiered(MOMENTUM_CONFIG['vol_ratio'], ind.get('vol_ratio'), '量比')
        details.append(d); total += s

        # 4. 逐笔买卖力量 (15分)
        s, d = self._score_tiered(MOMENTUM_CONFIG['ticker_power'], ind.get('ticker_power'), '逐笔买卖力量')
        details.append(d); total += s

        # 5. 日内振幅 (15分)
        s, d = self._score_range(MOMENTUM_CONFIG['amplitude'], ind.get('day_amplitude'), '日内振幅')
        details.append(d); total += s

        # 6. 反包力度 (15分) — (current - low) / (high - low)
        s, d = self._score_tiered(MOMENTUM_CONFIG['recovery'], ind.get('recovery_ratio'), '反包力度')
        details.append(d); total += s

        return total, details, triggered

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
            mid = cfg['max_score'] // 2
            return mid, ScoreDetail(label, None, mid, cfg['max_score'], '无数据(中性)')
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
            mid = cfg['max_score'] // 2
            return mid, ScoreDetail(label, None, mid, cfg['max_score'], '无数据(中性)')
        score = cfg['default']
        for threshold, points in cfg['tiers']:
            if value >= threshold:
                score = points
                break
        return score, ScoreDetail(label, round(value, 3), score, cfg['max_score'])

    @staticmethod
    def _score_tiered_reverse(cfg: dict, value, label: str) -> tuple:
        if value is None:
            mid = cfg['max_score'] // 2
            return mid, ScoreDetail(label, None, mid, cfg['max_score'], '无数据(中性)')
        score = cfg['default']
        for threshold, points in cfg['tiers']:
            if value <= threshold:
                score = points
                break
        return score, ScoreDetail(label, round(value, 3), score, cfg['max_score'])

    @staticmethod
    def _score_reverse(cfg: dict, value, label: str) -> tuple:
        if value is None:
            mid = cfg['max_score'] // 2
            return mid, ScoreDetail(label, None, mid, cfg['max_score'], '无数据(中性)')
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

        # REVERSAL trade params archived → strategy_archive/reversal_v1.py

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

