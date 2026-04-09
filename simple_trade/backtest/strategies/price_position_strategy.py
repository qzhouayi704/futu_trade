#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
价格位置统计策略（兼容入口）

本文件保留为向后兼容入口，所有核心逻辑已拆分到
simple_trade/backtest/strategies/price_position/ 子模块。
"""

import numpy as np
from typing import Dict, List, Any, Optional
from .base_strategy import BaseBacktestStrategy

# ========== 常量 re-export ==========
from .price_position.constants import (
    TARGET_STOCKS, ZONE_DEFINITIONS, ZONE_NAMES, LOOKBACK_DAYS,
    MIN_TRIGGER_RATE, SENTIMENT_ETF_CODE,
    SENTIMENT_BEARISH, SENTIMENT_NEUTRAL, SENTIMENT_BULLISH, SENTIMENT_LEVELS,
    DEFAULT_SENTIMENT_THRESHOLDS, DEFAULT_SENTIMENT_ADJUSTMENTS,
    DEFAULT_OPEN_ANCHOR_PARAMS,
    OPEN_TYPE_GAP_UP, OPEN_TYPE_FLAT, OPEN_TYPE_GAP_DOWN, OPEN_TYPES,
    DEFAULT_GAP_THRESHOLD,
)

# ========== 子模块导入 ==========
from .price_position.classifiers import (
    classify_zone as _classify_zone,
    classify_open_type as _classify_open_type,
    classify_sentiment as _classify_sentiment,
    build_sentiment_map as _build_sentiment_map,
)
from .price_position.statistics import (
    calculate_daily_metrics as _calculate_daily_metrics,
    compute_zone_statistics as _compute_zone_statistics,
    compute_stats as _compute_stats_fn,
    empty_stats as _empty_stats_fn,
)
from .price_position.trade_simulator import (
    apply_sentiment_adjustment as _apply_sentiment_adjustment,
    simulate_trades as _simulate_trades,
    simulate_trades_next_day as _simulate_trades_next_day,
)
from .price_position.grid_optimizer import (
    generate_range as _generate_range_fn,
)
from .price_position.report_generator import (
    generate_analysis_report as _generate_analysis_report,
)

_DEFAULT_SL_RANGE = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]


class PricePositionStrategy(BaseBacktestStrategy):
    """价格位置统计策略（兼容入口），核心逻辑已拆分到 price_position/ 子模块。"""

    def __init__(self, lookback_days: int = LOOKBACK_DAYS, **kwargs):
        super().__init__(lookback_days=lookback_days, **kwargs)
        self.lookback_days = lookback_days

    def get_strategy_name(self) -> str:
        return "价格位置统计策略"

    def get_lookback_days(self) -> int:
        return self.lookback_days + 5

    def get_forward_days(self) -> int:
        return 0

    # ========== 分类方法（委托到 classifiers） ==========

    @staticmethod
    def classify_zone(position: float) -> str:
        return _classify_zone(position)

    @staticmethod
    def classify_open_type(
        open_price: float, prev_close: float,
        gap_threshold: float = DEFAULT_GAP_THRESHOLD,
    ) -> str:
        return _classify_open_type(open_price, prev_close, gap_threshold)

    @staticmethod
    def classify_sentiment(
        sentiment_pct: float, thresholds: Optional[Dict[str, float]] = None,
    ) -> str:
        return _classify_sentiment(sentiment_pct, thresholds)

    @staticmethod
    def build_sentiment_map(
        etf_kline_data: List[Dict[str, Any]],
        thresholds: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        return _build_sentiment_map(etf_kline_data, thresholds)

    @staticmethod
    def apply_sentiment_adjustment(
        params: Dict[str, float], sentiment_level: str,
        adjustments: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> Dict[str, float]:
        """委托到 trade_simulator（向后兼容：返回 dict）"""
        r = _apply_sentiment_adjustment(params, sentiment_level, adjustments)
        return {'buy_dip_pct': r.buy_dip_pct, 'sell_rise_pct': r.sell_rise_pct,
                'stop_loss_pct': r.stop_loss_pct}

    # ========== 统计方法（委托到 statistics） ==========

    def calculate_daily_metrics(
        self, kline_data: List[Dict[str, Any]],
        sentiment_map: Optional[Dict[str, Dict[str, Any]]] = None,
        gap_threshold: float = DEFAULT_GAP_THRESHOLD,
    ) -> List[Dict[str, Any]]:
        return _calculate_daily_metrics(
            kline_data, self.lookback_days, sentiment_map, gap_threshold)

    def compute_zone_statistics(self, metrics: List[Dict[str, Any]]) -> Dict[str, Any]:
        return _compute_zone_statistics(metrics)

    @staticmethod
    def _compute_stats(values: np.ndarray) -> Dict[str, float]:
        return _compute_stats_fn(values)

    @staticmethod
    def _empty_stats() -> Dict[str, float]:
        return _empty_stats_fn()

    # ========== 止损百分位 ==========

    ZONE_STOP_LOSS_PERCENTILE = {
        '低位(0-20%)': 'p75', '偏低(20-40%)': 'median', '中位(40-60%)': 'median',
        '偏高(60-80%)': 'p25', '高位(80-100%)': 'p25',
    }

    # ========== 保留原始实现的方法 ==========

    def recommend_trade_params(
        self, zone_stats: Dict[str, Any],
        metrics: Optional[List[Dict[str, Any]]] = None,
        min_profit_spread: float = 0.5,
    ) -> Dict[str, Dict[str, float]]:
        """基于历史统计推荐每个区间的买卖基数和止损比例"""
        trade_params = {}
        _zero = {'buy_dip_pct': 0, 'sell_rise_pct': 0, 'stop_loss_pct': 3.0}
        for zone_name, stats in zone_stats.items():
            if stats['count'] == 0:
                trade_params[zone_name] = dict(_zero)
                continue
            drop_s, rise_s = stats['drop_stats'], stats['rise_stats']
            buy_dip_pct = max(0.1, round(abs(drop_s.get('median', 0)), 4))
            sell_rise_pct = max(0.1, round(rise_s.get('median', 0), 4))
            stop_key = self.ZONE_STOP_LOSS_PERCENTILE.get(zone_name, 'median')
            raw_stop = abs(drop_s.get(stop_key, drop_s['median']))
            stop_loss_pct = max(1.0, min(5.0, round(raw_stop, 4)))
            if buy_dip_pct + sell_rise_pct < min_profit_spread:
                trade_params[zone_name] = dict(_zero)
                continue
            trade_params[zone_name] = {
                'buy_dip_pct': buy_dip_pct, 'sell_rise_pct': sell_rise_pct,
                'stop_loss_pct': stop_loss_pct,
            }
        return trade_params

    def optimize_stop_loss(
        self, metrics: List[Dict[str, Any]],
        trade_params: Dict[str, Dict[str, float]],
        fee_calculator: Any = None, trade_amount: float = 60000.0,
        stop_loss_range: Optional[List[float]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """对每个区间搜索最优止损比例"""
        if stop_loss_range is None:
            stop_loss_range = list(_DEFAULT_SL_RANGE)
        results = {}
        _empty = {'best_stop_loss': 3.0, 'avg_net_profit': 0.0,
                   'win_rate': 0.0, 'trades_count': 0, 'stop_loss_rate': 0.0}
        for zone_name in ZONE_NAMES:
            params = trade_params.get(zone_name)
            if not params or params['buy_dip_pct'] <= 0:
                results[zone_name] = {**_empty, 'all_results': []}
                continue
            best, all_res = None, []
            for sl_pct in stop_loss_range:
                tp = {zn: dict(p) for zn, p in trade_params.items()}
                tp[zone_name]['stop_loss_pct'] = sl_pct
                trades = self.simulate_trades(
                    metrics, tp, trade_amount=trade_amount,
                    fee_calculator=fee_calculator)
                zt = [t for t in trades if t['zone'] == zone_name]
                total = len(zt)
                if total == 0:
                    all_res.append({'stop_loss': sl_pct, 'avg_net_profit': 0.0,
                                    'win_rate': 0.0, 'trades_count': 0,
                                    'stop_loss_rate': 0.0})
                    continue
                avg_net = sum(t['net_profit_pct'] for t in zt) / total
                wr = len([t for t in zt if t['net_profit_pct'] > 0]) / total * 100
                slr = len([t for t in zt if t['exit_type'] == 'stop_loss']) / total * 100
                r = {'stop_loss': sl_pct, 'avg_net_profit': round(avg_net, 4),
                     'win_rate': round(wr, 2), 'trades_count': total,
                     'stop_loss_rate': round(slr, 2)}
                all_res.append(r)
                if best is None or avg_net > best['avg_net_profit']:
                    best = r
            if best is None:
                best = dict(_empty)
            results[zone_name] = {
                'best_stop_loss': best['stop_loss'], 'avg_net_profit': best['avg_net_profit'],
                'win_rate': best['win_rate'], 'trades_count': best['trades_count'],
                'stop_loss_rate': best['stop_loss_rate'], 'all_results': all_res,
            }
        return results

    def optimize_params_grid(
        self, metrics: List[Dict[str, Any]], zone_stats: Dict[str, Any],
        fee_calculator: Any = None, trade_amount: float = 60000.0,
        buy_dip_range: Optional[List[float]] = None,
        sell_rise_range: Optional[List[float]] = None,
        stop_loss_range: Optional[List[float]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """旧版网格搜索，不使用综合评分，用 avg_net_profit 选最优，min_trades=5。"""
        if stop_loss_range is None:
            stop_loss_range = list(_DEFAULT_SL_RANGE)
        results = {}
        for zone_name in ZONE_NAMES:
            stats = zone_stats.get(zone_name, {})
            if stats.get('count', 0) == 0:
                results[zone_name] = self._empty_grid_result()
                continue
            drop_s, rise_s = stats['drop_stats'], stats['rise_stats']
            if buy_dip_range is None:
                dp25, dp75 = abs(drop_s.get('p25', 0)), abs(drop_s.get('p75', 0))
                dmed = abs(drop_s.get('median', 0))
                lo = max(0.25, min(dp75, dmed * 0.5))
                z_buy = self._generate_range(lo, max(lo + 0.5, dp25 * 1.2), 0.25)
            else:
                z_buy = buy_dip_range
            if sell_rise_range is None:
                rp25, rp75 = rise_s.get('p25', 0), rise_s.get('p75', 0)
                rmed = rise_s.get('median', 0)
                lo = max(0.25, min(rp25, rmed * 0.5))
                z_sell = self._generate_range(lo, max(lo + 0.5, rp75 * 1.2), 0.25)
            else:
                z_sell = sell_rise_range
            best, searched = None, 0
            for bd in z_buy:
                for sr in z_sell:
                    for sl in stop_loss_range:
                        searched += 1
                        tp = {zn: {'buy_dip_pct': 0, 'sell_rise_pct': 0,
                                    'stop_loss_pct': 3.0} for zn in ZONE_NAMES}
                        tp[zone_name] = {'buy_dip_pct': round(bd, 4),
                                         'sell_rise_pct': round(sr, 4),
                                         'stop_loss_pct': sl}
                        trades = self.simulate_trades(
                            metrics, tp, trade_amount=trade_amount,
                            fee_calculator=fee_calculator)
                        zt = [t for t in trades if t['zone'] == zone_name]
                        total = len(zt)
                        if total < 5:
                            continue
                        avg_net = sum(t['net_profit_pct'] for t in zt) / total
                        wr = len([t for t in zt if t['net_profit_pct'] > 0]) / total * 100
                        slr = len([t for t in zt if t['exit_type'] == 'stop_loss']) / total * 100
                        if best is None or avg_net > best['avg_net_profit']:
                            best = {
                                'best_params': {'buy_dip_pct': round(bd, 4),
                                                'sell_rise_pct': round(sr, 4),
                                                'stop_loss_pct': sl},
                                'avg_net_profit': round(avg_net, 4),
                                'win_rate': round(wr, 2), 'trades_count': total,
                                'stop_loss_rate': round(slr, 2),
                                'profit_spread': round(bd + sr, 4),
                                'searched_combos': searched,
                            }
            if best is None:
                results[zone_name] = self._empty_grid_result()
                results[zone_name]['searched_combos'] = searched
            else:
                best['searched_combos'] = searched
                results[zone_name] = best
        return results

    # ========== 委托到 grid_optimizer ==========

    @staticmethod
    def _generate_range(low: float, high: float, step: float) -> List[float]:
        return _generate_range_fn(low, high, step)

    @staticmethod
    def _empty_grid_result() -> Dict[str, Any]:
        return {'best_params': {'buy_dip_pct': 0, 'sell_rise_pct': 0,
                                'stop_loss_pct': 3.0},
                'avg_net_profit': 0.0, 'win_rate': 0.0, 'trades_count': 0,
                'stop_loss_rate': 0.0, 'profit_spread': 0.0, 'searched_combos': 0}

    # ========== 交易模拟（委托到 trade_simulator） ==========

    def simulate_trades(
        self, metrics: List[Dict[str, Any]],
        trade_params: Dict[str, Dict[str, float]],
        trade_amount: float = 60000.0, fee_calculator: Any = None,
        use_sentiment: bool = False,
        sentiment_adjustments: Optional[Dict[str, Dict[str, float]]] = None,
        enable_open_anchor: bool = False,
        open_anchor_params: Optional[Dict[str, float]] = None,
        enable_open_type_anchor: bool = False,
        open_type_params: Optional[Dict[str, Dict[str, float]]] = None,
        skip_gap_down: bool = False,
    ) -> List[Dict[str, Any]]:
        return _simulate_trades(
            self, metrics, trade_params, trade_amount, fee_calculator,
            use_sentiment, sentiment_adjustments,
            enable_open_anchor, open_anchor_params,
            enable_open_type_anchor, open_type_params, skip_gap_down)

    def simulate_trades_next_day(
        self, metrics: List[Dict[str, Any]],
        trade_params: Dict[str, Dict[str, float]],
        trade_amount: float = 60000.0, fee_calculator: Any = None,
        use_sentiment: bool = False,
        sentiment_adjustments: Optional[Dict[str, Dict[str, float]]] = None,
        enable_open_type_anchor: bool = False,
        open_type_params: Optional[Dict[str, Dict[str, float]]] = None,
        skip_gap_down: bool = False,
    ) -> List[Dict[str, Any]]:
        return _simulate_trades_next_day(
            self, metrics, trade_params, trade_amount, fee_calculator,
            use_sentiment, sentiment_adjustments,
            enable_open_type_anchor, open_type_params, skip_gap_down)

    # ========== BaseBacktestStrategy 接口 ==========

    def check_buy_signal(
        self, stock_code: str, date: str,
        current_kline: Dict[str, Any],
        historical_kline: List[Dict[str, Any]],
    ) -> bool:
        return False

    def check_exit_condition(
        self, buy_date: str, buy_price: float, current_date: str,
        current_kline: Dict[str, Any], future_kline: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {'is_exit': False}

    # ========== 报告生成（委托到 report_generator） ==========

    def generate_analysis_report(
        self, zone_stats: Dict[str, Any],
        trade_params: Dict[str, Dict[str, float]],
        trades: List[Dict[str, Any]], stock_codes: List[str],
        start_date: str, end_date: str,
    ) -> str:
        return _generate_analysis_report(
            self.lookback_days, zone_stats, trade_params, trades,
            stock_codes, start_date, end_date)
