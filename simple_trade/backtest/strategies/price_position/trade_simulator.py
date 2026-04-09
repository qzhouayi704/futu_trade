#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
价格位置策略 — 交易模拟器

包含：
- apply_sentiment_adjustment: 情绪调整（含下限钳制保护）
- simulate_trades: 日内交易模拟
- simulate_trades_next_day: 隔日交易模拟
- _resolve_buy_params: 买入参数解析（消除两个 simulate 方法的重复逻辑）
- _calculate_trade_fees: 费用计算
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .constants import (
    SENTIMENT_NEUTRAL,
    SENTIMENT_BULLISH,
    DEFAULT_SENTIMENT_ADJUSTMENTS,
    DEFAULT_OPEN_ANCHOR_PARAMS,
    OPEN_TYPE_GAP_UP,
    OPEN_TYPE_GAP_DOWN,
    OPEN_TYPE_FLAT,
    SentimentAdjustResult,
)


# ========== 辅助数据结构 ==========

@dataclass
class BuyResolveResult:
    """买入参数解析结果"""
    triggered: bool
    buy_price: float = 0.0
    sell_target: float = 0.0
    buy_dip_pct: float = 0.0
    sell_rise_pct: float = 0.0
    stop_loss_pct: float = 3.0
    anchor_type: str = 'prev_close'
    anchor_price: float = 0.0


_NOT_TRIGGERED = BuyResolveResult(triggered=False)


# ========== 情绪调整 ==========

def apply_sentiment_adjustment(
    params: Dict[str, float],
    sentiment_level: str,
    adjustments: Optional[Dict[str, Dict[str, float]]] = None,
    min_adjusted_sell_rise: float = 0.8,
) -> SentimentAdjustResult:
    """
    根据情绪等级调整买卖参数，并施加下限钳制保护。

    Args:
        params: 原始交易参数 {buy_dip_pct, sell_rise_pct, stop_loss_pct}
        sentiment_level: 情绪等级
        adjustments: 调整系数配置
        min_adjusted_sell_rise: sell_rise_pct 调整后的最低值（默认 0.8%）

    Returns:
        SentimentAdjustResult，含 clamped 标记
    """
    if adjustments is None:
        adjustments = DEFAULT_SENTIMENT_ADJUSTMENTS

    adj = adjustments.get(sentiment_level, adjustments.get(SENTIMENT_NEUTRAL, {}))
    buy_mult = adj.get('buy_dip_multiplier', 1.0)
    sell_mult = adj.get('sell_rise_multiplier', 1.0)

    adjusted_sell = round(params.get('sell_rise_pct', 0) * sell_mult, 4)
    clamped = adjusted_sell < min_adjusted_sell_rise
    if clamped:
        adjusted_sell = min_adjusted_sell_rise

    return SentimentAdjustResult(
        buy_dip_pct=round(params.get('buy_dip_pct', 0) * buy_mult, 4),
        sell_rise_pct=adjusted_sell,
        stop_loss_pct=params.get('stop_loss_pct', 3.0),
        clamped=clamped,
    )


# ========== 买入参数解析（消除重复） ==========

