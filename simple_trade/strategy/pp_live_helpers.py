#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日内价格位置策略 - 辅助函数

包含目标价计算、开盘类型判断、区间分类和条件详情构建。
"""

from typing import Dict, Any, List, Optional

from .base_strategy import StrategyResult, ConditionDetail
from ..services.trading.price_position.pp_live_models import (
    CachedAnalysisParams, ZoneTradeParam,
)


# 价格位置区间边界（与 PricePositionStrategy 保持一致）
ZONE_BOUNDARIES = [
    ('低位(0-20%)', 0, 20),
    ('偏低(20-40%)', 20, 40),
    ('中位(40-60%)', 40, 60),
    ('偏高(60-80%)', 60, 80),
    ('高位(80-100%)', 80, 100),
]

# 默认使用的区间（当无法判断 price_position 时）
DEFAULT_ZONE = '中位(40-60%)'


def classify_open_type(
    open_price: float, prev_close: float, gap_threshold: float = 0.5,
) -> str:
    """判断开盘类型"""
    if prev_close <= 0:
        return 'flat'
    gap_pct = (open_price - prev_close) / prev_close * 100
    if gap_pct > gap_threshold:
        return 'gap_up'
    if gap_pct < -gap_threshold:
        return 'gap_down'
    return 'flat'


def classify_zone(price_position: float) -> str:
    """根据价格位置百分比判断所属区间"""
    for name, low, high in ZONE_BOUNDARIES:
        if low <= price_position < high:
            return name
    return DEFAULT_ZONE


def calc_targets(anchor_price: float, param: ZoneTradeParam) -> tuple:
    """计算买卖目标价和止损价，返回 (buy_target, sell_target, stop_price)"""
    buy_target = round(anchor_price * (1 - param.buy_dip_pct / 100), 3)
    sell_target = round(anchor_price * (1 + param.sell_rise_pct / 100), 3)
    stop_price = round(buy_target * (1 - param.stop_loss_pct / 100), 3)
    return buy_target, sell_target, stop_price


def select_param_and_anchor(
    cached: CachedAnalysisParams, open_type: str,
    open_price: float, prev_close: float,
) -> tuple:
    """根据开盘类型选择参数和锚点，返回 (ZoneTradeParam, anchor_price) 或 (None, 0)"""
    if open_type == 'gap_up' and 'gap_up' in cached.open_type_params:
        return cached.open_type_params['gap_up'], open_price

    if open_type == 'gap_down':
        if cached.skip_gap_down:
            return None, 0
        if 'gap_down' in cached.open_type_params:
            return cached.open_type_params['gap_down'], prev_close

    # flat 或 fallback：使用 zone 参数
    zone_param = get_zone_param(cached)
    if zone_param:
        return zone_param, prev_close
    return None, 0


def get_zone_param(cached: CachedAnalysisParams) -> Optional[ZoneTradeParam]:
    """获取当前区间的交易参数（简化：取第一个可用区间）"""
    if DEFAULT_ZONE in cached.zone_params:
        return cached.zone_params[DEFAULT_ZONE]
    for param in cached.zone_params.values():
        if param.buy_dip_pct > 0:
            return param
    return None


def build_condition_details(
    strategy_result: StrategyResult,
    quote_data: Dict[str, Any],
) -> List[ConditionDetail]:
    """构建条件详情列表"""
    details = []
    targets_data = strategy_result.strategy_data.get('targets', {})

    has_params = bool(targets_data)
    details.append(ConditionDetail(
        name="回测参数",
        current_value="已就绪" if has_params else "未就绪",
        target_value="已完成回测分析",
        passed=has_params,
        description="需要完成价格位置回测分析",
    ))

    if not has_params:
        return details

    details.append(ConditionDetail(
        name="开盘类型",
        current_value=targets_data.get('open_type', ''),
        target_value="高开/平开/低开",
        passed=True,
        description=f"锚点价格: {targets_data.get('anchor_price', 0)}",
    ))

    last_price = quote_data.get('last_price', 0)
    buy_target = targets_data.get('buy_target', 0)
    details.append(ConditionDetail(
        name="买入条件",
        current_value=f"现价 {last_price}",
        target_value=f"<= {buy_target}",
        passed=last_price <= buy_target if buy_target > 0 else False,
        description=f"跌幅 {targets_data.get('buy_dip_pct', 0)}%",
    ))

    sell_target = targets_data.get('sell_target', 0)
    details.append(ConditionDetail(
        name="卖出条件",
        current_value=f"现价 {last_price}",
        target_value=f">= {sell_target}",
        passed=last_price >= sell_target if sell_target > 0 else False,
        description=f"涨幅 {targets_data.get('sell_rise_pct', 0)}%",
    ))

    return details
