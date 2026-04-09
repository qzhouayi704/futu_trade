"""
订单流不平衡（Order Flow Imbalance, OFI）计算器

计算买卖盘口的不平衡度，用于评估市场微观结构的买卖压力。
"""
from collections import deque
from datetime import datetime
from typing import Optional

from simple_trade.services.scalping.models import OrderBookData


class OFICalculator:
    """
    订单流不平衡计算器

    计算公式：
    OFI = (Bid_volume - Ask_volume) / (Bid_volume + Ask_volume)

    应用场景：
    - OFI > 0.3 且持续 3 个周期 → 买方压力强，配合突破信号
    - OFI < -0.3 且持续 3 个周期 → 卖方压力强，避免追多
    """

    def __init__(self, history_size: int = 10):
        """
        初始化 OFI 计算器

        Args:
            history_size: 保留的历史 OFI 值数量
        """
        self._history: deque[tuple[datetime, float]] = deque(maxlen=history_size)
        self._current_ofi: Optional[float] = None

    def calculate_ofi(self, orderbook: OrderBookData) -> float:
        """
        计算当前订单流不平衡度

        Args:
            orderbook: 订单簿数据

        Returns:
            OFI 值，范围 [-1, 1]
            - 正值表示买方压力强
            - 负值表示卖方压力强
        """
        # 计算买盘前5档总量
        bid_vol = sum(
            level.volume
            for level in orderbook.bid_levels[:5]
        )

        # 计算卖盘前5档总量
        ask_vol = sum(
            level.volume
            for level in orderbook.ask_levels[:5]
        )

        # 计算 OFI
        total_vol = bid_vol + ask_vol
        if total_vol < 1e-9:  # 避免除零
            ofi = 0.0
        else:
            ofi = (bid_vol - ask_vol) / total_vol

        # 更新历史记录
        self._current_ofi = ofi
        self._history.append((datetime.now(), ofi))

        return ofi

    def get_current_ofi(self) -> Optional[float]:
        """获取当前 OFI 值"""
        return self._current_ofi

    def is_strong_buy_pressure(self, threshold: float = 0.3, periods: int = 3) -> bool:
        """
        判断是否存在强买方压力

        Args:
            threshold: OFI 阈值（默认 0.3）
            periods: 持续周期数（默认 3）

        Returns:
            True 如果最近 N 个周期 OFI 都大于阈值
        """
        if len(self._history) < periods:
            return False

        recent_ofi = [ofi for _, ofi in list(self._history)[-periods:]]
        return all(ofi > threshold for ofi in recent_ofi)

    def is_strong_sell_pressure(self, threshold: float = -0.3, periods: int = 3) -> bool:
        """
        判断是否存在强卖方压力

        Args:
            threshold: OFI 阈值（默认 -0.3）
            periods: 持续周期数（默认 3）

        Returns:
            True 如果最近 N 个周期 OFI 都小于阈值
        """
        if len(self._history) < periods:
            return False

        recent_ofi = [ofi for _, ofi in list(self._history)[-periods:]]
        return all(ofi < threshold for ofi in recent_ofi)

    def get_ofi_score(self, ofi_threshold: float = 0.3) -> int:
        """
        计算 OFI 评分（用于信号评分系统）

        Args:
            ofi_threshold: OFI 阈值

        Returns:
            评分 0-2 分：
            - 2 分：强买方压力（连续 3 个周期 OFI > threshold）
            - 1 分：中等买方压力（当前 OFI > threshold）
            - 0 分：无明显买方压力或卖方压力
        """
        if self.is_strong_buy_pressure(ofi_threshold, periods=3):
            return 2
        elif self._current_ofi is not None and self._current_ofi > ofi_threshold:
            return 1
        else:
            return 0

    def get_history(self) -> list[tuple[datetime, float]]:
        """获取历史 OFI 值"""
        return list(self._history)

    def reset(self):
        """重置计算器"""
        self._history.clear()
        self._current_ofi = None