def _resolve_buy_params(
    m: Dict[str, Any],
    trade_params: Dict[str, Dict[str, float]],
    enable_open_type_anchor: bool = False,
    open_type_params: Optional[Dict[str, Dict[str, float]]] = None,
    skip_gap_down: bool = False,
    use_sentiment: bool = False,
    sentiment_adjustments: Optional[Dict[str, Dict[str, float]]] = None,
    enable_open_anchor: bool = False,
    open_anchor_params: Optional[Dict[str, float]] = None,
) -> BuyResolveResult:
    """
    统一的买入参数解析逻辑。

    根据开盘类型、情绪、锚点模式等条件，确定买入价、卖出目标、
    止损等参数，并判断是否触发买入。

    Args:
        m: 单日指标数据
        trade_params: 各区间的交易参数
        enable_open_type_anchor: 是否启用开盘类型锚点
        open_type_params: 各开盘类型的参数
        skip_gap_down: 是否跳过低开日
        use_sentiment: 是否启用情绪调整
        sentiment_adjustments: 情绪调整系数
        enable_open_anchor: 是否启用旧双锚点（仅日内模式）
        open_anchor_params: 旧双锚点参数

    Returns:
        BuyResolveResult，triggered=False 表示未触发买入
    """
    zone = m['zone']
    params = trade_params.get(zone)
    prev_close = m['prev_close']
    open_price = m.get('open_price', 0)
    open_type = m.get('open_type', OPEN_TYPE_FLAT)
    sentiment_level = m.get('sentiment_level', SENTIMENT_NEUTRAL)

    # 无 zone 参数且非开盘类型锚点模式 → 跳过
    if (not params or params['buy_dip_pct'] <= 0) and not enable_open_type_anchor:
        return _NOT_TRIGGERED

    if enable_open_type_anchor:
        return _resolve_open_type_anchor(
            m, params, open_type, prev_close, open_price,
            open_type_params, skip_gap_down,
            use_sentiment, sentiment_adjustments, sentiment_level,
        )

    # ========== 非开盘类型模式 ==========
    if not params or params['buy_dip_pct'] <= 0:
        return _NOT_TRIGGERED

    effective = _get_effective_params(params, use_sentiment, sentiment_adjustments, sentiment_level)
    buy_price = prev_close * (1 - effective['buy_dip_pct'] / 100)

    if m['low_price'] <= buy_price:
        # 主锚点触发
        return BuyResolveResult(
            triggered=True,
            buy_price=buy_price,
            sell_target=prev_close * (1 + effective['sell_rise_pct'] / 100),
            buy_dip_pct=effective['buy_dip_pct'],
            sell_rise_pct=effective['sell_rise_pct'],
            stop_loss_pct=effective['stop_loss_pct'],
            anchor_type='prev_close',
            anchor_price=prev_close,
        )

    # 旧双锚点：bullish 时用 open_price 备选
    if enable_open_anchor and sentiment_level == SENTIMENT_BULLISH and open_price > 0:
        oa = open_anchor_params or DEFAULT_OPEN_ANCHOR_PARAMS
        oa_buy_dip = oa.get('open_buy_dip_pct', 1.0)
        oa_sell_rise = oa.get('open_sell_rise_pct', 1.5)
        oa_stop = oa.get('stop_loss_pct', 2.0)
        buy_price = open_price * (1 - oa_buy_dip / 100)
        if m['low_price'] <= buy_price:
            return BuyResolveResult(
                triggered=True,
                buy_price=buy_price,
                sell_target=open_price * (1 + oa_sell_rise / 100),
                buy_dip_pct=oa_buy_dip,
                sell_rise_pct=oa_sell_rise,
                stop_loss_pct=oa_stop,
                anchor_type='open_price',
                anchor_price=open_price,
            )

    return _NOT_TRIGGERED


