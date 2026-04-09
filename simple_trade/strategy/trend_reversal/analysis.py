#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""趋势反转策略 - 趋势分析与板块情绪"""

from typing import Dict, Any, List

from .models import TrendAnalysis


def analyze_trend(
    lookback_data: List[Dict[str, Any]],
    current_price: float,
    current_high: float,
    current_low: float,
    current_open: float,
) -> TrendAnalysis:
    """
    分析趋势

    Args:
        lookback_data: 回看期间的K线数据
        current_price: 当前价格
        current_high: 当日最高价
        current_low: 当日最低价
        current_open: 当日开盘价
    """
    trend = TrendAnalysis()
    trend.current_price = current_price

    if not lookback_data:
        return trend

    # 统计涨跌天数（根据K线实体方向：收盘价 vs 开盘价）
    for day in lookback_data:
        close = day.get('close', 0)
        open_price = day.get('open', 0)
        if close > open_price:
            trend.up_days += 1
        elif close < open_price:
            trend.down_days += 1
        else:
            trend.flat_days += 1

    total_days = len(lookback_data)
    trend.up_ratio = trend.up_days / total_days if total_days > 0 else 0
    trend.down_ratio = trend.down_days / total_days if total_days > 0 else 0

    # 计算期间最高/最低价
    highs = [day.get('high', 0) for day in lookback_data]
    lows = [day.get('low', 0) for day in lookback_data]
    trend.period_high = max(highs) if highs else 0
    trend.period_low = min(lows) if lows else 0

    # 计算跌幅和涨幅
    if trend.period_high > 0:
        trend.drop_from_high = ((trend.period_high - current_price) / trend.period_high) * 100
    if trend.period_low > 0:
        trend.rise_from_low = ((current_price - trend.period_low) / trend.period_low) * 100

    # 判断趋势方向
    if trend.down_ratio >= 0.6:
        trend.trend_direction = "DOWN"
        trend.trend_strength = trend.down_ratio
    elif trend.up_ratio >= 0.6:
        trend.trend_direction = "UP"
        trend.trend_strength = trend.up_ratio
    else:
        trend.trend_direction = "SIDEWAYS"
        trend.trend_strength = max(trend.up_ratio, trend.down_ratio)

    # 计算反转信号（今日K线方向）
    today_is_up = current_price > current_open if current_open > 0 else False
    if trend.trend_direction == "DOWN" and today_is_up:
        trend.reversal_signal = trend.rise_from_low
        trend.is_buy_reversal = True
    elif trend.trend_direction == "UP" and not today_is_up:
        trend.reversal_signal = trend.drop_from_high
        trend.is_sell_reversal = True

    # 量价分析
    _analyze_volume_trend(lookback_data, trend)

    return trend


def _analyze_volume_trend(
    lookback_data: List[Dict[str, Any]],
    trend: TrendAnalysis,
) -> None:
    """分析成交量趋势，填充 TrendAnalysis 的量价字段"""
    volumes = [day.get('volume', 0) for day in lookback_data]
    if not volumes or all(v == 0 for v in volumes):
        return

    avg_volume = sum(volumes) / len(volumes)
    if avg_volume <= 0:
        return

    # 区分下跌日和上涨日的成交量
    down_volumes = []
    up_volumes = []
    for day in lookback_data:
        vol = day.get('volume', 0)
        close = day.get('close', 0)
        open_price = day.get('open', 0)
        if close < open_price:
            down_volumes.append(vol)
        elif close > open_price:
            up_volumes.append(vol)

    # 反弹日成交量 / 下跌日均量
    avg_down_vol = sum(down_volumes) / len(down_volumes) if down_volumes else avg_volume
    last_up_vol = up_volumes[-1] if up_volumes else 0
    trend.reversal_volume_ratio = (
        last_up_vol / avg_down_vol if avg_down_vol > 0 else 1.0
    )

    # 近期成交量 / 历史均量（最后2日 vs 全部均值）
    recent_avg = sum(volumes[-2:]) / min(2, len(volumes[-2:]))
    trend.avg_volume_ratio = recent_avg / avg_volume if avg_volume > 0 else 1.0

    # 判断量价趋势
    if down_volumes and up_volumes:
        avg_up_vol = sum(up_volumes) / len(up_volumes)
        if avg_down_vol > avg_up_vol * 1.2:
            trend.volume_trend = "SHRINK_DOWN"
        elif avg_up_vol > avg_down_vol * 1.2:
            trend.volume_trend = "EXPAND_UP"
        else:
            trend.volume_trend = "MIXED"
    else:
        trend.volume_trend = "MIXED"


def analyze_plate_sentiment(
    plate_stocks_data: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """分析板块情绪"""
    if not plate_stocks_data:
        return {
            'total_stocks': 0, 'up_count': 0, 'down_count': 0,
            'flat_count': 0, 'up_ratio': 0, 'avg_change': 0,
            'sentiment': 'NEUTRAL',
        }

    up_count = down_count = flat_count = 0
    total_change = 0.0

    for stock in plate_stocks_data:
        change = stock.get('change_percent', 0)
        total_change += change
        if change > 0.1:
            up_count += 1
        elif change < -0.1:
            down_count += 1
        else:
            flat_count += 1

    total_stocks = len(plate_stocks_data)
    up_ratio = up_count / total_stocks if total_stocks > 0 else 0
    avg_change = total_change / total_stocks if total_stocks > 0 else 0

    if up_ratio >= 0.7:
        sentiment = 'STRONG_BULLISH'
    elif up_ratio >= 0.55:
        sentiment = 'BULLISH'
    elif up_ratio <= 0.3:
        sentiment = 'STRONG_BEARISH'
    elif up_ratio <= 0.45:
        sentiment = 'BEARISH'
    else:
        sentiment = 'NEUTRAL'

    return {
        'total_stocks': total_stocks, 'up_count': up_count,
        'down_count': down_count, 'flat_count': flat_count,
        'up_ratio': up_ratio, 'avg_change': avg_change,
        'sentiment': sentiment,
    }


def adjust_signal_by_sentiment(
    signal_type: str,
    plate_sentiment: Dict[str, Any],
) -> float:
    """根据板块情绪调整信号强度

    Returns:
        信号调整系数 (>1.0 加强, <1.0 减弱, 1.0 不变)
    """
    sentiment = plate_sentiment.get('sentiment', 'NEUTRAL')

    if signal_type == 'BUY':
        if sentiment in ['STRONG_BEARISH', 'BEARISH']:
            return 1.3  # 板块下跌中个股反弹 = 强势
        return 1.0
    elif signal_type == 'SELL':
        if sentiment in ['STRONG_BULLISH', 'BULLISH']:
            return 1.3  # 板块上涨中个股回落 = 弱势
        return 1.0
    return 1.0
