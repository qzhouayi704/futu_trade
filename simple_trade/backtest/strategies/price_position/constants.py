#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
价格位置策略 — 常量与数据结构定义

包含：
- 目标股票列表
- 价格区间定义
- 回看天数等基础常量
- 情绪相关常量
- 开盘类型相关常量
- 所有 dataclass 数据结构
- 预定义优化方案
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ========== 目标股票 ==========

TARGET_STOCKS = [
    'HK.00700',  # 腾讯
    'HK.03690',  # 美团
    'HK.01810',  # 小米
    'HK.01024',  # 快手
    'HK.09988',  # 阿里巴巴
    'HK.01347',  # 华虹半导体
    'HK.09888',  # 百度
    'HK.09618',  # 京东
    'HK.09999',  # 网易
    'HK.09626',  # 哔哩哔哩
    'HK.02015',  # 理想汽车
    'HK.09868',  # 小鹏汽车
]

# ========== 价格区间定义 ==========

ZONE_DEFINITIONS = {
    '低位(0-20%)': (0, 20),
    '偏低(20-40%)': (20, 40),
    '中位(40-60%)': (40, 60),
    '偏高(60-80%)': (60, 80),
    '高位(80-100%)': (80, 100),
}

# 区间名称列表（有序）
ZONE_NAMES = list(ZONE_DEFINITIONS.keys())

# ========== 基础常量 ==========

LOOKBACK_DAYS = 12  # 回看天数
MIN_TRIGGER_RATE = 0.30  # 最低触发率 30%

# ========== 大盘情绪相关常量 ==========

# 恒生科技ETF代码（作为大盘情绪代理）
SENTIMENT_ETF_CODE = 'HK.03032'

# 情绪等级
SENTIMENT_BEARISH = 'bearish'   # 弱势
SENTIMENT_NEUTRAL = 'neutral'   # 中性
SENTIMENT_BULLISH = 'bullish'   # 强势
SENTIMENT_LEVELS = [SENTIMENT_BEARISH, SENTIMENT_NEUTRAL, SENTIMENT_BULLISH]

# 默认情绪阈值（涨跌幅百分比）
DEFAULT_SENTIMENT_THRESHOLDS = {
    'bearish_threshold': -1.0,  # < -1% 为弱势
    'bullish_threshold': 1.0,   # > +1% 为强势
}

# 默认情绪调整系数
DEFAULT_SENTIMENT_ADJUSTMENTS = {
    SENTIMENT_BEARISH: {'buy_dip_multiplier': 1.3, 'sell_rise_multiplier': 0.7},
    SENTIMENT_NEUTRAL: {'buy_dip_multiplier': 1.0, 'sell_rise_multiplier': 1.0},
    SENTIMENT_BULLISH: {'buy_dip_multiplier': 0.7, 'sell_rise_multiplier': 1.3},
}

# ========== 双锚点相关常量 ==========

# 开盘价锚点默认参数（独立于主锚点，用于强势高开日）
DEFAULT_OPEN_ANCHOR_PARAMS = {
    'open_buy_dip_pct': 1.0,    # 开盘价回调1%买入
    'open_sell_rise_pct': 1.5,  # 开盘价上涨1.5%卖出
    'stop_loss_pct': 2.0,       # 止损2%
}

# ========== 开盘类型相关常量 ==========

# 开盘类型定义
OPEN_TYPE_GAP_UP = 'gap_up'      # 高开
OPEN_TYPE_FLAT = 'flat'           # 平开
OPEN_TYPE_GAP_DOWN = 'gap_down'   # 低开
OPEN_TYPES = [OPEN_TYPE_GAP_UP, OPEN_TYPE_FLAT, OPEN_TYPE_GAP_DOWN]

# 默认开盘类型阈值（±0.5%）
DEFAULT_GAP_THRESHOLD = 0.5


# ========== Dataclass 数据结构定义 ==========

@dataclass
class ScoringWeights:
    """综合评分权重配置"""
    net_profit_weight: float = 0.4
    win_rate_weight: float = 0.3
    stop_loss_penalty_weight: float = 0.2
    profit_spread_bonus_weight: float = 0.1


@dataclass
class TradeParams:
    """单组交易参数"""
    buy_dip_pct: float
    sell_rise_pct: float
    stop_loss_pct: float


