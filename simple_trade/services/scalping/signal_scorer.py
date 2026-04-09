"""
信号评分系统（Signal Scorer）

多维度评分系统，替代当前的二元信号（有/无），提供 0-10 分的信号质量评分。

评分维度：
1. Delta 强度（0-3分）：累计净动量 / 平均成交量
2. OFI 持续性（0-2分）：订单流不平衡度，连续 3 个周期 OFI > 0.3
3. 成交加速度（0-2分）：成交速度的加速度 > 阈值
4. VWAP 偏离度（0-2分）：价格在合理区间（-1% ~ +1%）
5. POC 距离（0-1分）：价格接近 POC（高流动性区域）

评分规则：
- 总分 >= 7 分 → 高质量信号（⭐⭐⭐）
- 总分 5-6 分 → 中等信号（⭐⭐）
- 总分 < 5 分 → 过滤掉
"""
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("scalping")


@dataclass
class SignalScoreComponents:
    """信号评分组成部分"""
    delta_score: int  # 0-3 分
    ofi_score: int  # 0-2 分
    acceleration_score: int  # 0-2 分
    vwap_deviation_score: int  # 0-2 分
    poc_distance_score: int  # 0-1 分
    total_score: int  # 总分 0-10 分

    def get_quality_level(self) -> str:
        """获取信号质量等级"""
        if self.total_score >= 7:
            return "high"  # 高质量 ⭐⭐⭐
        elif self.total_score >= 5:
            return "medium"  # 中等 ⭐⭐
        else:
            return "low"  # 低质量（应过滤）


class SignalScorer:
    """
    信号评分器

    综合多个维度对交易信号进行评分，帮助过滤低质量信号。
    """

    def __init__(
        self,
        delta_threshold_multiplier: float = 2.0,
        ofi_threshold: float = 0.3,
        acceleration_threshold: float = 0.0,
        vwap_deviation_fair_range: tuple[float, float] = (-1.0, 1.0),
        poc_distance_max_ticks: int = 3,
        tick_size: float = 0.01,
    ):
        """
        初始化信号评分器

        Args:
            delta_threshold_multiplier: Delta 阈值倍数（默认 2.0，即平均成交量的 2 倍）
            ofi_threshold: OFI 阈值（默认 0.3）
            acceleration_threshold: 加速度阈值（默认 0.0）
            vwap_deviation_fair_range: VWAP 偏离度合理区间（默认 -1% ~ +1%）
            poc_distance_max_ticks: POC 距离最大 Tick 数（默认 3）
            tick_size: 最小价格变动单位（默认 0.01）
        """
        self.delta_threshold_multiplier = delta_threshold_multiplier
        self.ofi_threshold = ofi_threshold
        self.acceleration_threshold = acceleration_threshold
        self.vwap_deviation_fair_range = vwap_deviation_fair_range
        self.poc_distance_max_ticks = poc_distance_max_ticks
        self.tick_size = tick_size

    def score_delta_strength(
        self,
        current_delta: float,
        avg_delta: float,
    ) -> int:
        """
        评估 Delta 强度（0-3 分）

        Args:
            current_delta: 当前 Delta 值
            avg_delta: 平均 Delta 值

        Returns:
            0-3 分：
            - 3 分：Delta > 平均值 × 3
            - 2 分：Delta > 平均值 × 2
            - 1 分：Delta > 平均值
            - 0 分：Delta <= 平均值
        """
        if avg_delta <= 0:
            return 0

        ratio = current_delta / avg_delta

        if ratio >= 3.0:
            return 3
        elif ratio >= self.delta_threshold_multiplier:
            return 2
        elif ratio >= 1.0:
            return 1
        else:
            return 0

    def score_ofi_persistence(self, ofi_score: int) -> int:
        """
        评估 OFI 持续性（0-2 分）

        Args:
            ofi_score: OFI 计算器返回的评分（0-2）

        Returns:
            0-2 分（直接使用 OFI 计算器的评分）
        """
        return ofi_score

    def score_acceleration(self, acceleration: Optional[float]) -> int:
        """
        评估成交加速度（0-2 分）

        Args:
            acceleration: 成交速度加速度

        Returns:
            0-2 分：
            - 2 分：加速度 > 阈值 × 2
            - 1 分：加速度 > 阈值
            - 0 分：加速度 <= 阈值
        """
        if acceleration is None:
            return 0

        if acceleration > self.acceleration_threshold * 2:
            return 2
        elif acceleration > self.acceleration_threshold:
            return 1
        else:
            return 0

    def score_vwap_deviation(self, vwap_deviation_level: str) -> int:
        """
        评估 VWAP 偏离度（0-2 分）

        Args:
            vwap_deviation_level: VWAP 偏离度等级（"fair", "oversold", "overbought", "neutral"）

        Returns:
            0-2 分：
            - 2 分：价格在合理区间（fair）
            - 1 分：价格超跌（oversold，适合支撑低吸）
            - 0 分：价格超涨（overbought）或中性（neutral）
        """
        if vwap_deviation_level == "fair":
            return 2
        elif vwap_deviation_level == "oversold":
            return 1
        else:
            return 0

    def score_poc_distance(
        self,
        current_price: float,
        poc_price: Optional[float],
    ) -> int:
        """
        评估 POC 距离（0-1 分）

        Args:
            current_price: 当前价格
            poc_price: POC 价格

        Returns:
            0-1 分：
            - 1 分：价格距 POC < poc_distance_max_ticks 个 Tick
            - 0 分：价格距 POC >= poc_distance_max_ticks 个 Tick 或 POC 不存在
        """
        if poc_price is None:
            return 0

        dist_ticks = abs(current_price - poc_price) / self.tick_size

        if dist_ticks < self.poc_distance_max_ticks:
            return 1
        else:
            return 0

    def calculate_total_score(
        self,
        current_delta: float,
        avg_delta: float,
        ofi_score: int,
        acceleration: Optional[float],
        vwap_deviation_level: str,
        current_price: float,
        poc_price: Optional[float],
    ) -> SignalScoreComponents:
        """
        计算信号总分

        Args:
            current_delta: 当前 Delta 值
            avg_delta: 平均 Delta 值
            ofi_score: OFI 计算器返回的评分
            acceleration: 成交速度加速度
            vwap_deviation_level: VWAP 偏离度等级
            current_price: 当前价格
            poc_price: POC 价格

        Returns:
            SignalScoreComponents 对象，包含各维度评分和总分
        """
        delta_score = self.score_delta_strength(current_delta, avg_delta)
        ofi_score_val = self.score_ofi_persistence(ofi_score)
        acceleration_score = self.score_acceleration(acceleration)
        vwap_score = self.score_vwap_deviation(vwap_deviation_level)
        poc_score = self.score_poc_distance(current_price, poc_price)

        total = delta_score + ofi_score_val + acceleration_score + vwap_score + poc_score

        return SignalScoreComponents(
            delta_score=delta_score,
            ofi_score=ofi_score_val,
            acceleration_score=acceleration_score,
            vwap_deviation_score=vwap_score,
            poc_distance_score=poc_score,
            total_score=total,
        )

    def should_filter_signal(self, total_score: int, min_score: int = 5) -> bool:
        """
        判断是否应该过滤信号

        Args:
            total_score: 信号总分
            min_score: 最低评分阈值（默认 5 分）

        Returns:
            True 表示应该过滤（信号质量不足）
        """
        return total_score < min_score