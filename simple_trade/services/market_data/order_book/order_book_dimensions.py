#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
盘口分析 - 5维度分析函数

从 order_book_analyzer.py 拆分出来，保持单文件不超过 400 行。
"""

from typing import Any, Dict

from .order_book_analyzer import (
    DIM_NAMES,
    SIGNAL_NEUTRAL,
    DimensionSignal,
    _clamp,
    _score_to_signal,
)

from ....utils.converters import get_last_price


# ==================== 维度1: 盘口深度 (30%) ====================


def analyze_order_book_depth(ob, sr: dict, big_data) -> DimensionSignal:
    """分析盘口深度：挂单分布 + 主动买卖"""
    score = 0.0
    details: Dict[str, Any] = {}

    # 因子1: 买卖失衡度 (40分)
    imb = ob.imbalance
    score += imb * 40
    details['imbalance'] = imb

    # 因子2: 买一/卖一量比 (30分)
    if ob.bid_levels and ob.ask_levels:
        b1 = ob.bid_levels[0].volume
        a1 = ob.ask_levels[0].volume
        total = b1 + a1
        if total > 0:
            ratio = (b1 - a1) / total
            score += ratio * 30
            details['bid1_ask1_ratio'] = round(ratio, 3)

    # 因子3: 支撑/阻力量比 (20分)
    sup = sr.get('support')
    res = sr.get('resistance')
    if sup and res:
        sv, rv = sup['volume'], res['volume']
        total = sv + rv
        if total > 0:
            sr_ratio = (sv - rv) / total
            score += sr_ratio * 20
            details['support_resistance_ratio'] = round(sr_ratio, 3)

    # 因子4: 大单主动买卖 (10分)
    if big_data:
        strength = big_data.get('order_strength', 0)
        score += strength * 10
        details['active_buy_ratio'] = round(
            big_data.get('buy_sell_ratio', 1.0), 2
        )

    score = _clamp(score)
    desc = _depth_description(score, details)
    return DimensionSignal(
        name=DIM_NAMES[0], signal=_score_to_signal(score),
        score=round(score, 1), description=desc, details=details,
    )


def _depth_description(score: float, details: dict) -> str:
    if score > 25:
        return "买盘力量占优" + ("，主动买入密集" if details.get('active_buy_ratio', 1) > 1.5 else "")
    if score > 10:
        return "买盘略强"
    if score > -10:
        return "买卖力量均衡"
    if score > -25:
        return "卖盘略强"
    return "卖盘力量占优" + ("，主动卖出密集" if details.get('active_buy_ratio', 1) < 0.5 else "")


# ==================== 维度2: 量价关系 (25%) ====================


def analyze_volume_price(quote: dict) -> DimensionSignal:
    """分析量价关系：放量突破/缩量反弹/高位滞涨/低位不跌 + 换手率交叉验证"""
    vol_ratio = quote.get('volume_ratio', 1.0) or 1.0
    change_pct = quote.get('change_rate', 0) or quote.get('change_pct', 0) or 0
    price_pos = quote.get('price_position', 50)
    turnover_rate = quote.get('turnover_rate', 0) or 0
    if price_pos is None or price_pos < 0:
        price_pos = 50

    score = 0.0
    pattern = "震荡"
    details: Dict[str, Any] = {
        'volume_ratio': round(vol_ratio, 2),
        'change_pct': round(change_pct, 2),
        'price_position': price_pos,
        'turnover_rate': round(turnover_rate, 4),
    }

    # 高位爆量滞涨 → 主力派发
    if vol_ratio > 2.0 and price_pos > 80 and abs(change_pct) < 1:
        score = -60
        pattern = "高位爆量滞涨"
    # 低位爆量不跌 → 底部承接
    elif vol_ratio > 2.0 and price_pos < 20 and change_pct > -1:
        score = 60
        pattern = "低位爆量不跌"
    # 放量突破
    elif vol_ratio > 1.5 and change_pct > 2:
        score = 50
        pattern = "放量突破"
    # 放量下跌
    elif vol_ratio > 1.5 and change_pct < -2:
        score = -50
        pattern = "放量下跌"
    # 缩量反弹 → 死猫跳
    elif vol_ratio < 0.5 and change_pct > 0:
        score = -20
        pattern = "缩量反弹"
    # 缩量下跌 → 抛压减轻
    elif vol_ratio < 0.5 and change_pct < 0:
        score = 10
        pattern = "缩量下跌"
    # 温和放量上涨
    elif vol_ratio > 1.0 and change_pct > 0:
        score = 20
        pattern = "温和放量上涨"
    # 温和放量下跌
    elif vol_ratio > 1.0 and change_pct < 0:
        score = -20
        pattern = "温和放量下跌"

    # 换手率交叉验证：区分"真放量"和"大单异常"
    if turnover_rate > 0 and vol_ratio > 1.5:
        if turnover_rate < 0.005:
            # 高量比 + 低换手率 → 可能是少数大单导致，评分打 6 折
            score *= 0.6
            details['turnover_adjustment'] = '低换手率折扣'
        elif turnover_rate > 0.02:
            # 高量比 + 高换手率 → 真实资金大规模进出，评分加 20%
            score *= 1.2
            details['turnover_adjustment'] = '高换手率加成'

    score = _clamp(score)
    details['pattern'] = pattern
    return DimensionSignal(
        name=DIM_NAMES[1], signal=_score_to_signal(score),
        score=round(score, 1), description=pattern, details=details,
    )


# ==================== 维度3: VWAP (20%) ====================


def analyze_vwap(vwap_data, quote: dict) -> DimensionSignal:
    """分析 VWAP 多空分水岭"""
    if vwap_data is None:
        return DimensionSignal(
            name=DIM_NAMES[2], signal=SIGNAL_NEUTRAL,
            score=0, description="VWAP数据不可用", details={},
        )

    dev = vwap_data.deviation_pct
    above = vwap_data.above_vwap
    vol_ratio = quote.get('volume_ratio', 1.0) or 1.0
    details: Dict[str, Any] = {
        'vwap': vwap_data.vwap,
        'deviation_pct': round(dev, 2),
        'above_vwap': above,
    }

    if above:
        if dev > 1.5:
            score, desc = 40, "远离VWAP上方，多头强势"
        elif dev > 0.3:
            score, desc = 25, "站上VWAP，多头控盘"
        elif vol_ratio > 1.0:
            score, desc = 35, "回踩VWAP获支撑，放量确认"
        else:
            score, desc = 10, "贴近VWAP上方"
    else:
        if dev < -1.5:
            score, desc = -40, "远离VWAP下方，空头强势"
        elif dev < -0.3:
            score, desc = -25, "跌破VWAP，空头控盘"
        else:
            score, desc = -10, "贴近VWAP下方"

    return DimensionSignal(
        name=DIM_NAMES[2], signal=_score_to_signal(score),
        score=round(score, 1), description=desc, details=details,
    )


# ==================== 维度4: 关键点位 (15%) ====================


def analyze_key_levels(ob, sr: dict, quote: dict) -> DimensionSignal:
    """分析关键点位：支撑阻力 + 日内位置 + 流动性"""
    score = 0.0
    details: Dict[str, Any] = {}

    sup = sr.get('support')
    res = sr.get('resistance')

    # 支撑/阻力挂单量对比
    if sup and res:
        sv, rv = sup['volume'], res['volume']
        details['support_volume'] = sv
        details['resistance_volume'] = rv
        if sv > rv * 2:
            score += 30
        elif sv > rv * 1.3:
            score += 15
        elif rv > sv * 2:
            score -= 30
        elif rv > sv * 1.3:
            score -= 15

    # 价格与日内高低点的关系
    current = get_last_price(quote)
    high = quote.get('high_price', 0) or 0
    low = quote.get('low_price', 0) or 0

    if current > 0 and high > low > 0:
        day_range = high - low
        if day_range > 0:
            pos_in_range = (current - low) / day_range
            details['day_range_position'] = round(pos_in_range, 2)
            if pos_in_range < 0.2 and ob.imbalance > 0.1:
                score += 20
            elif pos_in_range > 0.8 and ob.imbalance > 0:
                score += 15

    # 流动性修正
    spread_pct = ob.spread_pct
    details['spread_pct'] = spread_pct
    if spread_pct > 0.5:
        score *= 0.7
        details['liquidity'] = 'low'
    elif spread_pct > 0.2:
        score *= 0.85
        details['liquidity'] = 'medium'
    else:
        details['liquidity'] = 'high'

    score = _clamp(score)
    desc = _key_levels_desc(score, details)
    return DimensionSignal(
        name=DIM_NAMES[3], signal=_score_to_signal(score),
        score=round(score, 1), description=desc, details=details,
    )


def _key_levels_desc(score: float, details: dict) -> str:
    liq = details.get('liquidity', 'medium')
    liq_text = "流动性差" if liq == 'low' else ""
    if score > 15:
        return "下方有强支撑" + ("，" + liq_text if liq_text else "")
    if score > 5:
        return "支撑位挂单量适中"
    if score > -5:
        return "支撑阻力均衡"
    if score > -15:
        return "上方阻力较大"
    return "上方有强阻力" + ("，" + liq_text if liq_text else "")


# ==================== 维度5: 相对强弱 (10%) ====================


def analyze_relative_strength(
    quote: dict, market_avg: float, sector_avg: float = 0.0,
) -> DimensionSignal:
    """分析相对强弱：个股 vs 板块（优先）或大盘"""
    change = quote.get('change_rate', 0) or quote.get('change_pct', 0) or 0
    # 优先使用板块基准，不可用时降级为大盘基准
    benchmark = sector_avg if sector_avg != 0.0 else market_avg
    benchmark_label = "板块" if sector_avg != 0.0 else "大盘"
    diff = change - benchmark
    details: Dict[str, Any] = {
        'stock_change': round(change, 2),
        'market_avg_change': round(market_avg, 2),
        'sector_avg_change': round(sector_avg, 2),
        'benchmark_used': benchmark_label,
        'diff': round(diff, 2),
    }

    if diff > 3:
        score, desc = 60, f"强势领涨，远强于{benchmark_label}"
    elif diff > 1.5:
        score, desc = 35, f"强于{benchmark_label}"
    elif diff > 0:
        score, desc = 10, f"略强于{benchmark_label}"
    elif diff > -1.5:
        score, desc = -10, f"略弱于{benchmark_label}"
    elif diff > -3:
        score, desc = -35, f"弱于{benchmark_label}"
    else:
        score, desc = -60, f"弱势补跌，远弱于{benchmark_label}"

    # 抗跌性: 大盘跌但个股不跌
    if market_avg < -1 and change > -0.5:
        score = max(score, 40)
        desc = f"{benchmark_label}下跌但抗跌性强"

    return DimensionSignal(
        name=DIM_NAMES[4], signal=_score_to_signal(score),
        score=round(score, 1), description=desc, details=details,
    )
