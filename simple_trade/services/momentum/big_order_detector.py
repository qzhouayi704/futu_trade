#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
大单聚集检测器

检测:
- 主力买入聚集（5min内同方向大单>=3笔）
- 主力卖出聚集
- 大单+突破位共振
"""

import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Optional

from .ticker_aggregator import AggregatedBar

logger = logging.getLogger(__name__)


@dataclass
class BigOrderSignal:
    """大单信号"""
    stock_code: str
    signal_type: str       # BIG_BUY_CLUSTER / BIG_SELL_CLUSTER / BIG_ORDER_BATTLE
    description: str
    big_buy_count: int
    big_sell_count: int
    big_buy_ratio: float   # 大单占比
    price: float
    confidence: float
    timestamp: float


class BigOrderDetector:
    """大单聚集检测器"""

    # 大单定义：单bar买/卖额 > 历史均值的N倍
    BIG_ORDER_MULTIPLIER = 3.0
    # 聚集定义：连续N个bar中有M个大单
    CLUSTER_WINDOW = 5     # 窗口(bar数)
    CLUSTER_MIN = 3        # 最少大单数

    def __init__(self, history_size: int = 60):
        self._buy_amt_history: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=history_size)
        )
        self._sell_amt_history: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=history_size)
        )
        # 大单标记窗口
        self._big_buy_window: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=self.CLUSTER_WINDOW)
        )
        self._big_sell_window: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=self.CLUSTER_WINDOW)
        )
        self._last_cluster_signal: dict[str, float] = {}
        self._cooldown = 300  # 5min冷却

    def reset_daily(self):
        self._buy_amt_history.clear()
        self._sell_amt_history.clear()
        self._big_buy_window.clear()
        self._big_sell_window.clear()
        self._last_cluster_signal.clear()

    def update(self, bar: AggregatedBar) -> Optional[BigOrderSignal]:
        code = bar.stock_code

        self._buy_amt_history[code].append(bar.buy_turnover)
        self._sell_amt_history[code].append(bar.sell_turnover)

        buy_hist = list(self._buy_amt_history[code])
        sell_hist = list(self._sell_amt_history[code])

        if len(buy_hist) < 10:
            return None

        avg_buy = sum(buy_hist[:-1]) / (len(buy_hist) - 1) if len(buy_hist) > 1 else 1
        avg_sell = sum(sell_hist[:-1]) / (len(sell_hist) - 1) if len(sell_hist) > 1 else 1

        # 判断当前bar是否有大单
        is_big_buy = bar.buy_turnover > avg_buy * self.BIG_ORDER_MULTIPLIER if avg_buy > 0 else False
        is_big_sell = bar.sell_turnover > avg_sell * self.BIG_ORDER_MULTIPLIER if avg_sell > 0 else False

        self._big_buy_window[code].append(1 if is_big_buy else 0)
        self._big_sell_window[code].append(1 if is_big_sell else 0)

        # 冷却检查
        last = self._last_cluster_signal.get(code, 0)
        if bar.timestamp - last < self._cooldown:
            return None

        buy_cluster = sum(self._big_buy_window[code])
        sell_cluster = sum(self._big_sell_window[code])

        total_turnover = bar.buy_turnover + bar.sell_turnover
        big_buy_ratio = bar.buy_turnover / total_turnover if total_turnover > 0 else 0

        # 主力买入聚集
        if buy_cluster >= self.CLUSTER_MIN and bar.bsr > 1.0:
            self._last_cluster_signal[code] = bar.timestamp
            return BigOrderSignal(
                stock_code=code, signal_type="BIG_BUY_CLUSTER",
                description=f"主力买入聚集: {self.CLUSTER_WINDOW}分钟内{buy_cluster}个大买单, 占比{big_buy_ratio:.0%}",
                big_buy_count=buy_cluster, big_sell_count=sell_cluster,
                big_buy_ratio=big_buy_ratio, price=bar.close_price,
                confidence=min(1.0, buy_cluster / 5),
                timestamp=bar.timestamp,
            )

        # 主力卖出聚集
        if sell_cluster >= self.CLUSTER_MIN and bar.bsr < 1.0:
            self._last_cluster_signal[code] = bar.timestamp
            return BigOrderSignal(
                stock_code=code, signal_type="BIG_SELL_CLUSTER",
                description=f"主力卖出聚集: {self.CLUSTER_WINDOW}分钟内{sell_cluster}个大卖单",
                big_buy_count=buy_cluster, big_sell_count=sell_cluster,
                big_buy_ratio=big_buy_ratio, price=bar.close_price,
                confidence=min(1.0, sell_cluster / 5),
                timestamp=bar.timestamp,
            )

        # 大单对冲
        if buy_cluster >= 2 and sell_cluster >= 2:
            self._last_cluster_signal[code] = bar.timestamp
            return BigOrderSignal(
                stock_code=code, signal_type="BIG_ORDER_BATTLE",
                description=f"多空激战: 买方{buy_cluster}个大单 vs 卖方{sell_cluster}个大单",
                big_buy_count=buy_cluster, big_sell_count=sell_cluster,
                big_buy_ratio=big_buy_ratio, price=bar.close_price,
                confidence=0.5,
                timestamp=bar.timestamp,
            )

        return None
