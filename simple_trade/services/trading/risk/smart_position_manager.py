#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能持仓管理器

基于回测数据的持仓管理：
- 分批止盈替代一刀切（回测显示利润捕获率仅-10.7%）
- ATR自适应止损（替代固定%止损）
- 5分钟线趋势保护

职责：
- 分批阶梯止盈（3%/6%/10%）
- ATR自适应止损线计算
- 5分钟趋势信号（连续阴线减仓）
- 最小持仓时间强制
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum

logger = logging.getLogger(__name__)


class TakeProfitStage(Enum):
    """止盈阶段"""
    NONE = "none"             # 未触发
    STAGE1 = "stage1"         # 盈利3%，卖30%
    STAGE2 = "stage2"         # 盈利6%，再卖40%
    STAGE3 = "stage3"         # 盈利10%或回撤3%，清仓


@dataclass
class PositionConfig:
    """持仓管理配置"""
    # 分批止盈阈值
    tp_stage1_pct: float = 3.0     # 盈利3% → 卖30%
    tp_stage1_ratio: float = 0.3
    tp_stage2_pct: float = 6.0     # 盈利6% → 再卖40%
    tp_stage2_ratio: float = 0.4
    tp_stage3_pct: float = 10.0    # 盈利10% → 清仓
    tp_pullback_pct: float = 3.0   # 从最高回撤3% → 清仓

    # ATR止损
    atr_stop_multiplier: float = 1.5  # 止损线 = 1.5 × ATR
    emergency_multiplier: float = 2.5 # 紧急止损 = 2.5 × ATR（可跳过最小持仓时间）

    # 趋势保护
    max_consecutive_down: int = 3  # 连续3根5min阴线 → 减仓50%
    trend_reduce_ratio: float = 0.5

    # 最小持仓
    min_hold_seconds: int = 300    # 5分钟


@dataclass
class PositionState:
    """单只持仓的状态"""
    stock_code: str
    stock_name: str
    entry_price: float
    entry_time: datetime
    total_qty: int              # 初始总股数
    remaining_qty: int          # 剩余股数
    highest_price: float        # 持仓期间最高价
    atr: float                  # ATR值（绝对值）
    current_stage: TakeProfitStage = TakeProfitStage.NONE

    @property
    def atr_pct(self) -> float:
        """ATR百分比"""
        return self.atr / self.entry_price * 100 if self.entry_price > 0 else 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'stock_code': self.stock_code,
            'entry_price': self.entry_price,
            'entry_time': self.entry_time.isoformat(),
            'total_qty': self.total_qty,
            'remaining_qty': self.remaining_qty,
            'highest_price': self.highest_price,
            'atr': self.atr,
            'atr_pct': round(self.atr_pct, 2),
            'current_stage': self.current_stage.value,
        }


@dataclass
class PositionAction:
    """持仓操作指令"""
    action: str          # 'HOLD' / 'SELL_PARTIAL' / 'SELL_ALL'
    qty_to_sell: int     # 卖出股数
    reason: str
    is_emergency: bool = False  # 是否紧急（可跳过最小持仓时间）

    def to_dict(self) -> Dict[str, Any]:
        return {
            'action': self.action,
            'qty_to_sell': self.qty_to_sell,
            'reason': self.reason,
            'is_emergency': self.is_emergency,
        }


