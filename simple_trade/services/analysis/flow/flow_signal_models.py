#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资金流向信号数据模型

定义信号引擎的核心数据结构：
- FlowSignal: 信号输出
- RuleContext: 规则评估上下文
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class RuleContext:
    """规则评估上下文 — 聚合所有数据源供规则检查"""

    # 基本行情
    stock_code: str = ""
    stock_name: str = ""
    current_price: float = 0.0
    prev_close: float = 0.0
    open_price: float = 0.0
    high_price: float = 0.0
    low_price: float = 0.0
    change_pct: float = 0.0
    volume: int = 0
    turnover: float = 0.0  # 成交额

    # 资金流数据（当日实时）
    capital_flow: Optional[Dict[str, Any]] = None
    main_net_inflow: float = 0.0      # 主力净流入（超大+大单）
    net_inflow_ratio: float = 0.0     # 净流入占比

    # 多日资金流历史
    capital_flow_history: List[Dict[str, Any]] = field(default_factory=list)

    # 技术数据
    vwap: Optional[float] = None                # 当日VWAP
    prev_day_change_pct: Optional[float] = None # 前日涨跌幅
    avg_daily_turnover: float = 0.0             # 日均成交额

    # 分时追踪
    vwap_break_minutes: int = 0  # 价格跌破VWAP持续分钟数

    # K线位置（趋势联动）
    kline_position: Optional[float] = None  # 0~1, 20日K线位置(0=最低,1=最高)

    # 持仓状态
    has_position: bool = False
    position_qty: int = 0

    # 5分钟动量数据（由 Momentum5MinAnalyzer 填充）
    momentum_direction: float = 0.0     # -1~+1，最近3根5分钟K线方向
    momentum_strength: float = 0.0      # 0~1，动量强度
    momentum_acceleration: float = 0.0  # >0加速, <0减速
    momentum_trend: str = "unknown"     # accelerating/stable/decelerating/reversing
    has_top_pattern: bool = False       # 5分钟顶分型
    has_bottom_pattern: bool = False    # 5分钟底分型
    upper_shadow_warning: bool = False  # 上影线过长（冲高被砸）
    lower_shadow_support: bool = False  # 下影线支撑

    # 流动性（由盘口数据填充）
    spread_pct: float = 0.0            # 买卖价差百分比

    # 交易时段
    trading_phase: str = ""            # phase1_opening / phase2_observe / phase3_rotate / lunch_break

    # 大盘/板块环境
    market_change_pct: float = 0.0     # 大盘涨跌幅
    sector_change_pct: float = 0.0     # 所属板块涨跌幅

    # 经纪商一致性数据（由 BrokerConsistencyFilter 填充）
    broker_trap_detected: bool = False          # 是否检测到诱多陷阱
    broker_trap_confidence: float = 0.0         # 陷阱置信度 (0-1)
    broker_analysis_reason: str = ""            # 分析描述


@dataclass
class FlowSignal:
    """资金流向信号"""

    rule_id: str              # "R1" ~ "R11"
    rule_name: str            # 中文名称
    stock_code: str = ""
    stock_name: str = ""
    signal_type: str = ""     # "BUY" / "SELL" / "ALERT"
    price: float = 0.0
    reason: str = ""          # 人类可读的触发原因
    confidence: float = 0.5   # 0-1 置信度
    priority: str = "medium"  # "high" / "medium" / "low"
    action_suggestion: str = ""  # 具体操作建议文案
    source: str = "capital_flow_signal"
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    def to_trade_action(self) -> Dict[str, Any]:
        """转换为 QuotePipeline 的 trade_action 格式"""
        emoji = "🟢" if self.signal_type == "BUY" else "🔴" if self.signal_type == "SELL" else "🟡"
        return {
            'signal_type': self.signal_type,
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'price': self.price,
            'reason': self.reason,
            'message': (
                f"{emoji} [{self.rule_id}]{self.rule_name}: "
                f"{self.stock_name}({self.stock_code}) "
                f"@ {self.price:.3f} — {self.action_suggestion}"
            ),
            'action': f'flow_signal_{self.rule_id.lower()}',
            'source': self.source,
            'timestamp': self.timestamp,
            # 扩展字段
            'flow_signal_detail': {
                'rule_id': self.rule_id,
                'rule_name': self.rule_name,
                'confidence': self.confidence,
                'priority': self.priority,
                'action_suggestion': self.action_suggestion,
            },
        }
