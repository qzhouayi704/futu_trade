#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""规则检查器集合 - 从 DecisionAdvisor 提取的 6 个场景检查函数

每个函数接收所需的数据参数，返回 List[DecisionAdvice]。
"""

import logging
from datetime import datetime
from typing import List, Dict, Any

from .models import (
    AdviceType, Urgency, HealthLevel,
    DecisionAdvice, PositionHealth,
)
from .kline_utils import extract_closes
from ...utils.converters import get_last_price

logger = logging.getLogger(__name__)

# 换仓阈值
SWAP_THRESHOLD_HIGH = 30
SWAP_THRESHOLD_MEDIUM = 20

# 止盈阈值
TAKE_PROFIT_HIGH = 8.0
TAKE_PROFIT_MEDIUM = 6.0

# 加仓条件
ADD_POSITION_MA_TOLERANCE = 0.02

# 模块级计数器
_advice_counter = 0


def _make_advice(**kwargs) -> DecisionAdvice:
    """创建建议对象"""
    global _advice_counter
    _advice_counter += 1
    advice_id = f"adv_{datetime.now().strftime('%H%M%S')}_{_advice_counter}"
    return DecisionAdvice(id=advice_id, **kwargs)


def check_stop_loss(
    health_results: List[PositionHealth],
    quotes_map: Dict[str, Dict],
) -> List[DecisionAdvice]:
    """场景1: 止损检查"""
    advices: List[DecisionAdvice] = []
    for h in health_results:
        quote = quotes_map.get(h.stock_code, {})
        price = get_last_price(quote)

        if h.profit_pct <= -5.0:
            advices.append(_make_advice(
                advice_type=AdviceType.STOP_LOSS,
                urgency=Urgency.CRITICAL,
                title=f"止损: {h.stock_name}",
                description=f"亏损 {h.profit_pct:.1f}%，已触及止损线(-5%)，建议立即清仓",
                sell_stock_code=h.stock_code,
                sell_stock_name=h.stock_name,
                sell_price=price,
                sell_ratio=1.0,
                position_health=h,
            ))
        elif h.profit_pct <= -3.0 and h.trend == "DOWN":
            advices.append(_make_advice(
                advice_type=AdviceType.STOP_LOSS,
                urgency=Urgency.HIGH,
                title=f"快速止损: {h.stock_name}",
                description=f"亏损 {h.profit_pct:.1f}% 且趋势向下，建议止损出局",
                sell_stock_code=h.stock_code,
                sell_stock_name=h.stock_name,
                sell_price=price,
                sell_ratio=1.0,
                position_health=h,
            ))
    return advices


def check_health_advices(
    health_results: List[PositionHealth],
) -> List[DecisionAdvice]:
    """场景2: 根据健康度生成减仓/清仓建议"""
    advices: List[DecisionAdvice] = []
    for h in health_results:
        # 跳过已在止损检查中处理的
        if h.profit_pct <= -3.0 and h.trend == "DOWN":
            continue
        if h.profit_pct <= -5.0:
            continue

        if h.health_level == HealthLevel.DANGER:
            advices.append(_make_advice(
                advice_type=AdviceType.CLEAR,
                urgency=Urgency.HIGH,
                title=f"清仓: {h.stock_name}",
                description=(
                    f"健康度评分 {h.score:.0f} (危险)，"
                    f"{'、'.join(h.reasons[:2])}，建议清仓释放资金"
                ),
                sell_stock_code=h.stock_code,
                sell_stock_name=h.stock_name,
                sell_ratio=1.0,
                position_health=h,
            ))
        elif h.health_level == HealthLevel.WEAK:
            advices.append(_make_advice(
                advice_type=AdviceType.REDUCE,
                urgency=Urgency.MEDIUM,
                title=f"减仓: {h.stock_name}",
                description=(
                    f"健康度评分 {h.score:.0f} (弱势)，"
                    f"{'、'.join(h.reasons[:2])}，建议减仓50%"
                ),
                sell_stock_code=h.stock_code,
                sell_stock_name=h.stock_name,
                sell_ratio=0.5,
                position_health=h,
            ))
    return advices


def calc_opportunity_score(
    signal: Dict[str, Any], quote: Dict[str, Any],
) -> float:
    """计算机会评分（0-100）"""
    # 信号强度 30%
    signal_strength = 70.0

    # 活跃度 30%
    turnover = quote.get('turnover_rate', 0)
    if turnover >= 3.0:
        activity = 100.0
    elif turnover >= 1.0:
        activity = 50.0 + (turnover - 1.0) / 2.0 * 50.0
    else:
        activity = max(0, turnover / 1.0 * 50.0)

    # 振幅 20%
    high = quote.get('high_price', 0)
    low = quote.get('low_price', 0)
    prev = quote.get('prev_close_price', quote.get('last_close_price', 0))
    if prev and prev > 0 and high > 0 and low > 0:
        amp = (high - low) / prev * 100
        amplitude_score = min(100.0, amp * 20)
    else:
        amplitude_score = 50.0

    # 涨跌幅 20%（适度上涨最佳）
    change = quote.get('change_rate', quote.get('change_percent', 0))
    if 1.0 <= change <= 5.0:
        change_score = 100.0
    elif 0 <= change < 1.0:
        change_score = 60.0
    elif change > 5.0:
        change_score = 50.0  # 涨太多追高风险
    else:
        change_score = 30.0

    return (
        signal_strength * 0.3
        + activity * 0.3
        + amplitude_score * 0.2
        + change_score * 0.2
    )


def check_swap_opportunity(
    health_results: List[PositionHealth],
    signals: List[Dict[str, Any]],
    quotes_map: Dict[str, Dict],
) -> List[DecisionAdvice]:
    """场景3: 机会成本分析 - 对比弱势持仓 vs 当天买入信号"""
    advices: List[DecisionAdvice] = []

    weak_positions = [
        h for h in health_results
        if h.health_level in (HealthLevel.WEAK, HealthLevel.DANGER)
    ]
    if not weak_positions:
        return advices

    buy_signals = [
        s for s in signals
        if s.get('signal_type', '').upper() == 'BUY'
        and not s.get('is_executed', False)
    ]
    if not buy_signals:
        return advices

    for signal in buy_signals:
        opp_code = signal.get('stock_code', signal.get('code', ''))
        opp_name = signal.get('stock_name', signal.get('name', ''))
        opp_quote = quotes_map.get(opp_code, {})
        opp_score = calc_opportunity_score(signal, opp_quote)

        for weak in weak_positions:
            delta = opp_score - weak.score
            if delta >= SWAP_THRESHOLD_HIGH:
                urgency = Urgency.HIGH
            elif delta >= SWAP_THRESHOLD_MEDIUM:
                urgency = Urgency.MEDIUM
            else:
                continue

            buy_price = signal.get('signal_price', signal.get('price', 0))
            advices.append(_make_advice(
                advice_type=AdviceType.SWAP,
                urgency=urgency,
                title=f"换仓: {weak.stock_name} → {opp_name}",
                description=(
                    f"{weak.stock_name} 健康度 {weak.score:.0f}，"
                    f"{opp_name} 机会评分 {opp_score:.0f}，"
                    f"差值 {delta:.0f}，建议换仓"
                ),
                sell_stock_code=weak.stock_code,
                sell_stock_name=weak.stock_name,
                sell_ratio=1.0,
                buy_stock_code=opp_code,
                buy_stock_name=opp_name,
                buy_price=buy_price,
                position_health=weak,
            ))
    return advices


def check_add_position(
    health_results: List[PositionHealth],
    quotes_map: Dict[str, Dict],
    kline_cache: Dict[str, List],
) -> List[DecisionAdvice]:
    """场景4: 强势持仓回调到好位置时建议加仓"""
    advices: List[DecisionAdvice] = []
    for h in health_results:
        if h.health_level != HealthLevel.STRONG:
            continue

        klines = kline_cache.get(h.stock_code, [])
        if not klines or len(klines) < 10:
            continue

        # 使用 kline_utils 替换内联提取逻辑
        closes = extract_closes(klines, 10)
        if len(closes) < 10:
            continue
        ma10 = sum(closes) / len(closes)

        quote = quotes_map.get(h.stock_code, {})
        current_price = get_last_price(quote)
        if not current_price or current_price <= 0:
            continue

        deviation = abs(current_price - ma10) / ma10
        if deviation <= ADD_POSITION_MA_TOLERANCE and h.volume_ratio >= 1.0:
            advices.append(_make_advice(
                advice_type=AdviceType.ADD_POSITION,
                urgency=Urgency.MEDIUM,
                title=f"加仓: {h.stock_name}",
                description=(
                    f"强势股回调到MA10附近 (偏离{deviation*100:.1f}%)，"
                    f"量比 {h.volume_ratio:.1f}，趋势仍向上，可考虑加仓"
                ),
                buy_stock_code=h.stock_code,
                buy_stock_name=h.stock_name,
                buy_price=current_price,
                position_health=h,
            ))
    return advices


def check_partial_take_profit(
    positions: List[Dict[str, Any]],
    health_results: List[PositionHealth],
) -> List[DecisionAdvice]:
    """场景5: 盈利到一定程度时建议分批止盈"""
    advices: List[DecisionAdvice] = []
    health_map = {h.stock_code: h for h in health_results}

    for pos in positions:
        code = pos.get('stock_code', pos.get('code', ''))
        h = health_map.get(code)
        if not h:
            continue

        if h.profit_pct >= TAKE_PROFIT_HIGH:
            advices.append(_make_advice(
                advice_type=AdviceType.TAKE_PROFIT,
                urgency=Urgency.HIGH,
                title=f"止盈: {h.stock_name}",
                description=(
                    f"盈利 {h.profit_pct:.1f}% >= {TAKE_PROFIT_HIGH}%，"
                    f"建议卖出50%锁定利润"
                ),
                sell_stock_code=h.stock_code,
                sell_stock_name=h.stock_name,
                sell_ratio=0.5,
                position_health=h,
            ))
        elif h.profit_pct >= TAKE_PROFIT_MEDIUM and h.trend == "UP":
            advices.append(_make_advice(
                advice_type=AdviceType.TAKE_PROFIT,
                urgency=Urgency.MEDIUM,
                title=f"分批止盈: {h.stock_name}",
                description=(
                    f"盈利 {h.profit_pct:.1f}%，趋势仍向上，"
                    f"建议先卖出30%锁定部分利润"
                ),
                sell_stock_code=h.stock_code,
                sell_stock_name=h.stock_name,
                sell_ratio=0.3,
                position_health=h,
            ))
    return advices


def check_holding_time(
    health_results: List[PositionHealth],
) -> List[DecisionAdvice]:
    """场景6: 持仓时间过长且盈利不足"""
    advices: List[DecisionAdvice] = []
    for h in health_results:
        if h.holding_days >= 3 and h.profit_pct < 2.0:
            advices.append(_make_advice(
                advice_type=AdviceType.REDUCE,
                urgency=Urgency.LOW,
                title=f"持仓过久: {h.stock_name}",
                description=(
                    f"持有 {h.holding_days} 天，盈利仅 {h.profit_pct:.1f}%，"
                    f"资金利用效率低，建议考虑减仓"
                ),
                sell_stock_code=h.stock_code,
                sell_stock_name=h.stock_name,
                sell_ratio=0.5,
                position_health=h,
            ))
    return advices