class SmartPositionManager:
    """
    智能持仓管理器

    使用方式：
    1. 买入后调用 register_position() 注册持仓
    2. 每次价格更新调用 evaluate() 获取操作指令
    3. 执行操作后调用 update_after_sell() 更新状态
    """

    def __init__(self, config: Optional[PositionConfig] = None):
        self.config = config or PositionConfig()
        self._positions: Dict[str, PositionState] = {}

    # ── 公��� API ─────────────────────────────────────

    def register_position(self, stock_code: str, stock_name: str,
                          entry_price: float, qty: int, atr: float,
                          entry_time: Optional[datetime] = None):
        """注册新持仓"""
        self._positions[stock_code] = PositionState(
            stock_code=stock_code,
            stock_name=stock_name,
            entry_price=entry_price,
            entry_time=entry_time or datetime.now(),
            total_qty=qty,
            remaining_qty=qty,
            highest_price=entry_price,
            atr=atr,
        )
        logger.info(
            f"[PositionMgr] 注册持仓 {stock_code} | "
            f"价格={entry_price} 数量={qty} ATR={atr}({atr/entry_price*100:.1f}%)"
        )

    def evaluate(self, stock_code: str, current_price: float,
                 consecutive_down_bars: int = 0,
                 current_time: Optional[datetime] = None) -> PositionAction:
        """
        评估持仓操作

        Args:
            current_price: 当前价格
            consecutive_down_bars: 连续5min阴线数
        """
        pos = self._positions.get(stock_code)
        if not pos or pos.remaining_qty <= 0:
            return PositionAction('HOLD', 0, '无持仓')

        now = current_time or datetime.now()

        # 更新最高价
        if current_price > pos.highest_price:
            pos.highest_price = current_price

        pnl_pct = (current_price - pos.entry_price) / pos.entry_price * 100
        pullback_pct = (pos.highest_price - current_price) / pos.entry_price * 100
        stop_loss_price = pos.entry_price * (1 - self.config.atr_stop_multiplier * pos.atr_pct / 100)
        emergency_price = pos.entry_price * (1 - self.config.emergency_multiplier * pos.atr_pct / 100)

        # ── 紧急止损（可跳过最小持仓时间）──────
        if current_price <= emergency_price:
            return PositionAction(
                'SELL_ALL', pos.remaining_qty,
                f"紧急止损: 价格{current_price}跌破{emergency_price:.2f}(2.5×ATR)",
                is_emergency=True,
            )

        # ── 最小持仓时间检查 ──────────────────
        hold_seconds = (now - pos.entry_time).total_seconds()
        if hold_seconds < self.config.min_hold_seconds:
            return PositionAction('HOLD', 0,
                f"持仓{hold_seconds:.0f}秒<{self.config.min_hold_seconds}秒，继续持有")

        # ── ATR止损 ──────────────────────────
        if current_price <= stop_loss_price:
            return PositionAction(
                'SELL_ALL', pos.remaining_qty,
                f"ATR止损: 价格{current_price}跌破{stop_loss_price:.2f}(1.5×ATR={pos.atr_pct*1.5:.1f}%)",
            )

        # ── 趋势保护（连续阴线减仓）──────────
        if consecutive_down_bars >= self.config.max_consecutive_down:
            reduce_qty = int(pos.remaining_qty * self.config.trend_reduce_ratio)
            if reduce_qty > 0:
                return PositionAction(
                    'SELL_PARTIAL', reduce_qty,
                    f"趋势保护: 连续{consecutive_down_bars}根阴线，减仓{self.config.trend_reduce_ratio*100:.0f}%",
                )

        # ── 分批止盈 ──────────────────────────

        # Stage 3: 盈利10%+ 或 从高点回撤3%（已过stage1/2后）
        if pos.current_stage in (TakeProfitStage.STAGE1, TakeProfitStage.STAGE2):
            if pnl_pct >= self.config.tp_stage3_pct:
                pos.current_stage = TakeProfitStage.STAGE3
                return PositionAction(
                    'SELL_ALL', pos.remaining_qty,
                    f"止盈Stage3: 盈利{pnl_pct:.1f}%≥{self.config.tp_stage3_pct}%，清仓",
                )
            if pullback_pct >= self.config.tp_pullback_pct and pos.highest_price > pos.entry_price:
                pos.current_stage = TakeProfitStage.STAGE3
                return PositionAction(
                    'SELL_ALL', pos.remaining_qty,
                    f"回撤保护: 从高点{pos.highest_price:.2f}回撤{pullback_pct:.1f}%≥{self.config.tp_pullback_pct}%",
                )

        # Stage 2: 盈利6%
        if pos.current_stage == TakeProfitStage.STAGE1 and pnl_pct >= self.config.tp_stage2_pct:
            sell_qty = int(pos.total_qty * self.config.tp_stage2_ratio)
            sell_qty = min(sell_qty, pos.remaining_qty)
            if sell_qty > 0:
                pos.current_stage = TakeProfitStage.STAGE2
                return PositionAction(
                    'SELL_PARTIAL', sell_qty,
                    f"止盈Stage2: 盈利{pnl_pct:.1f}%≥{self.config.tp_stage2_pct}%，卖{self.config.tp_stage2_ratio*100:.0f}%",
                )

        # Stage 1: 盈利3%
        if pos.current_stage == TakeProfitStage.NONE and pnl_pct >= self.config.tp_stage1_pct:
            sell_qty = int(pos.total_qty * self.config.tp_stage1_ratio)
            sell_qty = min(sell_qty, pos.remaining_qty)
            if sell_qty > 0:
                pos.current_stage = TakeProfitStage.STAGE1
                return PositionAction(
                    'SELL_PARTIAL', sell_qty,
                    f"止盈Stage1: 盈利{pnl_pct:.1f}%≥{self.config.tp_stage1_pct}%，卖{self.config.tp_stage1_ratio*100:.0f}%",
                )

        # ── 继续持有 ──────────────────────────
        return PositionAction('HOLD', 0,
            f"持有 | 盈亏{pnl_pct:+.1f}% | 最高{pos.highest_price:.2f} | 止损{stop_loss_price:.2f}")

    def update_after_sell(self, stock_code: str, sold_qty: int):
        """卖出后更新状态"""
        pos = self._positions.get(stock_code)
        if pos:
            pos.remaining_qty -= sold_qty
            if pos.remaining_qty <= 0:
                logger.info(f"[PositionMgr] {stock_code} 已清仓")
            else:
                logger.info(f"[PositionMgr] {stock_code} 剩余 {pos.remaining_qty}/{pos.total_qty}")

    def get_position(self, stock_code: str) -> Optional[PositionState]:
        """获取持仓状态"""
        return self._positions.get(stock_code)

    def get_all_positions(self) -> Dict[str, PositionState]:
        """获取所有活跃持仓"""
        return {k: v for k, v in self._positions.items() if v.remaining_qty > 0}

    def get_stop_loss_price(self, stock_code: str) -> Optional[float]:
        """获取指定持仓的止损价"""
        pos = self._positions.get(stock_code)
        if pos:
            return pos.entry_price * (1 - self.config.atr_stop_multiplier * pos.atr_pct / 100)
        return None

    def remove_position(self, stock_code: str):
        """移除持仓"""
        self._positions.pop(stock_code, None)

    def reset_daily(self):
        """每日重置"""
        self._positions.clear()
        logger.info("[PositionMgr] 持仓已重置")
