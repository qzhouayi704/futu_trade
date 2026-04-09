#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
低吸高抛策略 - 窄幅震荡卖出模块

从 swing_strategy.py 中提取的窄幅震荡卖出逻辑。
窄幅震荡卖出条件（需同时满足）：
1. 启用窄幅震荡卖出功能
2. 价格处于相对高位（30日位置 >= 阈值）
3. 近N天平均振幅 < 阈值（窄幅特征）
4. 近N天没有明显上涨（每日涨幅 < 阈值）
"""

import logging
from typing import Dict, Any, List
from dataclasses import dataclass


@dataclass
class NarrowRangeSellCheck:
    """窄幅震荡卖出检查结果"""
    should_sell: bool = False           # 是否应该卖出
    reason: str = ""                    # 卖出原因
    avg_amplitude: float = 0.0          # 平均振幅(%)
    consecutive_low_rise_days: int = 0  # 连续低涨幅天数
    price_position: float = 0.0         # 价格位置(0-100%)
    max_daily_rise_pct: float = 0.0     # 期间最大单日涨幅(%)


class NarrowRangeChecker:
    """窄幅震荡卖出检查器"""

    def __init__(
        self,
        enabled: bool,
        amplitude_threshold: float,
        check_days: int,
        daily_rise_threshold: float,
        min_position: float
    ):
        self.enabled = enabled
        self.amplitude_threshold = amplitude_threshold
        self.check_days = check_days
        self.daily_rise_threshold = daily_rise_threshold
        self.min_position = min_position

    def check(
        self,
        stock_code: str,
        kline_data: List[Dict[str, Any]],
        current_high: float,
        current_low: float,
        price_position_30d: float
    ) -> NarrowRangeSellCheck:
        """检查是否触发窄幅震荡卖出条件"""
        result = NarrowRangeSellCheck()
        result.price_position = price_position_30d

        try:
            # 前置条件检查
            skip_reason = self._check_preconditions(kline_data, price_position_30d)
            if skip_reason:
                result.reason = skip_reason
                return result

            recent_klines = kline_data[-self.check_days:]

            # 条件3：计算平均振幅
            avg_amplitude = self._calc_avg_amplitude(recent_klines)
            if avg_amplitude is None:
                result.reason = "无法计算振幅"
                return result
            result.avg_amplitude = avg_amplitude

            if avg_amplitude >= self.amplitude_threshold:
                result.reason = (
                    f"平均振幅({avg_amplitude:.2f}%)不低于阈值"
                    f"({self.amplitude_threshold:.1f}%)，波动正常"
                )
                return result

            # 条件4：检查每日涨幅
            self._check_daily_rises(result, kline_data, recent_klines)

            if result.consecutive_low_rise_days < self.check_days:
                result.reason = (
                    f"窄幅震荡但有上涨：{self.check_days}天内有"
                    f"{self.check_days - result.consecutive_low_rise_days}天"
                    f"涨幅>={self.daily_rise_threshold:.1f}%，"
                    f"最大单日涨幅{result.max_daily_rise_pct:.2f}%"
                )
                return result

            # 所有条件满足，触发卖出
            result.should_sell = True
            result.reason = (
                f"[!] 窄幅震荡卖出信号：价格位于{price_position_30d:.1f}%高位，"
                f"近{self.check_days}天平均振幅仅{avg_amplitude:.2f}%，"
                f"连续{result.consecutive_low_rise_days}天涨幅"
                f"<{self.daily_rise_threshold:.1f}%，无明显上涨趋势"
            )
            logging.info(
                f"{stock_code} 触发窄幅震荡卖出信号: 位置={price_position_30d:.1f}%, "
                f"平均振幅={avg_amplitude:.2f}%, "
                f"连续低涨幅天数={result.consecutive_low_rise_days}"
            )

        except Exception as e:
            logging.error(f"窄幅震荡卖出检查异常 {stock_code}: {e}")
            result.reason = f"检查异常: {str(e)}"

        return result

    def _check_preconditions(
        self, kline_data: List[Dict[str, Any]], price_position_30d: float
    ) -> str:
        """检查前置条件，返回跳过原因（空字符串表示通过）"""
        if not self.enabled:
            return "窄幅震荡卖出功能未启用"
        if len(kline_data) < self.check_days:
            return f"K线数据不足{self.check_days}天"
        if price_position_30d < self.min_position:
            return (
                f"价格位置({price_position_30d:.1f}%)低于阈值"
                f"({self.min_position:.1f}%)，不考虑窄幅卖出"
            )
        return ""

    def _calc_avg_amplitude(self, recent_klines: List[Dict[str, Any]]) -> float | None:
        """计算近N天平均振幅"""
        amplitudes = []
        for kline in recent_klines:
            low = kline.get('low', 0)
            high = kline.get('high', 0)
            if low > 0:
                amplitude = ((high - low) / low) * 100
                amplitudes.append(amplitude)
        if not amplitudes:
            return None
        return sum(amplitudes) / len(amplitudes)

    def _check_daily_rises(
        self, result: NarrowRangeSellCheck,
        kline_data: List[Dict[str, Any]],
        recent_klines: List[Dict[str, Any]]
    ) -> None:
        """检查每日涨幅（收盘价相对前一日收盘价）"""
        consecutive_low_rise_days = 0
        max_daily_rise_pct = 0.0

        for i, kline in enumerate(recent_klines):
            if i == 0:
                if len(kline_data) > self.check_days:
                    prev_close = kline_data[-(self.check_days + 1)].get('close', 0)
                else:
                    continue
            else:
                prev_close = recent_klines[i - 1].get('close', 0)

            current_close = kline.get('close', 0)
            if prev_close > 0 and current_close > 0:
                daily_rise_pct = ((current_close - prev_close) / prev_close) * 100
                max_daily_rise_pct = max(max_daily_rise_pct, daily_rise_pct)
                if daily_rise_pct < self.daily_rise_threshold:
                    consecutive_low_rise_days += 1
                else:
                    consecutive_low_rise_days = 0

        result.consecutive_low_rise_days = consecutive_low_rise_days
        result.max_daily_rise_pct = max_daily_rise_pct

    def get_conditions(self) -> List[str]:
        """获取窄幅震荡卖出条件列表"""
        if not self.enabled:
            return ["窄幅震荡卖出：已禁用"]
        return [
            f"30日价格位置 >= {self.min_position:.0f}%（处于高位）",
            f"近{self.check_days}天平均振幅 < {self.amplitude_threshold:.1f}%（窄幅震荡）",
            f"连续{self.check_days}天涨幅 < {self.daily_rise_threshold:.1f}%（无明显上涨）"
        ]
