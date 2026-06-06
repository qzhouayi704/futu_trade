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
        'window_minutes': 20,       # 回测优化: 15→20 (75%胜率, PF 4.57)
    },
    # 单源强信号：strength ≥ 80 且 StockScorer 评分 ≥ 80
    'strong_single': {
        'min_strength': 80,
        'min_score': 80,
    },
    # 多重绿色（仅 Sniper）：20分钟内2种以上不同 sniper_signal_type
    'multi_green': {
        'min_distinct_types': 2,
        'window_minutes': 20,       # 回测优化: 15→20
    },
}


# ============================================================
# 仓位控制
# ============================================================

POSITION_CONFIG = {
    'max_total_positions': 2,          # 最多同时持有2只（集中资金）
    'max_single_position_pct': 0.50,   # 单只最大占可投资金 50%
    'min_cash_reserve_pct': 0.30,      # 至少保留 30% 现金
    # 注: 不再使用固定股数(default_quantity/strong_signal_quantity)
    # 改为按资金百分比动态计算: qty = investable * 50% / price
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
# 注: accel_in 仅作为 mega_buy 的确认信号，不独立触发交易
#   回测验证(14天): 纯mega +1.60%/笔, accel独立 -0.53%/笔
SNIPER_STRENGTH_MAP: Dict[str, float] = {
    'mega_buy':      90.0,    # 巨量抢筹 — 唯一的买入触发信号
    'accel_in':       0.0,    # 资金加速流入 — 仅确认信号，不触发交易
    'reversal_bull':  0.0,    # 资金由负转正 (回测表现不佳，降为0)
    'mega_sell':     95.0,    # 巨量砸盘 — 最强风险信号
    'reversal_bear': 30.0,    # 资金由正转负 (降权)
    'sustained_out': 20.0,    # 持续流出 (降权)
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
    capital_score: float = 0.0  # 资金评分（Scanner传入）
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
    take_profit_pct: float = 5.0       # 激活移动止盈的阈值
    trailing_stop_pct: float = 2.0     # 回测优化: 3%→2% (锁利更紧, PF 1.90→4.57)
    stop_loss_pct: float = 5.0         # 回测优化: 3%→5% (避免误杀好股票)

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
