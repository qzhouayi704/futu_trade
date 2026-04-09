#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
信号评分器

对交易信号进行综合评分，筛选出最强的信号。
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import datetime, date


@dataclass
class SignalScore:
    """信号评分结果"""
    stock_code: str
    stock_name: str
    plate_code: str
    plate_name: str

    # 各项评分 (0-100)
    plate_score: float = 0.0         # 板块强势度评分
    stock_score: float = 0.0         # 个股条件评分
    timing_score: float = 0.0        # 时机评分

    # 综合评分
    total_score: float = 0.0         # 总评分 (0-100)
    normalized_score: float = 0.0    # 归一化评分 (0-1)

    # 信号类型
    signal_type: str = "BUY"         # BUY/SELL
    reason: str = ""                 # 信号原因

    # 排名
    rank: int = 0                    # 信号排名

    # 原始数据
    raw_data: Dict[str, Any] = field(default_factory=dict)

    # 时间戳
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'plate_code': self.plate_code,
            'plate_name': self.plate_name,
            'plate_score': round(self.plate_score, 2),
            'stock_score': round(self.stock_score, 2),
            'timing_score': round(self.timing_score, 2),
            'total_score': round(self.total_score, 2),
            'normalized_score': round(self.normalized_score, 3),
            'signal_type': self.signal_type,
            'reason': self.reason,
            'rank': self.rank,
            'timestamp': self.timestamp
        }


