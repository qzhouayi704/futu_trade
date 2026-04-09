#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
趋势反转交易策略

基于趋势反转的买卖点识别：
- 买点：下跌后出现放量反弹 + 阳线反转
- 卖点：上涨后出现回落 + 阴线反转
- 止损：固定阈值 + 市场环境加速 + 趋势未延续
"""

import logging
from typing import Dict, Any, List, Optional

from ..base_strategy import BaseStrategy, StrategyResult
from ..strategy_registry import register_strategy
from .models import TrendAnalysis, StopLossCheck
from .analysis import analyze_trend, analyze_plate_sentiment, adjust_signal_by_sentiment


@register_strategy("trend_reversal", is_default=False)
class TrendReversalStrategy(BaseStrategy):
    """趋势反转策略"""

    STRATEGY_ID = "trend_reversal"
    IS_DEFAULT = False

    # 默认参数
    DEFAULT_LOOKBACK_DAYS = 10
    DEFAULT_MIN_DROP_PCT = 8.0
    DEFAULT_MIN_RISE_PCT = 10.0
    DEFAULT_MIN_REVERSAL_PCT = 2.0
    DEFAULT_MAX_UP_RATIO_BUY = 0.4
    DEFAULT_MIN_UP_RATIO_SELL = 0.6
    DEFAULT_STOP_LOSS_PCT = -5.0
    DEFAULT_STOP_LOSS_DAYS = 3

    def __init__(self, data_service=None, config: Dict[str, Any] = None):
        super().__init__(data_service, config)
        self.lookback_days = self.config.get('lookback_days', self.DEFAULT_LOOKBACK_DAYS)
        self.min_drop_pct = self.config.get('min_drop_pct', self.DEFAULT_MIN_DROP_PCT)
        self.min_rise_pct = self.config.get('min_rise_pct', self.DEFAULT_MIN_RISE_PCT)
        self.min_reversal_pct = self.config.get('min_reversal_pct', self.DEFAULT_MIN_REVERSAL_PCT)
        self.max_up_ratio_buy = self.config.get('max_up_ratio_buy', self.DEFAULT_MAX_UP_RATIO_BUY)
        self.min_up_ratio_sell = self.config.get('min_up_ratio_sell', self.DEFAULT_MIN_UP_RATIO_SELL)
        self.stop_loss_pct = self.config.get('stop_loss_pct', self.DEFAULT_STOP_LOSS_PCT)
        self.stop_loss_days = self.config.get('stop_loss_days', self.DEFAULT_STOP_LOSS_DAYS)
        self.min_turnover_rate = self.config.get('min_turnover_rate', 0.1)

        # 兼容旧版本
        self.strategy_name = self.name
        self.stock_data_service = data_service

        logging.info(
            f"趋势反转策略初始化: lookback={self.lookback_days}, "
            f"min_drop={self.min_drop_pct}%, min_rise={self.min_rise_pct}%"
        )

    @property
    def name(self) -> str:
        return "趋势反转策略"

    @property
    def description(self) -> str:
        return f"基于{self.lookback_days}日趋势反转的买卖点识别策略"

    # ==================== 信号检查 ====================

    def check_signals(
        self,
        stock_code: str,
        quote_data: Dict[str, Any],
        kline_data: List[Dict[str, Any]],
    ) -> StrategyResult:
        """检查趋势反转策略信号"""
        result = StrategyResult(stock_code=stock_code)

        try:
            current_price = quote_data.get('last_price', 0)
            current_high = quote_data.get('high_price', 0)
            current_low = quote_data.get('low_price', 0)
            current_open = quote_data.get('open_price', 0)

            if len(kline_data) < self.lookback_days:
                result.buy_reason = f'数据不足，需要{self.lookback_days}天数据，当前{len(kline_data)}天'
                result.sell_reason = result.buy_reason
                return result

            lookback_data = kline_data[-self.lookback_days:]
            trend = analyze_trend(lookback_data, current_price, current_high, current_low, current_open)
            trend.turnover_rate = quote_data.get('turnover_rate', 0)

            result.buy_signal, result.buy_reason = self._check_buy_signal(trend, stock_code)
            result.sell_signal, result.sell_reason = self._check_sell_signal(trend, stock_code)

            result.strategy_data = {
                'current_price': current_price,
                'current_high': current_high,
                'current_low': current_low,
                'period_high': trend.period_high,
                'period_low': trend.period_low,
                'up_days': trend.up_days,
                'down_days': trend.down_days,
                'up_ratio': trend.up_ratio,
                'drop_from_high': trend.drop_from_high,
                'rise_from_low': trend.rise_from_low,
                'trend_direction': trend.trend_direction,
                'reversal_signal': trend.reversal_signal,
                'kline_count': len(kline_data),
                'lookback_days': self.lookback_days,
                'volume_trend': trend.volume_trend,
                'avg_volume_ratio': round(trend.avg_volume_ratio, 2),
                'reversal_volume_ratio': round(trend.reversal_volume_ratio, 2),
                'turnover_rate': trend.turnover_rate,
            }

        except Exception as e:
            logging.error(f"检查趋势反转策略失败 {stock_code}: {e}")
            result.buy_reason = f'策略检查异常: {str(e)}'
            result.sell_reason = f'策略检查异常: {str(e)}'

        return result

    # ==================== 买卖信号判断 ====================

    def _check_buy_signal(self, trend: TrendAnalysis, stock_code: str) -> tuple:
        """检查买入信号 (6个条件，核心条件2+3必须满足，总共满足4个即可)"""
        reasons = []
        conditions_met = 0
        total_conditions = 6

        # 条件1：下跌天数占比高
        c1 = trend.down_ratio >= (1 - self.max_up_ratio_buy)
        if c1:
            conditions_met += 1
            reasons.append(f"✅ 下跌天数{trend.down_days}天({trend.down_ratio:.0%})")
        else:
            reasons.append(f"❌ 下跌天数{trend.down_days}天({trend.down_ratio:.0%})，需≥{1-self.max_up_ratio_buy:.0%}")

        # 条件2（核心）：距最高点有明显跌幅
        c2 = trend.drop_from_high >= self.min_drop_pct
        if c2:
            conditions_met += 1
            reasons.append(f"✅ 距最高点跌幅{trend.drop_from_high:.1f}%")
        else:
            reasons.append(f"❌ 距最高点跌幅{trend.drop_from_high:.1f}%，需≥{self.min_drop_pct:.1f}%")

        # 条件3（核心）：出现反弹信号
        c3 = trend.rise_from_low >= self.min_reversal_pct
        if c3:
            conditions_met += 1
            reasons.append(f"✅ 反弹信号{trend.rise_from_low:.1f}%")
        else:
            reasons.append(f"❌ 反弹信号{trend.rise_from_low:.1f}%，需≥{self.min_reversal_pct:.1f}%")

        # 条件4：今日阳线反转
        c4 = trend.is_buy_reversal
        if c4:
            conditions_met += 1
            reasons.append("✅ 今日出现阳线反转")
        else:
            reasons.append("❌ 今日未出现阳线反转")

        # 条件5：反弹伴随放量
        c5 = trend.reversal_volume_ratio >= 1.2
        if c5:
            conditions_met += 1
            reasons.append(f"✅ 反弹放量 {trend.reversal_volume_ratio:.1f}x")
        else:
            reasons.append(f"❌ 反弹量比 {trend.reversal_volume_ratio:.1f}x，需≥1.2x")

        # 条件6：换手率达标
        c6 = trend.turnover_rate >= self.min_turnover_rate
        if c6:
            conditions_met += 1
            reasons.append(f"✅ 换手率 {trend.turnover_rate:.2f}%")
        else:
            reasons.append(f"❌ 换手率 {trend.turnover_rate:.2f}%，需≥{self.min_turnover_rate}%")

        signal = conditions_met >= 4 and c2 and c3

        if signal:
            reason = "🔔 买入信号: " + ", ".join([r for r in reasons if r.startswith("✅")])
        else:
            reason = f"条件({conditions_met}/{total_conditions}): " + " | ".join(reasons)

        return signal, reason

    def _check_sell_signal(self, trend: TrendAnalysis, stock_code: str) -> tuple:
        """检查卖出信号"""
        reasons = []
        conditions_met = 0
        total_conditions = 4

        c1 = trend.up_ratio >= self.min_up_ratio_sell
        if c1:
            conditions_met += 1
            reasons.append(f"✅ 上涨天数{trend.up_days}天({trend.up_ratio:.0%})")
        else:
            reasons.append(f"❌ 上涨天数{trend.up_days}天({trend.up_ratio:.0%})，需≥{self.min_up_ratio_sell:.0%}")

        c2 = trend.rise_from_low >= self.min_rise_pct
        if c2:
            conditions_met += 1
            reasons.append(f"✅ 距最低点涨幅{trend.rise_from_low:.1f}%")
        else:
            reasons.append(f"❌ 距最低点涨幅{trend.rise_from_low:.1f}%，需≥{self.min_rise_pct:.1f}%")

        c3 = trend.drop_from_high >= self.min_reversal_pct
        if c3:
            conditions_met += 1
            reasons.append(f"✅ 回落信号{trend.drop_from_high:.1f}%")
        else:
            reasons.append(f"❌ 回落信号{trend.drop_from_high:.1f}%，需≥{self.min_reversal_pct:.1f}%")

        c4 = trend.is_sell_reversal
        if c4:
            conditions_met += 1
            reasons.append("✅ 今日出现阴线反转")
        else:
            reasons.append("❌ 今日未出现阴线反转")

        signal = conditions_met >= 3 and c2 and c3

        if signal:
            reason = "🔔 卖出信号: " + ", ".join([r for r in reasons if r.startswith("✅")])
        else:
            reason = f"条件({conditions_met}/{total_conditions}): " + " | ".join(reasons)

        return signal, reason

    # ==================== 止损检查 ====================

    def check_stop_loss(
        self,
        stock_code: str,
        buy_price: float,
        buy_date: str,
        current_data: Dict[str, Any],
        kline_since_buy: List[Dict[str, Any]],
        market_context: Optional[Dict[str, Any]] = None,
    ) -> StopLossCheck:
        """检查是否需要止损

        Args:
            stock_code: 股票代码
            buy_price: 买入价格
            buy_date: 买入日期
            current_data: 当前行情数据
            kline_since_buy: 买入后的K线数据
            market_context: 市场环境数据（可选），包含:
                - market_change_pct: 大盘涨跌幅(%)
                - volume_ratio: 量比
                - change_pct: 个股当日涨跌幅(%)
        """
        result = StopLossCheck()

        try:
            current_price = current_data.get('last_price', 0)
            if buy_price <= 0 or current_price <= 0:
                return result

            result.return_pct = ((current_price - buy_price) / buy_price) * 100
            result.days_held = len(kline_since_buy)

            # 条件1：跌幅超过止损阈值
            if result.return_pct <= self.stop_loss_pct:
                result.should_stop_loss = True
                result.reason = f"⚠️ 跌幅{result.return_pct:.1f}%已超过止损阈值{self.stop_loss_pct:.1f}%"
                return result

            # 条件1.5：市场环境加速止损
            if self._check_market_env_stop_loss(result, current_data, market_context):
                return result

            # 条件2：持有N天后趋势未延续
            if result.days_held >= self.stop_loss_days:
                up_days = sum(1 for d in kline_since_buy if d.get('close', 0) > d.get('open', 0))
                up_ratio = up_days / result.days_held if result.days_held > 0 else 0

                if up_ratio < 0.4:
                    result.should_stop_loss = True
                    result.trend_continued = False
                    result.reason = (
                        f"⚠️ 持有{result.days_held}天后趋势未延续，"
                        f"上涨仅{up_days}天({up_ratio:.0%})，当前收益{result.return_pct:.1f}%"
                    )
                else:
                    result.trend_continued = True
                    result.reason = f"趋势延续中，上涨{up_days}天({up_ratio:.0%})，收益{result.return_pct:.1f}%"
            else:
                result.reason = f"持有{result.days_held}天，收益{result.return_pct:.1f}%，继续观察"

        except Exception as e:
            logging.error(f"止损检查异常 {stock_code}: {e}")
            result.reason = f"止损检查异常: {str(e)}"

        return result

    def _check_market_env_stop_loss(
        self,
        result: StopLossCheck,
        current_data: Dict[str, Any],
        market_context: Optional[Dict[str, Any]],
    ) -> bool:
        """检查市场环境是否触发加速止损"""
        if not market_context:
            return False

        # 大盘暴跌加速止损：大盘跌幅 > 2% 时，止损阈值收紧 50%
        market_change = market_context.get('market_change_pct', 0)
        if market_change < -2.0:
            effective_stop = self.stop_loss_pct * 0.5
            if result.return_pct <= effective_stop:
                result.should_stop_loss = True
                result.reason = (
                    f"⚠️ 大盘暴跌({market_change:.1f}%)，"
                    f"加速止损阈值{effective_stop:.1f}%，当前收益{result.return_pct:.1f}%"
                )
                return True

        # 放量下跌立即止损：量比 > 2 且跌幅 > 3% 且已亏损
        vol_ratio = current_data.get('volume_ratio', market_context.get('volume_ratio', 1.0))
        change_pct = current_data.get('change_pct', market_context.get('change_pct', 0))
        if vol_ratio > 2.0 and change_pct < -3.0 and result.return_pct < 0:
            result.should_stop_loss = True
            result.reason = (
                f"⚠️ 放量下跌(量比{vol_ratio:.1f}x, 跌{change_pct:.1f}%)，"
                f"当前收益{result.return_pct:.1f}%，立即止损"
            )
            return True

        return False

    # ==================== 条件描述与信号强度 ====================

    def get_buy_conditions(self) -> List[str]:
        return [
            f'近{self.lookback_days}日下跌天数占比 ≥ {(1-self.max_up_ratio_buy)*100:.0f}%',
            f'距期间最高点跌幅 ≥ {self.min_drop_pct:.1f}%',
            f'反弹信号（距最低点涨幅）≥ {self.min_reversal_pct:.1f}%',
            '今日K线为阳线（反转确认）',
            '反弹日成交量 ≥ 下跌日均量 × 1.2（放量确认）',
            f'换手率 ≥ {self.min_turnover_rate}%（流动性确认）',
        ]

    def get_sell_conditions(self) -> List[str]:
        return [
            f'近{self.lookback_days}日上涨天数占比 ≥ {self.min_up_ratio_sell*100:.0f}%',
            f'距期间最低点涨幅 ≥ {self.min_rise_pct:.1f}%',
            f'回落信号（距最高点跌幅）≥ {self.min_reversal_pct:.1f}%',
            '今日K线为阴线（反转确认）',
        ]

    def get_stop_loss_conditions(self) -> List[str]:
        return [
            f'跌幅超过 {abs(self.stop_loss_pct):.1f}%',
            f'持有 {self.stop_loss_days} 天后趋势未延续（上涨天数 < 40%）',
            '大盘暴跌(>2%)时止损阈值收紧50%',
            '放量下跌(量比>2x且跌>3%)时立即止损',
        ]

    def get_required_kline_days(self) -> int:
        return self.lookback_days

    def calculate_signal_strength(self, result: StrategyResult) -> float:
        """计算信号强度（0-1之间）"""
        try:
            strength = 0.0
            strategy_data = result.strategy_data

            if result.has_signal:
                strength += 0.3

            kline_count = strategy_data.get('kline_count', 0)
            if kline_count >= self.lookback_days:
                strength += 0.1

            if result.buy_signal:
                drop = strategy_data.get('drop_from_high', 0)
                rise = strategy_data.get('rise_from_low', 0)
                strength += 0.15 if drop >= self.min_drop_pct * 1.5 else (0.08 if drop >= self.min_drop_pct else 0)
                strength += 0.15 if rise >= self.min_reversal_pct * 2 else (0.08 if rise >= self.min_reversal_pct else 0)
            elif result.sell_signal:
                rise = strategy_data.get('rise_from_low', 0)
                drop = strategy_data.get('drop_from_high', 0)
                strength += 0.15 if rise >= self.min_rise_pct * 1.5 else (0.08 if rise >= self.min_rise_pct else 0)
                strength += 0.15 if drop >= self.min_reversal_pct * 2 else (0.08 if drop >= self.min_reversal_pct else 0)

            # 量价确认加分
            vol_ratio = strategy_data.get('reversal_volume_ratio', 1.0)
            if vol_ratio >= 1.5:
                strength += 0.15
            elif vol_ratio >= 1.2:
                strength += 0.08
            elif vol_ratio < 0.8:
                strength -= 0.1

            return max(min(strength, 1.0), 0.0)

        except Exception as e:
            logging.error(f"计算信号强度失败: {e}")
            return 0.0

    # ==================== 板块情绪（委托给 analysis 模块） ====================

    def analyze_plate_sentiment(self, plate_stocks_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        return analyze_plate_sentiment(plate_stocks_data)

    def adjust_signal_by_sentiment(self, signal_type: str, plate_sentiment: Dict[str, Any]) -> float:
        return adjust_signal_by_sentiment(signal_type, plate_sentiment)

    def get_strategy_description(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'description': self.description,
            'buy_conditions': self.get_buy_conditions(),
            'sell_conditions': self.get_sell_conditions(),
            'stop_loss_conditions': self.get_stop_loss_conditions(),
            'parameters': {
                'lookback_days': self.lookback_days,
                'min_drop_pct': self.min_drop_pct,
                'min_rise_pct': self.min_rise_pct,
                'min_reversal_pct': self.min_reversal_pct,
                'max_up_ratio_buy': self.max_up_ratio_buy,
                'min_up_ratio_sell': self.min_up_ratio_sell,
                'stop_loss_pct': self.stop_loss_pct,
                'stop_loss_days': self.stop_loss_days,
            },
            'risk_notice': '该策略基于趋势反转分析，存在投资风险，仅供参考',
        }
