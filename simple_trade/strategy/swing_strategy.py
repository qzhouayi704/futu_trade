#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
低吸高抛交易策略

基于12日高低点的技术分析策略：
- 买入条件：今日最低价 > 昨日最低价 且 昨日最低价 = 近12日最低点
- 卖出条件：今日最高价 < 昨日最高价 且 昨日最高价 = 近12日最高点

模块拆分：
- swing_stop_loss.py: 止损检查逻辑
- swing_narrow_range.py: 窄幅震荡卖出逻辑
- swing_helpers.py: 信号强度计算、策略描述等辅助方法
"""

import logging
from datetime import datetime
from typing import Dict, Any, List
from dataclasses import dataclass

from .base_strategy import BaseStrategy, StrategyResult, ConditionDetail, TradingConditionResult
from .strategy_registry import register_strategy
from .swing_stop_loss import StopLossCheck, StopLossChecker
from .swing_narrow_range import NarrowRangeSellCheck, NarrowRangeChecker
from .swing_helpers import SwingStrategyHelpers, SWING_DEFAULTS


@dataclass
class KlineDateMeta:
    """K线日期验证结果"""
    is_outdated: bool = False       # 是否过期
    warning: str = ''               # 过期警告文本
    days_since_last: int = 0        # 距今自然日数


@register_strategy("swing", is_default=True)
class SwingStrategy(SwingStrategyHelpers, BaseStrategy):
    """
    低吸高抛策略

    继承 BaseStrategy，实现12日高低点策略逻辑。
    止损检查委托给 StopLossChecker，窄幅震荡卖出委托给 NarrowRangeChecker。
    辅助方法（信号强度、策略描述等）由 SwingStrategyHelpers 提供。
    """

    STRATEGY_ID = "swing"
    IS_DEFAULT = True

    def __init__(self, data_service=None, config: Dict[str, Any] = None):
        super().__init__(data_service, config)
        cfg = {k: self.config.get(k, v) for k, v in SWING_DEFAULTS.items()}

        self.lookback_days = cfg['lookback_days']
        self.stop_loss_pct = cfg['stop_loss_pct']
        self.stop_loss_min_rise_pct = cfg['stop_loss_min_rise_pct']
        self.stop_loss_check_days = cfg['stop_loss_check_days']
        self.narrow_range_enabled = cfg['narrow_range_enabled']
        self.narrow_range_amplitude_threshold = cfg['narrow_range_amplitude_threshold']
        self.narrow_range_check_days = cfg['narrow_range_check_days']
        self.narrow_range_daily_rise_threshold = cfg['narrow_range_daily_rise_threshold']
        self.narrow_range_min_position = cfg['narrow_range_min_position']

        self._stop_loss_checker = StopLossChecker(
            self.stop_loss_pct, self.stop_loss_min_rise_pct, self.stop_loss_check_days
        )
        self._narrow_range_checker = NarrowRangeChecker(
            self.narrow_range_enabled, self.narrow_range_amplitude_threshold,
            self.narrow_range_check_days, self.narrow_range_daily_rise_threshold,
            self.narrow_range_min_position
        )

        # 兼容旧版本
        self.strategy_name = self.name
        self.stock_data_service = data_service

    @property
    def name(self) -> str:
        return "低吸高抛策略"

    @property
    def description(self) -> str:
        return f"基于{self.lookback_days}日高低点的低吸高抛策略"

    # ==================== 核心信号检查 ====================

    def check_signals(
        self,
        stock_code: str,
        quote_data: Dict[str, Any],
        kline_data: List[Dict[str, Any]]
    ) -> StrategyResult:
        """检查低吸高抛策略信号（核心入口：协调买卖信号检查）"""
        result = StrategyResult(stock_code=stock_code)

        try:
            if len(kline_data) < self.lookback_days:
                result.buy_reason = '数据不足，无法判断'
                result.sell_reason = '数据不足，无法判断'
                return result

            current_high = quote_data.get('high_price', 0)
            current_low = quote_data.get('low_price', 0)
            yesterday = kline_data[-1]
            kline_meta = self._validate_kline_date(yesterday)

            # 计算近N日极值
            past_days = kline_data[:-1] if len(kline_data) > 1 else kline_data
            past_highs = [day['high'] for day in past_days]
            past_lows = [day['low'] for day in past_days]
            max_high_nd = max(past_highs + [yesterday['high']]) if past_highs else yesterday['high']
            min_low_nd = min(past_lows + [yesterday['low']]) if past_lows else yesterday['low']

            self._check_buy_signal(result, current_low, yesterday, min_low_nd)
            self._check_sell_signal(result, current_high, yesterday, max_high_nd)

            if kline_meta.is_outdated:
                result.buy_reason = kline_meta.warning + result.buy_reason
                result.sell_reason = kline_meta.warning + result.sell_reason

            price_pos_30d, max_high_30d, min_low_30d = self._calculate_price_position_30d(
                kline_data, current_high, current_low
            )

            # 窄幅震荡卖出（仅在传统卖出未触发时检查）
            narrow_check = None
            if not result.sell_signal:
                narrow_check = self._check_narrow_range_sell_signal(
                    result, stock_code, kline_data, current_high, current_low, price_pos_30d
                )

            result.strategy_data = self._build_strategy_data(
                current_high, current_low, yesterday, max_high_nd, min_low_nd,
                kline_data, kline_meta, price_pos_30d, max_high_30d, min_low_30d, narrow_check
            )

        except Exception as e:
            logging.error(f"检查低吸高抛策略失败 {stock_code}: {e}")
            result.buy_reason = f'策略检查异常: {str(e)}'
            result.sell_reason = f'策略检查异常: {str(e)}'

        return result

    # ==================== check_signals 子方法 ====================

    def _validate_kline_date(self, yesterday_kline: Dict[str, Any]) -> KlineDateMeta:
        """基于自然日间隔判断K线是否过期（>5天过期，0-5天正常）"""
        meta = KlineDateMeta()
        kline_date_str = yesterday_kline.get('date', '')
        if not kline_date_str:
            return meta
        try:
            kline_date = datetime.strptime(kline_date_str.split()[0], '%Y-%m-%d').date()
            today = datetime.now().date()
            meta.days_since_last = (today - kline_date).days
            if meta.days_since_last > 5:
                meta.is_outdated = True
                meta.warning = f'[K线过期:{kline_date_str},距今{meta.days_since_last}天] '
        except Exception:
            pass
        return meta

    def _check_buy_signal(
        self, result: StrategyResult,
        current_low: float, yesterday: Dict[str, Any], min_low_nd: float
    ) -> None:
        """低吸买入信号检查：当天最低价 > 昨日最低价 且 昨日最低价是近N日最低点"""
        cond1 = current_low > yesterday['low']
        cond2 = yesterday['low'] == min_low_nd
        yd_low = yesterday['low']
        n = self.lookback_days

        if cond1 and cond2:
            result.buy_signal = True
            result.buy_reason = f'低吸信号：今日最低价({current_low:.2f}) > 昨日最低价({yd_low:.2f})，且昨日最低价为{n}日最低点'
        elif cond1:
            result.buy_reason = f'今日最低价({current_low:.2f}) > 昨日最低价({yd_low:.2f})，但昨日最低价({yd_low:.2f})不是{n}日最低点({min_low_nd:.2f})'
        elif cond2:
            rel = "持平" if current_low == yd_low else "低于"
            sym = "=" if current_low == yd_low else "<"
            result.buy_reason = f'昨日最低价({yd_low:.2f})是{n}日最低点，但今日最低价({current_low:.2f}) {sym} 昨日最低价（{rel}）'
        else:
            result.buy_reason = f'不满足买入条件：今日低({current_low:.2f}) vs 昨日低({yd_low:.2f})，{n}日最低({min_low_nd:.2f})'

    def _check_sell_signal(
        self, result: StrategyResult,
        current_high: float, yesterday: Dict[str, Any], max_high_nd: float
    ) -> None:
        """高抛卖出信号检查：当天最高价 < 昨日最高价 且 昨日最高价是近N日最高点"""
        cond1 = current_high < yesterday['high']
        cond2 = yesterday['high'] == max_high_nd
        yd_high = yesterday['high']
        n = self.lookback_days

        if cond1 and cond2:
            result.sell_signal = True
            result.sell_reason = f'高抛信号：今日最高价({current_high:.2f}) < 昨日最高价({yd_high:.2f})，且昨日最高价为{n}日最高点'
        elif cond1:
            result.sell_reason = f'今日最高价({current_high:.2f}) < 昨日最高价({yd_high:.2f})，但昨日最高价({yd_high:.2f})不是{n}日最高点({max_high_nd:.2f})'
        elif cond2:
            rel = "持平" if current_high == yd_high else "高于"
            sym = "=" if current_high == yd_high else ">"
            result.sell_reason = f'昨日最高价({yd_high:.2f})是{n}日最高点，但今日最高价({current_high:.2f}) {sym} 昨日最高价（{rel}）'
        else:
            result.sell_reason = f'不满足卖出条件：今日高({current_high:.2f}) vs 昨日高({yd_high:.2f})，{n}日最高({max_high_nd:.2f})'

    def _calculate_price_position_30d(
        self, kline_data: List[Dict[str, Any]],
        current_high: float, current_low: float
    ) -> tuple:
        """计算30日价格位置，返回 (position, max_high, min_low)"""
        price_pos = 50.0
        max_h = 0.0
        min_l = 0.0

        if len(kline_data) >= 30:
            source = kline_data[-30:]
        elif len(kline_data) >= 12:
            source = kline_data
        else:
            return price_pos, max_h, min_l

        highs = [d['high'] for d in source if d.get('high', 0) > 0]
        lows = [d['low'] for d in source if d.get('low', 0) > 0]

        if highs and lows:
            max_h = max(highs)
            min_l = min(lows)
            if max_h > min_l:
                avg = (current_high + current_low) / 2 if current_high > 0 and current_low > 0 else 0
                if avg > 0:
                    price_pos = ((avg - min_l) / (max_h - min_l)) * 100
                    price_pos = max(0, min(100, price_pos))

        return price_pos, max_h, min_l

    def _check_narrow_range_sell_signal(
        self, result: StrategyResult, stock_code: str,
        kline_data: List[Dict[str, Any]],
        current_high: float, current_low: float,
        price_position_30d: float
    ) -> 'NarrowRangeSellCheck | None':
        """窄幅震荡卖出检查（协调调用 NarrowRangeChecker）"""
        if not self.narrow_range_enabled:
            return None
        check = self.check_narrow_range_sell(
            stock_code=stock_code, kline_data=kline_data,
            current_high=current_high, current_low=current_low,
            price_position_30d=price_position_30d
        )
        if check.should_sell:
            result.sell_signal = True
            result.sell_reason = check.reason
        return check

    def _build_strategy_data(
        self, current_high, current_low, yesterday, max_high_nd, min_low_nd,
        kline_data, kline_meta, price_pos_30d, max_high_30d, min_low_30d,
        narrow_check
    ) -> Dict[str, Any]:
        """构建策略数据字典"""
        data = {
            'today_high': current_high, 'today_low': current_low,
            'yesterday_high': yesterday['high'], 'yesterday_low': yesterday['low'],
            'max_high_nd': max_high_nd, 'min_low_nd': min_low_nd,
            'kline_count': len(kline_data), 'lookback_days': self.lookback_days,
            'kline_last_date': yesterday.get('date', ''),
            'kline_outdated': kline_meta.is_outdated,
            'kline_days_since_last': kline_meta.days_since_last,
            'price_position_30d': round(price_pos_30d, 1),
            'max_high_30d': max_high_30d, 'min_low_30d': min_low_30d,
        }
        if narrow_check:
            data['narrow_range_check'] = {
                'enabled': self.narrow_range_enabled,
                'triggered': narrow_check.should_sell,
                'avg_amplitude': narrow_check.avg_amplitude,
                'consecutive_low_rise_days': narrow_check.consecutive_low_rise_days,
                'reason': narrow_check.reason
            }
        else:
            data['narrow_range_check'] = None
        return data

    # ==================== 委托给子检查器 ====================

    def check_stop_loss(self, stock_code, buy_price, buy_date_high, current_price, kline_since_buy) -> StopLossCheck:
        """检查是否需要止损（委托给 StopLossChecker）"""
        return self._stop_loss_checker.check(stock_code, buy_price, buy_date_high, current_price, kline_since_buy)

    def get_stop_loss_conditions(self) -> List[str]:
        return self._stop_loss_checker.get_conditions()

    def check_narrow_range_sell(self, stock_code, kline_data, current_high, current_low, price_position_30d) -> NarrowRangeSellCheck:
        """检查是否触发窄幅震荡卖出条件（委托给 NarrowRangeChecker）"""
        return self._narrow_range_checker.check(stock_code, kline_data, current_high, current_low, price_position_30d)

    def get_narrow_range_sell_conditions(self) -> List[str]:
        return self._narrow_range_checker.get_conditions()
