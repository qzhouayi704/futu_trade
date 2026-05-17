#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易频率守卫

基于回测数据的纪律管控：
- 当前日均40笔 → 限制到 ≤8笔
- 同股同日反复交易是主要亏损来源

职责：
- 控制每日总下单上限
- 限制同股同日买入次数
- 日亏损熔断
- 换票最小间隔
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class GuardConfig:
    """频率管控配置"""
    max_daily_trades: int = 8              # 每日总下单上限（买+卖）
    max_same_stock_buys: int = 2           # 同股同日买入上限
    daily_loss_circuit_pct: float = 2.0    # 日亏损熔断阈值（账户%）
    min_rotation_interval_min: int = 15    # 换票最小间隔（分钟）
    min_hold_seconds: int = 300            # 最小持仓时间（秒）= 5分钟
    phase2_buy_blocked: bool = True        # 第二阶段(9:40-10:00)是否禁买


class TradeFrequencyGuard:
    """
    交易频率守卫

    在下单入口处强制拦截，确保交易纪律。

    使用方式：
    1. 每日开盘前调用 reset_daily()
    2. 每次下单前调用 can_buy() / can_sell() 检查
    3. 下单成功后调用 record_trade()
    4. 平仓亏损后调用 record_loss()
    """

    def __init__(self, config: Optional[GuardConfig] = None):
        self.config = config or GuardConfig()
        self._trade_count: int = 0
        self._buy_count_by_stock: Dict[str, int] = {}
        self._last_trade_time_by_stock: Dict[str, datetime] = {}
        self._daily_pnl: float = 0.0
        self._account_value: float = 0.0
        self._circuit_broken: bool = False
        self._date: str = ""

    # ── 公开 API ─────────────────────────────────────

    def can_buy(self, stock_code: str, current_time: Optional[datetime] = None) -> tuple[bool, str]:
        """
        检查是否允许买入

        Returns:
            (允许, 拒绝原因)  拒绝原因为空字符串表示允许
        """
        now = current_time or datetime.now()

        # 1. 日亏损熔断
        if self._circuit_broken:
            return False, f"日亏损熔断(累亏{self._daily_pnl:.2f})"

        # 2. 日交易上限
        if self._trade_count >= self.config.max_daily_trades:
            return False, f"日交易已达上限{self.config.max_daily_trades}笔"

        # 3. 同股买入上限
        stock_buys = self._buy_count_by_stock.get(stock_code, 0)
        if stock_buys >= self.config.max_same_stock_buys:
            return False, f"{stock_code}今日已买入{stock_buys}次(上限{self.config.max_same_stock_buys})"

        # 4. 第二阶段禁买（9:40-10:00）
        if self.config.phase2_buy_blocked:
            time_str = now.strftime('%H:%M')
            if '09:40' <= time_str < '10:00':
                return False, f"当前为观察期(9:40-10:00)，原则上不新开仓"

        # 5. 换票间隔
        last_trade = self._last_trade_time_by_stock.get(stock_code)
        if last_trade:
            elapsed = (now - last_trade).total_seconds() / 60
            if elapsed < self.config.min_rotation_interval_min:
                remaining = self.config.min_rotation_interval_min - elapsed
                return False, f"{stock_code}距上次交易{elapsed:.0f}分钟(需间隔{self.config.min_rotation_interval_min}分钟)"

        return True, ""

    def can_sell(self, stock_code: str, buy_time: Optional[datetime] = None,
                 current_time: Optional[datetime] = None,
                 is_emergency_stop: bool = False) -> tuple[bool, str]:
        """
        检查是否允许卖出

        Args:
            buy_time: 买入时间（用于计算最小持仓时间）
            is_emergency_stop: 是否紧急止损（跌破2×ATR等极端情况可跳过持仓时间限制）
        """
        if is_emergency_stop:
            return True, ""

        now = current_time or datetime.now()

        # 最小持仓时间检查
        if buy_time:
            hold_seconds = (now - buy_time).total_seconds()
            if hold_seconds < self.config.min_hold_seconds:
                remaining = self.config.min_hold_seconds - hold_seconds
                return False, f"持仓{hold_seconds:.0f}秒(需≥{self.config.min_hold_seconds}秒，剩{remaining:.0f}秒)"

        return True, ""

    def record_trade(self, stock_code: str, side: str, current_time: Optional[datetime] = None):
        """
        记录一笔成交

        Args:
            side: 'BUY' 或 'SELL'
        """
        now = current_time or datetime.now()
        self._trade_count += 1
        self._last_trade_time_by_stock[stock_code] = now

        if side == 'BUY':
            self._buy_count_by_stock[stock_code] = self._buy_count_by_stock.get(stock_code, 0) + 1

        logger.info(
            f"[FrequencyGuard] 记录交易 {side} {stock_code} | "
            f"日交易: {self._trade_count}/{self.config.max_daily_trades} | "
            f"该股买入: {self._buy_count_by_stock.get(stock_code, 0)}/{self.config.max_same_stock_buys}"
        )

    def record_pnl(self, pnl: float, account_value: float):
        """
        记录盈亏，检查是否触发熔断

        Args:
            pnl: 本次交易盈亏金额
            account_value: 当前账户总值
        """
        self._daily_pnl += pnl
        self._account_value = account_value

        if account_value > 0:
            loss_pct = abs(self._daily_pnl) / account_value * 100
            if self._daily_pnl < 0 and loss_pct >= self.config.daily_loss_circuit_pct:
                self._circuit_broken = True
                logger.warning(
                    f"[FrequencyGuard] 日亏损熔断! "
                    f"累亏{self._daily_pnl:.2f} = 账户{loss_pct:.2f}% >= {self.config.daily_loss_circuit_pct}%"
                )

    def get_phase(self, current_time: Optional[datetime] = None) -> str:
        """获取当前交易阶段"""
        now = current_time or datetime.now()
        t = now.strftime('%H:%M')
        if t < '09:30':
            return 'PRE_MARKET'
        elif t < '09:40':
            return 'PHASE1_OPENING'     # 开盘抢先手
        elif t < '10:00':
            return 'PHASE2_OBSERVE'     # 观察期（只卖不买）
        elif t < '12:00':
            return 'PHASE3_ROTATION'    # 资金流换票
        elif t < '13:00':
            return 'LUNCH_BREAK'
        elif t < '16:00':
            return 'PHASE3_ROTATION'    # 下午继续换票阶段
        else:
            return 'AFTER_HOURS'

    def get_status(self) -> Dict[str, Any]:
        """获取当前管控状态"""
        return {
            'date': self._date,
            'trade_count': self._trade_count,
            'max_trades': self.config.max_daily_trades,
            'buy_counts': dict(self._buy_count_by_stock),
            'daily_pnl': round(self._daily_pnl, 2),
            'circuit_broken': self._circuit_broken,
            'current_phase': self.get_phase(),
        }

    def reset_daily(self):
        """每日开盘前重置"""
        self._trade_count = 0
        self._buy_count_by_stock.clear()
        self._last_trade_time_by_stock.clear()
        self._daily_pnl = 0.0
        self._circuit_broken = False
        self._date = datetime.now().strftime('%Y-%m-%d')
        logger.info("[FrequencyGuard] 日度数据已重置")
