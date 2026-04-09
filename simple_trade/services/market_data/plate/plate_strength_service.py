#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
板块强势度服务

计算和评估板块的实时强势度，用于激进交易策略筛选。
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import datetime


@dataclass
class PlateStrengthScore:
    """板块强势度评分结果"""
    plate_code: str
    plate_name: str
    market: str

    # 核心指标
    up_stock_ratio: float = 0.0      # 上涨股票占比 (0-1)
    avg_change_pct: float = 0.0      # 板块平均涨跌幅 (%)
    leader_count: int = 0            # 龙头股数量（涨幅>5%）
    total_stocks: int = 0            # 板块总股票数

    # 综合评分
    strength_score: float = 0.0      # 强势度评分 (0-100)
    rank: int = 0                    # 强势度排名

    # 趋势判断
    is_leading: bool = False         # 是否为领涨板块
    momentum: str = "STABLE"         # 动量状态: ACCELERATING/STABLE/DECELERATING

    # 时间戳
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'plate_code': self.plate_code,
            'plate_name': self.plate_name,
            'market': self.market,
            'up_stock_ratio': round(self.up_stock_ratio, 4),
            'avg_change_pct': round(self.avg_change_pct, 2),
            'leader_count': self.leader_count,
            'total_stocks': self.total_stocks,
            'strength_score': round(self.strength_score, 2),
            'rank': self.rank,
            'is_leading': self.is_leading,
            'momentum': self.momentum,
            'timestamp': self.timestamp
        }


