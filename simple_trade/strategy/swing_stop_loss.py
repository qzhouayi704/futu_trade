#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
低吸高抛策略 - 止损检查模块

从 swing_strategy.py 中提取的止损逻辑，包含：
- 亏损止损：当前价格相对买入价格的亏损达到阈值
- 趋势未延续止损：买入后连续N天最高价涨幅低于阈值
"""

import logging
from typing import Dict, Any, List
from dataclasses import dataclass


@dataclass
class StopLossCheck:
    """止损检查结果"""
    should_stop_loss: bool = False      # 是否应该止损
    reason: str = ""                     # 止损原因
    stop_loss_type: str = ""            # 止损类型: 'trend_not_continued' 或 'price_loss'
    days_held: int = 0                   # 持有天数
    return_pct: float = 0.0              # 收益率(%)
    max_rise_pct: float = 0.0            # 最高涨幅(%)
    consecutive_low_rise_days: int = 0   # 连续低涨幅天数


class StopLossChecker:
    """止损检查器"""

    def __init__(
        self,
        stop_loss_pct: float,
        stop_loss_min_rise_pct: float,
        stop_loss_check_days: int
    ):
        self.stop_loss_pct = stop_loss_pct
        self.stop_loss_min_rise_pct = stop_loss_min_rise_pct
        self.stop_loss_check_days = stop_loss_check_days

    def check(
        self,
        stock_code: str,
        buy_price: float,
        buy_date_high: float,
        current_price: float,
        kline_since_buy: List[Dict[str, Any]]
    ) -> StopLossCheck:
        """
        检查是否需要止损

        止损条件（满足任一即触发）：
        1. 亏损止损：当前价格相对买入价格的亏损达到阈值
        2. 趋势未延续：买入后连续N天最高价涨幅 < 阈值
        """
        result = StopLossCheck()

        try:
            if buy_price <= 0 or current_price <= 0:
                result.reason = "价格数据无效"
                return result

            result.days_held = len(kline_since_buy)
            result.return_pct = ((current_price - buy_price) / buy_price) * 100

            # 条件1：亏损止损
            if result.return_pct <= self.stop_loss_pct:
                return self._make_price_loss_result(result, stock_code, buy_price, current_price)

            # 条件2：趋势未延续止损
            if result.days_held >= self.stop_loss_check_days and buy_date_high > 0:
                return self._check_trend_continuation(result, stock_code, buy_date_high, kline_since_buy)

            result.reason = f"持有{result.days_held}天，当前收益{result.return_pct:.1f}%，继续观察"

        except Exception as e:
            logging.error(f"止损检查异常 {stock_code}: {e}")
            result.reason = f"止损检查异常: {str(e)}"

        return result

    def _make_price_loss_result(
        self, result: StopLossCheck, stock_code: str,
        buy_price: float, current_price: float
    ) -> StopLossCheck:
        """构建亏损止损结果"""
        result.should_stop_loss = True
        result.stop_loss_type = 'price_loss'
        result.reason = (
            f"⚠️ 亏损止损：当前亏损{result.return_pct:.1f}%，"
            f"已超过止损阈值{self.stop_loss_pct:.1f}%"
        )
        logging.warning(
            f"{stock_code} 触发亏损止损: 买入价={buy_price:.2f}, "
            f"当前价={current_price:.2f}, 亏损={result.return_pct:.1f}%"
        )
        return result

    def _check_trend_continuation(
        self, result: StopLossCheck, stock_code: str,
        buy_date_high: float, kline_since_buy: List[Dict[str, Any]]
    ) -> StopLossCheck:
        """检查趋势是否延续"""
        consecutive_low_rise_days = 0
        max_rise_pct = 0.0

        for day in kline_since_buy:
            day_high = day.get('high', 0)
            if day_high > 0 and buy_date_high > 0:
                rise_pct = ((day_high - buy_date_high) / buy_date_high) * 100
                max_rise_pct = max(max_rise_pct, rise_pct)
                if rise_pct < self.stop_loss_min_rise_pct:
                    consecutive_low_rise_days += 1
                else:
                    consecutive_low_rise_days = 0

        result.max_rise_pct = max_rise_pct
        result.consecutive_low_rise_days = consecutive_low_rise_days

        if consecutive_low_rise_days >= self.stop_loss_check_days:
            result.should_stop_loss = True
            result.stop_loss_type = 'trend_not_continued'
            result.reason = (
                f"⚠️ 趋势未延续止损：连续{consecutive_low_rise_days}天最高价涨幅 "
                f"< {self.stop_loss_min_rise_pct:.1f}%，最高涨幅仅{max_rise_pct:.1f}%，"
                f"当前收益{result.return_pct:.1f}%"
            )
            logging.warning(
                f"{stock_code} 触发趋势未延续止损: 持有{result.days_held}天, "
                f"连续{consecutive_low_rise_days}天低涨幅, 最高涨幅={max_rise_pct:.1f}%"
            )
        else:
            result.reason = (
                f"持有{result.days_held}天，最高涨幅{max_rise_pct:.1f}%，"
                f"当前收益{result.return_pct:.1f}%"
            )

        return result

    def get_conditions(self) -> List[str]:
        """获取止损条件列表"""
        return [
            f'亏损达到 {abs(self.stop_loss_pct):.1f}%',
            f'连续 {self.stop_loss_check_days} 天最高价涨幅 < {self.stop_loss_min_rise_pct:.1f}%（趋势未延续）'
        ]
