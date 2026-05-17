#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
StockSnapshot — 不可变股票指标快照

一只股票在某一时刻的全部标准化指标。
数据引擎构建一次，所有策略共享读取。

设计原则：
- frozen=True: 不可变，策略无法篡改数据
- 所有字段都是基础类型或Optional，无复杂对象
- 策略通过读取快照字段来评分，不再自己获取数据
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any


@dataclass(frozen=True)
class StockSnapshot:
    """一只股票在某一时刻的完整指标快照（不可变）"""

    # ── 标识 ──────────────────────────────
    code: str
    name: str
    market: str                          # "HK" / "US"
    timestamp: datetime = field(default_factory=datetime.now)

    # ── 价格与行情 ────────────────────────
    last_price: float = 0.0
    change_rate: float = 0.0             # 当日涨跌幅 %
    prev_close: float = 0.0
    open_price: float = 0.0
    high_price: float = 0.0
    low_price: float = 0.0
    amplitude: float = 0.0              # 振幅 %

    # ── 量能 ──────────────────────────────
    volume: int = 0                      # 成交量(股)
    turnover: float = 0.0               # 成交额
    turnover_rate: float = 0.0          # 换手率 %
    volume_ratio: float = 0.0           # 量比

    # ── 资金流向 ──────────────────────────
    # 来源: capital_flow_analyzer.py (只算一次)
    capital_score: float = 50.0          # 0-100 资金综合评分
    net_inflow_ratio: float = 0.0        # 主力净流入占比
    big_order_buy_ratio: float = 0.5     # 大单买入占比 0-1
    main_net_inflow: float = 0.0         # 主力净流入额

    # ── 价格位置与趋势 ───────────────────
    # 来源: K线计算 (只算一次)
    price_position_30d: float = 50.0     # 30日价格位置 0-100%
    kline_position_20d: float = 0.5      # K线20日位置 0-1+
    change_5d: float = 0.0              # 5日累计涨幅 %
    prev_day_change: float = 0.0        # 前日涨幅 %

    # ── 板块信息 ──────────────────────────
    plate_strength: float = 0.0          # 板块强势度 0-100
    plate_rank: int = 999                # 板块排名
    plates: tuple = ()                   # 所属板块 (tuple for frozen)

    # ── 成交分析（实时，可选）──────────────
    # 来源: combined_analyzer / ticker_analyzer
    ticker_score: Optional[float] = None          # -100~+100
    ticker_buy_sell_ratio: Optional[float] = None  # 主动买卖力量比
    ticker_big_order_pct: Optional[float] = None   # 大单成交占比 %
    ticker_signal: Optional[str] = None            # bullish/bearish/neutral

    # ── 流动性 ────────────────────────────
    liquidity_score: Optional[float] = None   # 0-100
    liquidity_level: Optional[str] = None     # A/B/C/D
    is_volume_anomaly: bool = False

    # ── 持仓与标签 ────────────────────────
    is_position: bool = False
    stock_tag: Optional[Dict[str, Any]] = None

    # ── 派生便捷属性 ──────────────────────

    @property
    def capital_signal(self) -> str:
        """统一的资金信号判定（消除多引擎阈值不一致问题）"""
        if self.capital_score >= 70:
            return "strong_bullish"
        elif self.capital_score >= 60:
            return "bullish"
        elif self.capital_score >= 45:
            return "neutral"
        elif self.capital_score >= 30:
            return "bearish"
        else:
            return "strong_bearish"

    @property
    def capital_signal_simple(self) -> str:
        """兼容旧接口的3档信号"""
        s = self.capital_signal
        if s in ("strong_bullish", "bullish"):
            return "bullish"
        elif s in ("strong_bearish", "bearish"):
            return "bearish"
        return "neutral"

    @property
    def is_hk(self) -> bool:
        return self.market == "HK" or self.code.startswith("HK.")

    @property
    def is_us(self) -> bool:
        return self.market == "US" or self.code.startswith("US.")

    def to_dict(self) -> Dict[str, Any]:
        """转为字典（用于API响应）"""
        return {
            'code': self.code,
            'name': self.name,
            'market': self.market,
            'last_price': self.last_price,
            'change_rate': self.change_rate,
            'amplitude': self.amplitude,
            'volume': self.volume,
            'turnover': self.turnover,
            'turnover_rate': self.turnover_rate,
            'volume_ratio': self.volume_ratio,
            'capital_score': self.capital_score,
            'capital_signal': self.capital_signal_simple,
            'net_inflow_ratio': self.net_inflow_ratio,
            'big_order_buy_ratio': self.big_order_buy_ratio,
            'main_net_inflow': self.main_net_inflow,
            'price_position_30d': self.price_position_30d,
            'kline_position_20d': self.kline_position_20d,
            'change_5d': self.change_5d,
            'prev_day_change': self.prev_day_change,
            'plate_strength': self.plate_strength,
            'plate_rank': self.plate_rank,
            'plates': list(self.plates),
            'ticker_score': self.ticker_score,
            'ticker_signal': self.ticker_signal,
            'liquidity_score': self.liquidity_score,
            'liquidity_level': self.liquidity_level,
            'is_volume_anomaly': self.is_volume_anomaly,
            'is_position': self.is_position,
            'stock_tag': self.stock_tag,
        }
