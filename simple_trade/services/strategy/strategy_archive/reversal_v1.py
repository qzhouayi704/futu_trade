#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略归档: REVERSAL (趋势反转 / 超跌反弹) v1
归档时间: 2026-05-20
归档原因: 回测数据证明该策略在港股市场无效
  - 2226个超跌样本(5日跌>3%)，200+参数组合，所有组合3日收益均为负
  - 根本原因: "跌够了"不等于"要反弹"，港股动量效应强（跌的继续跌）
  - 蓝思科技案例分析显示，真正有效的底部反转信号已被 TREND + BREAKOUT 覆盖

恢复方法:
  1. 将 REVERSAL_CONFIG 复制回 stock_scorer.py
  2. 恢复 _score_reversal() 方法
  3. 在 score_all_strategies() 中添加 reversal 调用
  4. 在 hot_stock.py 中添加 reversal 面板返回
  5. 在 MarketScanPanel.tsx 中恢复 REVERSAL 面板

回测数据摘要:
  - 简单持有3天: score>=55 → avg -0.44%, 胜率41.5%
  - 简单持有5天: score>=55 → avg +0.01%, 胜率41.1%
  - 网格搜索最优: SL10%/TP5%/3天 → avg -0.01%, PF=1.00 (不赚不亏)
  - 高分(>=70)反而更亏: 持4天 → avg -3.75%

交易参数(v2 - 已收紧但仍无效):
  - 止损: 12%
  - 追踪止盈: 涨8%后回撤5%卖
  - 最大持仓: 5天
  - 买入: T+1开盘
"""

# ==================== 评分配置 ====================

REVERSAL_CONFIG = {
    # 背景条件(40%): "跌够了"
    # 条件①②: 低位 + 近期下跌
    'kline_pos':     {'max_score': 15, 'optimal_range': (0.0, 0.2), 'marginal_range': (0.0, 0.4), 'default': 0},
    'change_5d':     {'max_score': 15, 'optimal_range': (-15.0, -3.0), 'marginal_range': (-25.0, -1.0), 'default': 0},
    'prev_change':   {'max_score': 10, 'optimal_range': (-8.0, -2.0), 'marginal_range': (-15.0, -1.0), 'default': 0},

    # 反转信号(60%): "开始反转了"
    # 条件③: 距低点反弹>=2%
    'rise_from_low': {'max_score': 15, 'tiers': [(5.0, 15), (3.0, 12), (2.0, 10), (1.0, 5)], 'default': 0},
    # 条件④: 今日收涨(阳线反转)
    'today_change':  {'max_score': 10, 'tiers': [(3.0, 10), (1.0, 8), (0.0, 5)], 'default': 0},
    # 条件⑤: 反弹伴随主动买入
    'ticker_power':  {'max_score': 15, 'tiers': [(0.5, 15), (0.2, 12), (0.0, 6)], 'default': 6},
    # 条件⑤⑥: 放量确认
    'vol_ratio':     {'max_score': 15, 'tiers': [(3.0, 15), (2.0, 12), (1.5, 8), (1.2, 5)], 'default': 0},
    # 振幅
    'amplitude':     {'max_score': 5, 'optimal_range': (3.0, 15.0), 'marginal_range': (2.0, 50.0), 'default': 0},
}


# ==================== 评分方法 ====================

def score_reversal(ind, _score_range, _score_tiered, ScoreDetail):
    """
    REVERSAL mode: 对齐TrendReversalStrategy的6个买入条件.

    参数:
        ind: 指标字典
        _score_range: StockScorer._score_range 静态方法
        _score_tiered: StockScorer._score_tiered 静态方法
        ScoreDetail: ScoreDetail 数据类

    返回:
        (total_score, details_list)
    """
    details = []
    total = 0

    # === 背景条件(40%): "跌够了" ===
    s, d = _score_range(REVERSAL_CONFIG['kline_pos'], ind.get('kline_pos_20d'), 'K线低位')
    details.append(d); total += s

    s, d = _score_range(REVERSAL_CONFIG['change_5d'], ind.get('change_5d'), '5日跌幅')
    details.append(d); total += s

    s, d = _score_range(REVERSAL_CONFIG['prev_change'], ind.get('prev_day_change'), '前日跌幅')
    details.append(d); total += s

    # === 反转信号(60%): "开始反转了" ===
    s, d = _score_tiered(REVERSAL_CONFIG['rise_from_low'], ind.get('rise_from_low'), '低位反弹')
    details.append(d); total += s

    s, d = _score_tiered(REVERSAL_CONFIG['today_change'], ind.get('today_change'), '今日涨幅')
    details.append(d); total += s

    s, d = _score_tiered(REVERSAL_CONFIG['ticker_power'], ind.get('ticker_power'), '逐笔买卖力量')
    details.append(d); total += s

    s, d = _score_tiered(REVERSAL_CONFIG['vol_ratio'], ind.get('vol_ratio'), '量比')
    details.append(d); total += s

    s, d = _score_range(REVERSAL_CONFIG['amplitude'], ind.get('day_amplitude'), '日内振幅')
    details.append(d); total += s

    return total, details


# ==================== 交易参数 ====================

def recommend_trade_params(indicators):
    """REVERSAL 交易参数建议（v2 已收紧）"""
    chg5d = indicators.get('change_5d', 0) or 0

    if chg5d <= -15:
        confidence = 'HIGH'
        reason = f'深度超卖(5日跌{chg5d:.1f}%)，反弹确定性高'
    elif chg5d <= -8:
        confidence = 'HIGH'
        reason = f'超卖反弹(5日跌{chg5d:.1f}%)'
    else:
        confidence = 'MEDIUM'
        reason = f'低位反转(5日跌{chg5d:.1f}%)，需等待反弹确认'

    return {
        'trade_type': 'DAILY',
        'buy_dip_pct': 0.0,
        'take_profit_pct': 8.0,
        'stop_loss_pct': 12.0,
        'max_hold_days': 5,
        'confidence': confidence,
        'reason': reason,
    }