def _resolve_open_type_anchor(
    m: Dict[str, Any],
    params: Optional[Dict[str, float]],
    open_type: str,
    prev_close: float,
    open_price: float,
    open_type_params: Optional[Dict[str, Dict[str, float]]],
    skip_gap_down: bool,
    use_sentiment: bool,
    sentiment_adjustments: Optional[Dict[str, Dict[str, float]]],
    sentiment_level: str,
) -> BuyResolveResult:
    """开盘类型锚点模式的买入参数解析"""
    ot_params = open_type_params or {}

    if open_type == OPEN_TYPE_GAP_UP and 'gap_up' in ot_params:
        gp = ot_params['gap_up']
        bdp = gp.get('buy_dip_pct', gp.get('open_buy_dip_pct', 1.0))
        srp = gp.get('sell_rise_pct', gp.get('open_sell_rise_pct', 1.5))
        slp = gp.get('stop_loss_pct', 2.0)
        buy_price = open_price * (1 - bdp / 100)
        if m['low_price'] > buy_price:
            return _NOT_TRIGGERED
        return BuyResolveResult(
            triggered=True, buy_price=buy_price,
            sell_target=open_price * (1 + srp / 100),
            buy_dip_pct=bdp, sell_rise_pct=srp, stop_loss_pct=slp,
            anchor_type='open_price', anchor_price=open_price,
        )

    if open_type == OPEN_TYPE_GAP_DOWN:
        if skip_gap_down:
            return _NOT_TRIGGERED
        if 'gap_down' in ot_params:
            gp = ot_params['gap_down']
            bdp = gp.get('buy_dip_pct', 2.0)
            srp = gp.get('sell_rise_pct', 1.0)
            slp = gp.get('stop_loss_pct', 3.0)
            buy_price = prev_close * (1 - bdp / 100)
            if m['low_price'] > buy_price:
                return _NOT_TRIGGERED
            return BuyResolveResult(
                triggered=True, buy_price=buy_price,
                sell_target=prev_close * (1 + srp / 100),
                buy_dip_pct=bdp, sell_rise_pct=srp, stop_loss_pct=slp,
                anchor_type='prev_close', anchor_price=prev_close,
            )
        # 无 gap_down 参数，回退到 zone 参数
        if not params or params['buy_dip_pct'] <= 0:
            return _NOT_TRIGGERED
        effective = _get_effective_params(params, use_sentiment, sentiment_adjustments, sentiment_level)
        buy_price = prev_close * (1 - effective['buy_dip_pct'] / 100)
        if m['low_price'] > buy_price:
            return _NOT_TRIGGERED
        return BuyResolveResult(
            triggered=True, buy_price=buy_price,
            sell_target=prev_close * (1 + effective['sell_rise_pct'] / 100),
            buy_dip_pct=effective['buy_dip_pct'], sell_rise_pct=effective['sell_rise_pct'],
            stop_loss_pct=effective['stop_loss_pct'],
            anchor_type='prev_close', anchor_price=prev_close,
        )

    # 平开日（或无特殊参数）
    if not params or params['buy_dip_pct'] <= 0:
        return _NOT_TRIGGERED
    effective = _get_effective_params(params, use_sentiment, sentiment_adjustments, sentiment_level)
    buy_price = prev_close * (1 - effective['buy_dip_pct'] / 100)
    if m['low_price'] > buy_price:
        return _NOT_TRIGGERED
    return BuyResolveResult(
        triggered=True, buy_price=buy_price,
        sell_target=prev_close * (1 + effective['sell_rise_pct'] / 100),
        buy_dip_pct=effective['buy_dip_pct'], sell_rise_pct=effective['sell_rise_pct'],
        stop_loss_pct=effective['stop_loss_pct'],
        anchor_type='prev_close', anchor_price=prev_close,
    )


def _get_effective_params(
    params: Dict[str, float],
    use_sentiment: bool,
    sentiment_adjustments: Optional[Dict[str, Dict[str, float]]],
    sentiment_level: str,
) -> Dict[str, float]:
    """获取经过情绪调整的有效参数"""
    if use_sentiment and sentiment_adjustments is not None:
        result = apply_sentiment_adjustment(params, sentiment_level, sentiment_adjustments)
        return {
            'buy_dip_pct': result.buy_dip_pct,
            'sell_rise_pct': result.sell_rise_pct,
            'stop_loss_pct': result.stop_loss_pct,
        }
    return params


# ========== 费用计算 ==========

def _calculate_trade_fees(
    profit_pct: float,
    trade_amount: float,
    fee_calculator: Any,
) -> Tuple[float, float, float]:
    """
    计算交易费用。

    Returns:
        (buy_fee, sell_fee, net_profit_pct)
    """
    if fee_calculator is None or trade_amount <= 0:
        return 0.0, 0.0, profit_pct

    buy_fee_detail = fee_calculator.calculate_hk_fee(trade_amount, is_buy=True)
    sell_amount_actual = trade_amount * (1 + profit_pct / 100)
    sell_fee_detail = fee_calculator.calculate_hk_fee(sell_amount_actual, is_buy=False)
    buy_fee = buy_fee_detail.total
    sell_fee = sell_fee_detail.total
    total_fee = buy_fee + sell_fee
    net_profit_pct = ((sell_amount_actual - trade_amount - total_fee) / trade_amount) * 100
    return buy_fee, sell_fee, net_profit_pct


