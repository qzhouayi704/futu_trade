#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一交易决策引擎 — 数据模型与配置常量

所有信号源的标准化输出格式、决策结果、共振规则和仓位配置。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any


# ============================================================
# 共振规则
# ============================================================

RESONANCE_RULES = {
    # 双源共振：2个以上不同 source 的买入信号
    'dual_source': {
        'min_sources': 2,
        'window_minutes': 15,
    },
    # 单源强信号：strength ≥ 80 且 StockScorer 评分 ≥ 80
    'strong_single': {
        'min_strength': 80,
        'min_score': 80,
    },
    # 多重绿色（仅 Sniper）：15分钟内2种以上不同 sniper_signal_type
    'multi_green': {
        'min_distinct_types': 2,
        'window_minutes': 15,
    },
}


# ============================================================
# 仓位控制
# ============================================================

POSITION_CONFIG = {
    'max_total_positions': 2,          # 最多同时持有2只（集中资金，原5）
    'max_single_position_pct': 0.50,   # 单只最大占可投资金 50%（原20%）
    'default_quantity': 200,           # 默认买入数量(股)
    'strong_signal_quantity': 400,     # 强信号加仓(股)
    'min_cash_reserve_pct': 0.30,      # 至少保留 30% 现金
}


# ============================================================
# 红色信号处理策略
# ============================================================

RED_SIGNAL_ACTIONS: Dict[str, str] = {
    'mega_sell':     'auto_sell',   # 巨量砸盘 → 自动止损卖出
    'reversal_bear': 'warn',       # 资金转负 → 风控预警
    'sustained_out': 'warn',       # 持续流出 → 风控预警
}


# ============================================================
# 冷却与信号强度映射
# ============================================================

COOLDOWN_MINUTES = 30  # 同股票交易冷却期（分钟）

# Sniper 信号 → 标准强度映射 (0~100)
SNIPER_STRENGTH_MAP: Dict[str, float] = {
    'mega_buy':      90.0,    # 巨量抢筹 — 最强买入信号
    'accel_in':      75.0,    # 资金加速流入
    'reversal_bull': 70.0,    # 资金由负转正
    'mega_sell':     95.0,    # 巨量砸盘 — 最强风险信号
    'reversal_bear': 70.0,    # 资金由正转负
    'sustained_out': 65.0,    # 持续流出
}


# ============================================================
# 数据模型
# ============================================================

@dataclass
class TradeSignalEvent:
    """所有信号源的标准化输出"""

    source: str              # 'sniper' | 'anomaly' | 'strategy'
    stock_code: str
    stock_name: str
    direction: str           # 'BUY' | 'SELL' | 'WARN'
    strength: float          # 0~100 信号强度
    price: float             # 当前/触发价格
    reason: str              # 人类可读原因
    timestamp: datetime = field(default_factory=datetime.now)

    # Sniper 专用
    sniper_signal_type: str = ''

    # 评分/异动 专用
    scorer_score: int = 0
    trade_params: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'source': self.source,
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'direction': self.direction,
            'strength': self.strength,
            'price': self.price,
            'reason': self.reason,
            'timestamp': self.timestamp.isoformat(),
            'sniper_signal_type': self.sniper_signal_type,
            'scorer_score': self.scorer_score,
            'trade_params': self.trade_params,
        }


@dataclass
class TradeDecision:
    """引擎的输出决策"""

    stock_code: str
    stock_name: str
    direction: str           # 'BUY' | 'SELL'
    price: float
    quantity: int
    reason: str
    sources: List[str]       # 触发的信号源列表
    resonance_type: str      # 'dual_source' | 'strong_single' | 'multi_green'
    simulated: bool = True   # True=模拟模式, False=实盘

    # 交易参数（传递给 AutoTradeService）
    buy_dip_pct: float = 1.0
    take_profit_pct: float = 5.0       # 回测最优: 5%（原10%）
    stop_loss_pct: float = 3.0         # 回测最优: 3%（原8%）

    def to_dict(self) -> Dict[str, Any]:
        return {
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'direction': self.direction,
            'price': self.price,
            'quantity': self.quantity,
            'reason': self.reason,
            'sources': self.sources,
            'resonance_type': self.resonance_type,
            'simulated': self.simulated,
            'buy_dip_pct': self.buy_dip_pct,
            'take_profit_pct': self.take_profit_pct,
            'stop_loss_pct': self.stop_loss_pct,
        }
