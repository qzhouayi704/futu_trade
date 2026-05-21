#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
逐笔数据聚合器

将逐笔成交数据实时聚合为1分钟bar，计算:
- BSR (Buy-Sell Ratio)
- Delta / CumDelta
- VWAP
- 成交速度
"""

import time
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class AggregatedBar:
    """1分钟聚合bar"""
    stock_code: str
    timestamp: float           # bar开始时间(Unix秒)
    time_str: str              # HH:MM 格式

    buy_volume: int = 0
    sell_volume: int = 0
    buy_turnover: float = 0.0
    sell_turnover: float = 0.0
    tick_count: int = 0

    open_price: float = 0.0
    close_price: float = 0.0
    high_price: float = 0.0
    low_price: float = 999999.0

    # 计算指标
    bsr: float = 1.0           # Buy-Sell Ratio (turnover)
    delta: int = 0             # 买量 - 卖量
    cum_delta: int = 0         # 累积Delta
    vwap: float = 0.0          # 成交量加权均价
    velocity: int = 0          # 成交笔数(速度)


@dataclass
class _BarAccumulator:
    """单只股票的bar累积器"""
    buy_vol: int = 0
    sell_vol: int = 0
    buy_amt: float = 0.0
    sell_amt: float = 0.0
    ticks: int = 0
    open_p: float = 0.0
    close_p: float = 0.0
    high_p: float = 0.0
    low_p: float = 999999.0
    pv_sum: float = 0.0        # price * volume 累积(用于VWAP)
    vol_sum: int = 0           # volume 累积


class TickerAggregator:
    """逐笔数据聚合器 — 将tick流聚合为1分钟bar"""

    BAR_INTERVAL = 60  # 秒

    def __init__(self):
        self._accumulators: dict[str, _BarAccumulator] = {}
        self._current_bar_ts: dict[str, int] = {}  # stock -> 当前bar的分钟时间戳

        # 全局累积指标(每只股票)
        self._cum_delta: dict[str, int] = defaultdict(int)
        self._cum_pv: dict[str, float] = defaultdict(float)
        self._cum_vol: dict[str, int] = defaultdict(int)

    def reset_daily(self):
        """每日重置"""
        self._accumulators.clear()
        self._current_bar_ts.clear()
        self._cum_delta.clear()
        self._cum_pv.clear()
        self._cum_vol.clear()
        logger.info("[TickerAggregator] 每日重置完成")

    def on_tick(self, stock_code: str, price: float, volume: int,
                turnover: float, direction: str, timestamp_ms: int
                ) -> Optional[AggregatedBar]:
        """
        接收一条逐笔数据，返回完成的bar（如果有）

        Args:
            stock_code: 股票代码
            price: 成交价
            volume: 成交量
            turnover: 成交额
            direction: 'BUY' / 'SELL' / 'NEUTRAL'
            timestamp_ms: Unix毫秒时间戳

        Returns:
            如果一个1分钟bar刚刚完成，返回该bar；否则返回None
        """
        bar_ts = (timestamp_ms // (self.BAR_INTERVAL * 1000)) * (self.BAR_INTERVAL * 1000)
        completed_bar = None

        # 检查是否需要关闭上一个bar
        prev_ts = self._current_bar_ts.get(stock_code)
        if prev_ts is not None and bar_ts > prev_ts:
            completed_bar = self._close_bar(stock_code, prev_ts)

        # 更新当前bar
        self._current_bar_ts[stock_code] = bar_ts

        acc = self._accumulators.get(stock_code)
        if acc is None:
            acc = _BarAccumulator()
            self._accumulators[stock_code] = acc

        # 如果是新bar的第一条tick
        if prev_ts is None or bar_ts > (prev_ts or 0):
            acc.buy_vol = acc.sell_vol = 0
            acc.buy_amt = acc.sell_amt = 0.0
            acc.ticks = 0
            acc.open_p = price
            acc.high_p = price
            acc.low_p = price
            acc.pv_sum = 0.0
            acc.vol_sum = 0

        # 累积
        acc.ticks += 1
        acc.close_p = price
        acc.high_p = max(acc.high_p, price)
        acc.low_p = min(acc.low_p, price)
        acc.pv_sum += price * volume
        acc.vol_sum += volume

        if direction == 'BUY':
            acc.buy_vol += volume
            acc.buy_amt += turnover
        elif direction == 'SELL':
            acc.sell_vol += volume
            acc.sell_amt += turnover

        return completed_bar

    def flush(self, stock_code: str) -> Optional[AggregatedBar]:
        """强制关闭当前bar（用于收盘时）"""
        ts = self._current_bar_ts.get(stock_code)
        if ts is not None:
            return self._close_bar(stock_code, ts)
        return None

    def _close_bar(self, stock_code: str, bar_ts: int) -> AggregatedBar:
        """关闭一个bar，计算所有指标"""
        acc = self._accumulators.get(stock_code, _BarAccumulator())

        # Delta
        delta = acc.buy_vol - acc.sell_vol
        self._cum_delta[stock_code] += delta

        # VWAP
        self._cum_pv[stock_code] += acc.pv_sum
        self._cum_vol[stock_code] += acc.vol_sum
        cum_vol = self._cum_vol[stock_code]
        vwap = self._cum_pv[stock_code] / cum_vol if cum_vol > 0 else acc.close_p

        # BSR
        bsr = acc.buy_amt / acc.sell_amt if acc.sell_amt > 0 else (
            2.0 if acc.buy_amt > 0 else 1.0
        )

        # 时间格式
        import datetime
        dt = datetime.datetime.fromtimestamp(
            bar_ts / 1000,
            tz=datetime.timezone(datetime.timedelta(hours=8))
        )
        time_str = dt.strftime('%H:%M')

        bar = AggregatedBar(
            stock_code=stock_code,
            timestamp=bar_ts / 1000,
            time_str=time_str,
            buy_volume=acc.buy_vol,
            sell_volume=acc.sell_vol,
            buy_turnover=acc.buy_amt,
            sell_turnover=acc.sell_amt,
            tick_count=acc.ticks,
            open_price=acc.open_p,
            close_price=acc.close_p,
            high_price=acc.high_p,
            low_price=acc.low_p if acc.low_p < 999999 else acc.close_p,
            bsr=round(bsr, 3),
            delta=delta,
            cum_delta=self._cum_delta[stock_code],
            vwap=round(vwap, 3),
            velocity=acc.ticks,
        )

        # 重置累积器
        self._accumulators[stock_code] = _BarAccumulator()

        return bar