# ========== 交易记录构建 ==========

def _build_base_record(
    m: Dict[str, Any],
    br: BuyResolveResult,
    params: Optional[Dict[str, float]],
    sell_price: float,
    sell_target: float,
    stop_price: float,
    exit_type: str,
    profit_pct: float,
    buy_fee: float,
    sell_fee: float,
    net_profit_pct: float,
) -> Dict[str, Any]:
    """构建基础交易记录（日内和隔日共用字段）"""
    return {
        'date': m['date'],
        'stock_code': m.get('stock_code', ''),
        'zone': m['zone'],
        'price_position': m['price_position'],
        'prev_close': round(m['prev_close'], 3),
        'buy_price': round(br.buy_price, 3),
        'sell_price': round(sell_price, 3),
        'sell_target': round(sell_target, 3),
        'stop_price': round(stop_price, 3),
        'buy_dip_pct': params['buy_dip_pct'] if params else 0,
        'sell_rise_pct': params['sell_rise_pct'] if params else 0,
        'stop_loss_pct': br.stop_loss_pct,
        'profit_pct': round(profit_pct, 4),
        'buy_fee': round(buy_fee, 2),
        'sell_fee': round(sell_fee, 2),
        'net_profit_pct': round(net_profit_pct, 4),
        'exit_type': exit_type,
        'high_price': m['high_price'],
        'low_price': m['low_price'],
        'close_price': m['close_price'],
        'sentiment_level': m.get('sentiment_level', SENTIMENT_NEUTRAL),
        'sentiment_pct': m.get('sentiment_pct', 0.0),
        'effective_buy_dip_pct': round(br.buy_dip_pct, 4),
        'effective_sell_rise_pct': round(br.sell_rise_pct, 4),
        'anchor_type': br.anchor_type,
        'anchor_price': round(br.anchor_price, 3),
        'open_type': m.get('open_type', OPEN_TYPE_FLAT),
        'open_gap_pct': round(m.get('open_gap_pct', 0.0), 4),
    }


# ========== 日内交易模拟 ==========

def simulate_trades(
    strategy: Any,
    metrics: List[Dict[str, Any]],
    trade_params: Dict[str, Dict[str, float]],
    trade_amount: float = 60000.0,
    fee_calculator: Any = None,
    use_sentiment: bool = False,
    sentiment_adjustments: Optional[Dict[str, Dict[str, float]]] = None,
    enable_open_anchor: bool = False,
    open_anchor_params: Optional[Dict[str, float]] = None,
    enable_open_type_anchor: bool = False,
    open_type_params: Optional[Dict[str, Dict[str, float]]] = None,
    skip_gap_down: bool = False,
) -> List[Dict[str, Any]]:
    """
    模拟日内交易（含情绪调整 + 双锚点 + 开盘类型锚点）

    买入逻辑通过 _resolve_buy_params 统一处理。
    卖出逻辑：止损优先于止盈，最后收盘平仓。

    Args:
        strategy: PricePositionStrategy 实例（保留兼容性，当前未直接使用）
        metrics: calculate_daily_metrics() 的输出
        trade_params: 各区间的交易参数
        trade_amount: 每笔交易金额（港币），默认 60000
        fee_calculator: FeeCalculator 实例
        use_sentiment: 是否启用情绪调整
        sentiment_adjustments: 情绪调整系数
        enable_open_anchor: 是否启用旧双锚点（基于情绪）
        open_anchor_params: 旧双锚点参数
        enable_open_type_anchor: 是否启用开盘类型锚点
        open_type_params: 各开盘类型的参数
        skip_gap_down: 是否跳过低开日

    Returns:
        交易记录列表
    """
    trades = []

    for m in metrics:
        br = _resolve_buy_params(
            m, trade_params,
            enable_open_type_anchor=enable_open_type_anchor,
            open_type_params=open_type_params,
            skip_gap_down=skip_gap_down,
            use_sentiment=use_sentiment,
            sentiment_adjustments=sentiment_adjustments,
            enable_open_anchor=enable_open_anchor,
            open_anchor_params=open_anchor_params,
        )
        if not br.triggered:
            continue

        stop_price = br.buy_price * (1 - br.stop_loss_pct / 100)

        # 日内时序判断（止损优先于止盈）
        if m['low_price'] <= stop_price:
            sell_price, exit_type = stop_price, 'stop_loss'
        elif m['high_price'] >= br.sell_target:
            sell_price, exit_type = br.sell_target, 'profit'
        else:
            sell_price, exit_type = m['close_price'], 'close'

        profit_pct = (sell_price - br.buy_price) / br.buy_price * 100
        buy_fee, sell_fee, net_profit_pct = _calculate_trade_fees(
            profit_pct, trade_amount, fee_calculator,
        )

        params = trade_params.get(m['zone'])
        record = _build_base_record(
            m, br, params, sell_price, br.sell_target, stop_price,
            exit_type, profit_pct, buy_fee, sell_fee, net_profit_pct,
        )
        trades.append(record)

    return trades