class PlateStrengthService:
    """
    板块强势度服务

    计算板块强势度评分，用于筛选最强势的板块。

    强势度计算公式：
    - 上涨占比权重: 40%
    - 平均涨幅权重: 35%
    - 龙头股数量权重: 25%
    """

    # 权重配置
    UP_RATIO_WEIGHT = 0.40
    AVG_CHANGE_WEIGHT = 0.35
    LEADER_COUNT_WEIGHT = 0.25

    # 满分阈值
    UP_RATIO_FULL_SCORE = 0.70       # 70%以上股票上涨得满分
    AVG_CHANGE_FULL_SCORE = 3.0      # 平均涨幅3%以上得满分
    LEADER_COUNT_FULL_SCORE = 5      # 5只以上龙头股得满分

    # 龙头股定义
    LEADER_MIN_CHANGE_PCT = 5.0      # 涨幅>=5%算龙头股

    def __init__(self, realtime_service=None, plate_manager=None):
        """
        初始化板块强势度服务

        Args:
            realtime_service: 实时行情服务
            plate_manager: 板块管理服务
        """
        self.realtime_service = realtime_service
        self.plate_manager = plate_manager
        self.logger = logging.getLogger(__name__)

        # 缓存
        self._strength_cache: Dict[str, PlateStrengthScore] = {}
        self._last_update_time: Optional[datetime] = None

    def calculate_plate_strength(
        self,
        plate_code: str,
        plate_name: str,
        market: str,
        quotes: Dict[str, Dict[str, Any]]
    ) -> PlateStrengthScore:
        """
        计算单个板块的强势度

        Args:
            plate_code: 板块代码
            plate_name: 板块名称
            market: 市场代码
            quotes: 板块内股票的实时报价 {stock_code: quote_data}

        Returns:
            PlateStrengthScore: 板块强势度评分
        """
        result = PlateStrengthScore(
            plate_code=plate_code,
            plate_name=plate_name,
            market=market
        )

        if not quotes:
            return result

        # 统计指标
        up_count = 0
        total_change = 0.0
        leader_count = 0
        valid_count = 0

        for stock_code, quote in quotes.items():
            # 防御性检查：确保 quote 是字典类型
            if not isinstance(quote, dict):
                self.logger.warning(f"跳过无效的报价数据: {stock_code}, 类型={type(quote)}")
                continue

            change_pct = quote.get('change_percent', 0) or 0

            # 跳过无效数据
            if change_pct is None:
                continue

            valid_count += 1
            total_change += change_pct

            # 统计上涨股票
            if change_pct > 0:
                up_count += 1

            # 统计龙头股（涨幅>=5%）
            if change_pct >= self.LEADER_MIN_CHANGE_PCT:
                leader_count += 1

        if valid_count == 0:
            return result

        # 计算指标
        result.total_stocks = valid_count
        result.up_stock_ratio = up_count / valid_count
        result.avg_change_pct = total_change / valid_count
        result.leader_count = leader_count

        # 计算强势度评分
        result.strength_score = self._calculate_strength_score(
            up_ratio=result.up_stock_ratio,
            avg_change=result.avg_change_pct,
            leader_count=result.leader_count
        )

        return result

    def _calculate_strength_score(
        self,
        up_ratio: float,
        avg_change: float,
        leader_count: int
    ) -> float:
        """
        计算强势度评分

        公式：
        强势度 = 上涨占比评分×40% + 平均涨幅评分×35% + 龙头股评分×25%

        Args:
            up_ratio: 上涨股票占比 (0-1)
            avg_change: 平均涨跌幅 (%)
            leader_count: 龙头股数量

        Returns:
            强势度评分 (0-100)
        """
        # 上涨占比评分 (0-40分)
        up_score = min(up_ratio / self.UP_RATIO_FULL_SCORE, 1.0) * 100 * self.UP_RATIO_WEIGHT

        # 平均涨幅评分 (0-35分)
        # 负涨幅得0分，正涨幅按比例得分
        if avg_change <= 0:
            change_score = 0
        else:
            change_score = min(avg_change / self.AVG_CHANGE_FULL_SCORE, 1.0) * 100 * self.AVG_CHANGE_WEIGHT

        # 龙头股评分 (0-25分)
        leader_score = min(leader_count / self.LEADER_COUNT_FULL_SCORE, 1.0) * 100 * self.LEADER_COUNT_WEIGHT

        return up_score + change_score + leader_score

    def calculate_all_plates_strength(
        self,
        plates: List[Dict[str, Any]],
        all_quotes: Dict[str, Dict[str, Any]]
    ) -> List[PlateStrengthScore]:
        """
        计算所有板块的强势度并排名

        Args:
            plates: 板块列表 [{plate_code, plate_name, market, stocks: [stock_codes]}]
            all_quotes: 所有股票的实时报价

        Returns:
            按强势度排序的板块列表
        """
        results = []

        for plate in plates:
            plate_code = plate.get('plate_code') or plate.get('code', '')
            plate_name = plate.get('plate_name') or plate.get('name', '')
            market = plate.get('market', '')
            stock_codes = plate.get('stocks', [])

            # 提取该板块的股票报价
            plate_quotes = {
                code: all_quotes[code]
                for code in stock_codes
                if code in all_quotes
            }

            # 计算强势度
            strength = self.calculate_plate_strength(
                plate_code=plate_code,
                plate_name=plate_name,
                market=market,
                quotes=plate_quotes
            )

            results.append(strength)

        # 按强势度排序
        results.sort(key=lambda x: x.strength_score, reverse=True)

        # 设置排名和领涨标志
        for i, result in enumerate(results):
            result.rank = i + 1
            result.is_leading = (i < 3)  # 前3名为领涨板块

        # 更新缓存
        self._strength_cache = {r.plate_code: r for r in results}
        self._last_update_time = datetime.now()

        return results

    def get_top_plates(
        self,
        plates: List[Dict[str, Any]],
        all_quotes: Dict[str, Dict[str, Any]],
        top_n: int = 3,
        min_score: float = 70.0
    ) -> List[PlateStrengthScore]:
        """
        获取强势板块

        Args:
            plates: 板块列表
            all_quotes: 所有股票报价
            top_n: 返回前N名
            min_score: 最低强势度分数

        Returns:
            强势板块列表
        """
        all_strengths = self.calculate_all_plates_strength(plates, all_quotes)

        # 筛选符合条件的板块
        qualified = [
            s for s in all_strengths
            if s.strength_score >= min_score and s.rank <= top_n
        ]

        self.logger.info(
            f"强势板块筛选: 共{len(all_strengths)}个板块, "
            f"符合条件{len(qualified)}个 (top{top_n}, score>={min_score})"
        )

        return qualified

    def get_plate_strength(self, plate_code: str) -> Optional[PlateStrengthScore]:
        """
        获取单个板块的强势度（从缓存）

        Args:
            plate_code: 板块代码

        Returns:
            板块强势度，如果不存在返回None
        """
        return self._strength_cache.get(plate_code)

    def is_plate_strong(
        self,
        plate_code: str,
        min_score: float = 70.0,
        max_rank: int = 5
    ) -> bool:
        """
        判断板块是否强势

        Args:
            plate_code: 板块代码
            min_score: 最低强势度分数
            max_rank: 最大排名

        Returns:
            是否强势
        """
        strength = self._strength_cache.get(plate_code)
        if not strength:
            return False

        return strength.strength_score >= min_score and strength.rank <= max_rank

    def get_all_strengths(self) -> List[PlateStrengthScore]:
        """获取所有板块强势度（从缓存）"""
        strengths = list(self._strength_cache.values())
        strengths.sort(key=lambda x: x.rank)
        return strengths

    def clear_cache(self):
        """清空缓存"""
        self._strength_cache.clear()
        self._last_update_time = None
