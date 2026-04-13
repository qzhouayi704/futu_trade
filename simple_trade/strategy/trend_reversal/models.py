#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""趋势反转策略 - 数据模型"""

from dataclasses import dataclass


@dataclass
class TrendAnalysis:
    """趋势分析结果"""
    # 基础统计
    up_days: int = 0              # 上涨天数（收盘>开盘）
    down_days: int = 0            # 下跌天数（收盘<开盘）
    flat_days: int = 0            # 平盘天数
    up_ratio: float = 0.0         # 上涨天数比例
    down_ratio: float = 0.0       # 下跌天数比例

    # 价格位置
    period_high: float = 0.0      # 期间最高价
    period_low: float = 0.0       # 期间最低价
    current_price: float = 0.0    # 当前价格
    drop_from_high: float = 0.0   # 距最高点跌幅(%)
    rise_from_low: float = 0.0    # 距最低点涨幅(%)

    # 趋势指标
    trend_direction: str = ""     # 趋势方向: UP/DOWN/SIDEWAYS
    trend_strength: float = 0.0   # 趋势强度
    reversal_signal: float = 0.0  # 反转信号强度

    # 反转确认
    is_buy_reversal: bool = False   # 是否买入反转信号
    is_sell_reversal: bool = False  # 是否卖出反转信号

    # 量价分析
    volume_trend: str = ""              # 成交量趋势: SHRINK_DOWN / EXPAND_UP / MIXED
    avg_volume_ratio: float = 1.0       # 近期成交量 / 历史均量
    reversal_volume_ratio: float = 1.0  # 反弹日成交量 / 下跌日均量
    turnover_rate: float = 0.0          # 当日换手率(%)


@dataclass
class StopLossCheck:
    """止损/卖出检查结果"""
    should_stop_loss: bool = False  # 是否应该卖出
    reason: str = ""                 # 卖出原因
    days_held: int = 0               # 持有天数
    return_pct: float = 0.0          # 当前收益率
    trend_continued: bool = True     # 趋势是否延续
    # 追踪止盈
    peak_return_pct: float = 0.0     # 持有期间最高收益率
    trailing_activated: bool = False # 追踪止盈是否已激活
    drawdown_pct: float = 0.0       # 从峰值的回撤幅度(%)
    exit_type: str = ""              # 退出类型: stop_loss/trailing/high_throw/trend_fail/timeout