# ========== 隔日交易模拟 ==========

def simulate_trades_next_day(
    strategy: Any,
    metrics: List[Dict[str, Any]],
    trade_params: Dict[str, Dict[str, float]],
    trade_amount: float = 60000.0,
    fee_calculator: Any = None,
    use_sentiment: bool = False,
    sentiment_adjustments: Optional[Dict[str, Dict[str, float]]] = None,
    enable_open_type_anchor: bool = False,
    open_type_params: Optional[Dict[str, Dict[str, float]]] = None,
    skip_gap_down: bool = False,
) -> List[Dict[str, Any]]:
    """
    模拟隔日交易：当日买入，次日卖出。

    买入逻辑与 simulate_trades 一致（通过 _resolve_buy_params）。
    卖出改为次日执行：止损/止盈/收盘均基于次日价格。

    Args:
        strategy: PricePositionStrategy 实例
        metrics: calculate_daily_metrics() 的输出（按时间正序）
        trade_params: 各区间的交易参数
        trade_amount: 每笔交易金额（港币）
        fee_calculator: FeeCalculator 实例
        use_sentiment: 是否启用情绪调整
        sentiment_adjustments: 情绪调整系数
        enable_open_type_anchor: 是否启用开盘类型锚点
        open_type_params: 各开盘类型的参数
        skip_gap_down: 是否跳过低开日

    Returns:
        交易记录列表（含 sell_date 字段）
    """
    trades = []

    for i in range(len(metrics) - 1):
        m = metrics[i]
        next_m = metrics[i + 1]

        br = _resolve_buy_params(
            m, trade_params,
            enable_open_type_anchor=enable_open_type_anchor,
            open_type_params=open_type_params,
            skip_gap_down=skip_gap_down,
            use_sentiment=use_sentiment,
            sentiment_adjustments=sentiment_adjustments,
            # 隔日模式不支持旧双锚点
            enable_open_anchor=False,
            open_anchor_params=None,
        )
        if not br.triggered:
            continue

        stop_price = br.buy_price * (1 - br.stop_loss_pct / 100)

        # 次日价格
        next_high = next_m['high_price']
        next_low = next_m['low_price']
        next_close = next_m['close_price']

        if next_low <= stop_price:
            sell_price, exit_type = stop_price, 'stop_loss'
        elif next_high >= br.sell_target:
            sell_price, exit_type = br.sell_target, 'profit'
        else:
            sell_price, exit_type = next_close, 'close'

        profit_pct = (sell_price - br.buy_price) / br.buy_price * 100
        buy_fee, sell_fee, net_profit_pct = _calculate_trade_fees(
            profit_pct, trade_amount, fee_calculator,
        )

        params = trade_params.get(m['zone'])
        record = _build_base_record(
            m, br, params, sell_price, br.sell_target, stop_price,
            exit_type, profit_pct, buy_fee, sell_fee, net_profit_pct,
        )
        # 隔日模式额外字段
        record['sell_date'] = next_m['date']
        record['next_high'] = next_high
        record['next_low'] = next_low
        record['next_close'] = next_close
        trades.append(record)

    return trades
