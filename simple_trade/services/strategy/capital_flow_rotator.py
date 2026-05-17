#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资金流换票引擎

10:00后的核心操作模块：基于实时资金流排名，卖出弱势持仓换入强势标的。

职责：
- 实时扫描监控标的的资金流排名
- 识别弱势持仓（资金流出/3根阴线/跌破ATR）
- 推荐强势换入标的（资金流入前3+评分≥50+价格<均价）
- 生成换票建议
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class FlowRanking:
    """标的资金流排名"""
    stock_code: str
    stock_name: str
    net_inflow: float          # 当日净流入金额
    net_inflow_ratio: float    # 净流入比率
    consecutive_bars_up: int   # 连续阳线数（5min级别）
    consecutive_bars_down: int # 连续阴线数
    current_vs_vwap: float     # 当前价 vs VWAP 的偏离%
    score: int = 0             # 盘前评分（来自StockScorer）
    is_held: bool = False      # 是否持仓中


@dataclass
class RotationSignal:
    """换票信号"""
    sell_code: str        # 卖出标的
    sell_name: str
    sell_reason: str      # 卖出原因
    buy_code: str         # 买入标的
    buy_name: str
    buy_reason: str       # 买入原因
    confidence: float     # 置信度 0-1
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            'sell': {'code': self.sell_code, 'name': self.sell_name, 'reason': self.sell_reason},
            'buy': {'code': self.buy_code, 'name': self.buy_name, 'reason': self.buy_reason},
            'confidence': self.confidence,
            'timestamp': self.timestamp,
        }


# ── 卖出触发条件 ──────────────────────────────────────

SELL_TRIGGERS = {
    'flow_outflow': '资金流转为净流出',
    'consecutive_3_down': '连续3根5分钟阴线',
    'below_vwap': '跌破VWAP且放量',
    'profit_pullback': '浮盈回撤超50%',
    'atr_stop': '跌破ATR止损线',
}

# ── 买入条件 ──────────────────────────────────────────

BUY_CONDITIONS = {
    'min_score': 50,               # 换票时评分门槛（比开盘低）
    'min_flow_rank': 3,            # 资金流入排名前3
    'max_price_vs_vwap': 0.0,      # 价格需≤VWAP（负数=低于均价）
    'min_consecutive_up': 2,       # 至少2根连续阳线
}