@dataclass
class SearchConfig:
    """搜索配置（可追溯性）"""
    sell_rise_range: list
    buy_dip_range: list
    min_trades: int
    scoring_weights: ScoringWeights


@dataclass
class SearchStats:
    """搜索过程统计"""
    total_combos: int = 0
    valid_combos: int = 0
    skipped_combos: int = 0


@dataclass
class GridSearchResult:
    """单区间网格搜索结果"""
    best_params: Optional[TradeParams] = None
    composite_score: float = 0.0
    avg_net_profit: float = 0.0
    win_rate: float = 0.0
    trades_count: int = 0
    stop_loss_rate: float = 0.0
    profit_spread: float = 0.0
    degraded: bool = False          # 是否降级了 min_trades
    actual_min_trades: int = 10
    search_config: Optional[SearchConfig] = None
    search_stats: Optional[SearchStats] = None


@dataclass
class OpenTypeGridResult:
    """Zone × Open_Type 单组合的搜索结果"""
    best_params: Optional[TradeParams] = None
    composite_score: float = 0.0
    avg_net_profit: float = 0.0
    win_rate: float = 0.0
    trades_count: int = 0
    stop_loss_rate: float = 0.0
    fallback_to_flat: bool = False  # 是否回退到平开日参数
    search_stats: Optional[SearchStats] = None


@dataclass
class SentimentAdjustResult:
    """情绪调整结果"""
    buy_dip_pct: float
    sell_rise_pct: float
    stop_loss_pct: float
    clamped: bool = False           # 是否发生了钳制


@dataclass
class SellModeMetrics:
    """单种卖出模式的指标"""
    total_trades: int = 0
    win_rate: float = 0.0
    avg_net_profit: float = 0.0
    max_drawdown: float = 0.0
    stop_loss_rate: float = 0.0
    composite_score: float = 0.0


@dataclass
class SellModeComparison:
    """日内/次日卖出模式对比结果"""
    intraday: SellModeMetrics = field(default_factory=SellModeMetrics)
    next_day: SellModeMetrics = field(default_factory=SellModeMetrics)
    recommended_mode: str = 'intraday'      # 'intraday' 或 'next_day'
    next_day_insufficient: bool = False     # 次日模式交易数不足


@dataclass
class OptimizationScheme:
    """优化方案定义"""
    name: str
    min_sell_rise_pct: float = 1.0
    min_buy_dip_pct: float = 0.5
    min_trades: int = 10
    scoring_weights: ScoringWeights = field(default_factory=ScoringWeights)
    enable_zone_open_type: bool = False     # 是否启用 Zone×OpenType 交叉优化


@dataclass
class SchemeResult:
    """单方案回测结果"""
    scheme: OptimizationScheme = field(
        default_factory=lambda: OptimizationScheme(name='')
    )
    zone_params: Dict[str, GridSearchResult] = field(default_factory=dict)
    zone_open_type_params: Optional[Dict[str, Dict[str, OpenTypeGridResult]]] = None
    trades: list = field(default_factory=list)
    next_day_trades: list = field(default_factory=list)
    sell_mode_comparison: Optional[SellModeComparison] = None
    total_trades: int = 0
    win_rate: float = 0.0
    avg_net_profit: float = 0.0
    max_drawdown: float = 0.0
    stop_loss_rate: float = 0.0
    composite_score: float = 0.0
    recommended_sell_mode: str = 'intraday'


@dataclass
class ComparisonReport:
    """对比报告"""
    scheme_results: Dict[str, SchemeResult] = field(default_factory=dict)
    recommended_scheme: str = ''
    sell_mode_summary: Dict[str, int] = field(
        default_factory=lambda: {'intraday': 0, 'next_day': 0}
    )


# ========== 预定义优化方案 ==========

PRESET_SCHEMES = {
    '保守方案': OptimizationScheme(
        name='保守方案',
        min_sell_rise_pct=1.5,
        min_buy_dip_pct=0.75,
        min_trades=15,
    ),
    '均衡方案': OptimizationScheme(
        name='均衡方案',
        min_sell_rise_pct=1.0,
        min_buy_dip_pct=0.5,
        min_trades=10,
    ),
    '激进方案': OptimizationScheme(
        name='激进方案',
        min_sell_rise_pct=0.5,
        min_buy_dip_pct=0.25,
        min_trades=8,
    ),
}