class SignalScorer:
    """
    信号评分器

    对交易信号进行综合评分，确保每天只输出最强的信号。

    评分维度：
    1. 板块强势度 (40%)
    2. 个股条件 (40%)
    3. 时机评分 (20%)
    """

    # 评分权重
    PLATE_WEIGHT = 0.40
    STOCK_WEIGHT = 0.40
    TIMING_WEIGHT = 0.20

    # 信号控制
    DEFAULT_MAX_DAILY_SIGNALS = 2
    DEFAULT_MIN_SCORE = 70.0

    def __init__(
        self,
        max_daily_signals: int = None,
        min_score: float = None
    ):
        """
        初始化信号评分器

        Args:
            max_daily_signals: 每日最大信号数
            min_score: 最低信号分数
        """
        self.max_daily_signals = max_daily_signals or self.DEFAULT_MAX_DAILY_SIGNALS
        self.min_score = min_score or self.DEFAULT_MIN_SCORE
        self.logger = logging.getLogger(__name__)

        # 每日信号计数
        self._daily_signals: Dict[str, List[SignalScore]] = {}
        self._current_date: Optional[date] = None

    def score_signal(
        self,
        stock_code: str,
        stock_name: str,
        plate_code: str,
        plate_name: str,
        plate_strength: float,
        plate_rank: int,
        change_pct: float,
        volume: int,
        price_position: float,
        signal_type: str = "BUY",
        reason: str = ""
    ) -> SignalScore:
        """
        计算单个信号的评分

        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            plate_code: 板块代码
            plate_name: 板块名称
            plate_strength: 板块强势度 (0-100)
            plate_rank: 板块排名
            change_pct: 涨跌幅 (%)
            volume: 成交量
            price_position: 价格位置 (0-100)
            signal_type: 信号类型
            reason: 信号原因

        Returns:
            SignalScore: 信号评分结果
        """
        # 计算各项评分
        plate_score = self._calculate_plate_score(plate_strength, plate_rank)
        stock_score = self._calculate_stock_score(change_pct, volume, price_position)
        timing_score = self._calculate_timing_score()

        # 计算总分
        total_score = (
            plate_score * self.PLATE_WEIGHT +
            stock_score * self.STOCK_WEIGHT +
            timing_score * self.TIMING_WEIGHT
        )

        return SignalScore(
            stock_code=stock_code,
            stock_name=stock_name,
            plate_code=plate_code,
            plate_name=plate_name,
            plate_score=plate_score,
            stock_score=stock_score,
            timing_score=timing_score,
            total_score=total_score,
            normalized_score=total_score / 100.0,
            signal_type=signal_type,
            reason=reason,
            raw_data={
                'plate_strength': plate_strength,
                'plate_rank': plate_rank,
                'change_pct': change_pct,
                'volume': volume,
                'price_position': price_position
            }
        )

    def _calculate_plate_score(self, strength: float, rank: int) -> float:
        """
        计算板块评分

        Args:
            strength: 板块强势度 (0-100)
            rank: 板块排名

        Returns:
            板块评分 (0-100)
        """
        # 强势度评分 (0-70分)
        strength_score = min(strength, 100) * 0.7

        # 排名评分 (0-30分)
        # 第1名30分，第2名25分，第3名20分，以此类推
        if rank <= 3:
            rank_score = 35 - rank * 5
        elif rank <= 5:
            rank_score = 20 - (rank - 3) * 5
        else:
            rank_score = max(0, 10 - (rank - 5) * 2)

        return strength_score + rank_score

    def _calculate_stock_score(
        self,
        change_pct: float,
        volume: int,
        price_position: float
    ) -> float:
        """
        计算个股评分

        Args:
            change_pct: 涨跌幅 (%)
            volume: 成交量
            price_position: 价格位置 (0-100)

        Returns:
            个股评分 (0-100)
        """
        # 涨幅评分 (0-40分)
        # 最佳区间 3%-4%
        if 3.0 <= change_pct <= 4.0:
            change_score = 40
        elif 2.5 <= change_pct < 3.0:
            change_score = 35
        elif 4.0 < change_pct <= 5.0:
            change_score = 30
        elif 2.0 <= change_pct < 2.5:
            change_score = 25
        else:
            change_score = max(0, 20 - abs(change_pct - 3.5) * 5)

        # 成交量评分 (0-30分)
        # 500万股及以上满分
        volume_ratio = min(volume / 5000000, 1.0)
        volume_score = volume_ratio * 30

        # 价格位置评分 (0-30分)
        # 0-20%位置满分，20-40%位置递减
        if price_position <= 20:
            position_score = 30
        elif price_position <= 40:
            position_score = 30 - (price_position - 20) * 0.75
        else:
            position_score = max(0, 15 - (price_position - 40) * 0.375)

        return change_score + volume_score + position_score

    def _calculate_timing_score(self) -> float:
        """
        计算时机评分

        基于当前时间评估交易时机。

        Returns:
            时机评分 (0-100)
        """
        now = datetime.now()
        hour = now.hour
        minute = now.minute

        # 港股交易时间: 9:30-12:00, 13:00-16:00
        # 美股交易时间: 21:30-04:00 (北京时间)

        # 早盘开盘后30分钟内 (9:30-10:00) - 最佳时机
        if 9 <= hour < 10:
            return 100

        # 早盘中段 (10:00-11:30) - 良好时机
        if 10 <= hour < 12:
            return 85

        # 午盘 (13:00-14:30) - 一般时机
        if 13 <= hour < 15:
            return 75

        # 尾盘 (14:30-16:00) - 隔日买入时机
        if 14 <= hour < 16:
            return 70

        # 非交易时间
        return 50

    def filter_best_signals(
        self,
        signals: List[SignalScore],
        max_signals: int = None,
        min_score: float = None
    ) -> List[SignalScore]:
        """
        筛选最佳信号

        Args:
            signals: 信号列表
            max_signals: 最大信号数
            min_score: 最低分数

        Returns:
            筛选后的信号列表
        """
        if max_signals is None:
            max_signals = self.max_daily_signals
        if min_score is None:
            min_score = self.min_score

        # 按总分排序
        sorted_signals = sorted(signals, key=lambda x: x.total_score, reverse=True)

        # 筛选符合条件的信号
        qualified = [s for s in sorted_signals if s.total_score >= min_score]

        # 设置排名
        for i, signal in enumerate(qualified):
            signal.rank = i + 1

        # 取前N个
        result = qualified[:max_signals]

        self.logger.info(
            f"信号筛选: 共{len(signals)}个信号, "
            f"符合条件{len(qualified)}个, 输出{len(result)}个"
        )

        return result

    def check_daily_limit(self, signal: SignalScore) -> bool:
        """
        检查是否达到每日信号上限

        Args:
            signal: 待添加的信号

        Returns:
            是否可以添加（未达上限）
        """
        today = date.today()

        # 日期变化时重置计数
        if self._current_date != today:
            self._daily_signals.clear()
            self._current_date = today

        today_str = today.isoformat()
        if today_str not in self._daily_signals:
            self._daily_signals[today_str] = []

        current_count = len(self._daily_signals[today_str])
        return current_count < self.max_daily_signals

    def add_daily_signal(self, signal: SignalScore) -> bool:
        """
        添加每日信号

        Args:
            signal: 信号

        Returns:
            是否添加成功
        """
        if not self.check_daily_limit(signal):
            self.logger.warning(
                f"已达每日信号上限 ({self.max_daily_signals}), "
                f"跳过信号: {signal.stock_code}"
            )
            return False

        today_str = date.today().isoformat()
        self._daily_signals[today_str].append(signal)

        self.logger.info(
            f"添加信号: {signal.stock_code} ({signal.stock_name}), "
            f"评分: {signal.total_score:.1f}, "
            f"今日第{len(self._daily_signals[today_str])}个"
        )

        return True

    def get_today_signals(self) -> List[SignalScore]:
        """获取今日已发出的信号"""
        today_str = date.today().isoformat()
        return self._daily_signals.get(today_str, [])

    def get_remaining_slots(self) -> int:
        """获取今日剩余信号槽位"""
        today_signals = self.get_today_signals()
        return max(0, self.max_daily_signals - len(today_signals))

    def reset_daily_count(self):
        """重置每日计数"""
        self._daily_signals.clear()
        self._current_date = None

    def update_config(self, max_daily_signals: int = None, min_score: float = None):
        """
        更新配置

        Args:
            max_daily_signals: 每日最大信号数
            min_score: 最低信号分数
        """
        if max_daily_signals is not None:
            self.max_daily_signals = max_daily_signals
        if min_score is not None:
            self.min_score = min_score