class CapitalFlowRotator:
    """
    资金流换票引擎

    使用方式：
    1. 实时更新各标的资金流数据 update_flow()
    2. 调用 evaluate_rotation() 获取换票建议
    3. 执行换票后调用 record_rotation()
    """

    def __init__(self):
        self._flow_data: Dict[str, FlowRanking] = {}
        self._held_stocks: Dict[str, Dict[str, Any]] = {}  # code → 持仓信息
        self._rotation_count: int = 0
        self._max_rotations: int = 2

    # ── 公开 API ─────────────────────────────────────

    def update_flow(self, stock_code: str, stock_name: str,
                    net_inflow: float, net_inflow_ratio: float,
                    consecutive_up: int = 0, consecutive_down: int = 0,
                    current_vs_vwap: float = 0.0, score: int = 0,
                    is_held: bool = False):
        """更新标的资金流数据"""
        self._flow_data[stock_code] = FlowRanking(
            stock_code=stock_code,
            stock_name=stock_name,
            net_inflow=net_inflow,
            net_inflow_ratio=net_inflow_ratio,
            consecutive_bars_up=consecutive_up,
            consecutive_bars_down=consecutive_down,
            current_vs_vwap=current_vs_vwap,
            score=score,
            is_held=is_held,
        )

    def update_position(self, stock_code: str, entry_price: float,
                        current_price: float, highest_since_entry: float):
        """更新持仓信息"""
        pnl_pct = (current_price - entry_price) / entry_price * 100 if entry_price > 0 else 0
        max_pnl_pct = (highest_since_entry - entry_price) / entry_price * 100 if entry_price > 0 else 0
        pullback = max_pnl_pct - pnl_pct if max_pnl_pct > 0 else 0

        self._held_stocks[stock_code] = {
            'entry_price': entry_price,
            'current_price': current_price,
            'pnl_pct': pnl_pct,
            'max_pnl_pct': max_pnl_pct,
            'pullback_pct': pullback,
        }

    def evaluate_rotation(self) -> List[RotationSignal]:
        """
        评估换票机会

        Returns:
            换票信号列表（按置信度降序）
        """
        if self._rotation_count >= self._max_rotations:
            return []

        # 1. 找出需要卖出的弱势持仓
        weak_holds = self._find_weak_holds()

        # 2. 找出适合买入的强势标的
        strong_candidates = self._find_strong_candidates()

        # 3. 配对生成换票信号
        signals = []
        for weak in weak_holds:
            if not strong_candidates:
                break
            strong = strong_candidates[0]  # 取最强的
            confidence = self._calc_confidence(weak, strong)
            if confidence >= 0.6:
                signals.append(RotationSignal(
                    sell_code=weak['code'],
                    sell_name=weak['name'],
                    sell_reason=weak['reason'],
                    buy_code=strong.stock_code,
                    buy_name=strong.stock_name,
                    buy_reason=f"资金流入排名前{BUY_CONDITIONS['min_flow_rank']}，评分{strong.score}",
                    confidence=confidence,
                ))
                strong_candidates.pop(0)

        return sorted(signals, key=lambda x: x.confidence, reverse=True)

    def get_flow_ranking(self, top_n: int = 10) -> List[FlowRanking]:
        """获取资金流入排名"""
        return sorted(
            self._flow_data.values(),
            key=lambda x: x.net_inflow,
            reverse=True,
        )[:top_n]

    def record_rotation(self):
        """记录一次换票"""
        self._rotation_count += 1
        logger.info(f"[FlowRotator] 换票次数: {self._rotation_count}/{self._max_rotations}")

    def get_status(self) -> Dict[str, Any]:
        """获取当前状态"""
        ranking = self.get_flow_ranking(5)
        return {
            'rotation_count': self._rotation_count,
            'max_rotations': self._max_rotations,
            'monitored_stocks': len(self._flow_data),
            'held_stocks': len(self._held_stocks),
            'top_inflow': [
                {'code': r.stock_code, 'name': r.stock_name,
                 'inflow': r.net_inflow, 'ratio': r.net_inflow_ratio}
                for r in ranking
            ],
        }

    def reset_daily(self):
        """每日重置"""
        self._flow_data.clear()
        self._held_stocks.clear()
        self._rotation_count = 0
        logger.info("[FlowRotator] 日度数据已重置")

    # ── 内部方法 ─────────────────────────────────────

    def _find_weak_holds(self) -> List[Dict[str, Any]]:
        """找出需要卖出的弱势持仓"""
        weak = []
        for code, pos in self._held_stocks.items():
            flow = self._flow_data.get(code)
            if not flow:
                continue

            reason = ""
            # 资金流出
            if flow.net_inflow < 0:
                reason = SELL_TRIGGERS['flow_outflow']
            # 连续3根阴线
            elif flow.consecutive_bars_down >= 3:
                reason = SELL_TRIGGERS['consecutive_3_down']
            # 跌破VWAP
            elif flow.current_vs_vwap < -2.0:
                reason = SELL_TRIGGERS['below_vwap']
            # 浮盈回撤>50%
            elif pos['max_pnl_pct'] > 2.0 and pos['pullback_pct'] > pos['max_pnl_pct'] * 0.5:
                reason = SELL_TRIGGERS['profit_pullback']

            if reason:
                weak.append({
                    'code': code,
                    'name': flow.stock_name,
                    'reason': reason,
                    'pnl_pct': pos['pnl_pct'],
                })

        return sorted(weak, key=lambda x: x['pnl_pct'])

    def _find_strong_candidates(self) -> List[FlowRanking]:
        """找出适合买入的强势标的"""
        candidates = []
        # 按资金流入排名
        ranking = self.get_flow_ranking(20)

        for r in ranking:
            # 跳过已持仓
            if r.is_held:
                continue
            # 评分门槛
            if r.score < BUY_CONDITIONS['min_score']:
                continue
            # 资金必须净流入
            if r.net_inflow <= 0:
                continue
            # 价格需低于VWAP
            if r.current_vs_vwap > BUY_CONDITIONS['max_price_vs_vwap']:
                continue
            # 趋势确认：至少连续阳线
            if r.consecutive_bars_up < BUY_CONDITIONS['min_consecutive_up']:
                continue

            candidates.append(r)

        return candidates[:BUY_CONDITIONS['min_flow_rank']]

    def _calc_confidence(self, weak: Dict[str, Any], strong: FlowRanking) -> float:
        """计算换票信号置信度"""
        conf = 0.5

        # 弱势持仓亏损越多，换票越有必要
        if weak['pnl_pct'] < -3:
            conf += 0.1
        elif weak['pnl_pct'] < 0:
            conf += 0.05

        # 强势标的评分越高，置信度越高
        if strong.score >= 80:
            conf += 0.2
        elif strong.score >= 60:
            conf += 0.1

        # 资金流入越强
        if strong.net_inflow_ratio > 0.5:
            conf += 0.1
        elif strong.net_inflow_ratio > 0.3:
            conf += 0.05

        # 连续阳线越多
        if strong.consecutive_bars_up >= 3:
            conf += 0.1

        return min(conf, 1.0)
