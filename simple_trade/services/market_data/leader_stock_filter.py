#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
龙头股筛选服务 - 热度+涨幅综合型

从强势板块中筛选热门龙头股。
筛选模型：综合热度评分 = 涨幅得分×40% + 成交活跃度×30% + 换手率得分×30%
典型案例参考：HK.02513(智谱)、HK.00100(MINIMAX-WP) 等 AI 龙头股。
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import datetime


@dataclass
class LeaderStockCandidate:
    """龙头股候选"""
    stock_code: str
    stock_name: str
    market: str
    plate_code: str
    plate_name: str

    # 实时数据
    last_price: float = 0.0
    change_pct: float = 0.0          # 涨跌幅 (%)
    volume: int = 0                  # 成交量
    turnover: float = 0.0            # 成交额
    turnover_rate: float = 0.0       # 换手率 (%)

    # 评分
    heat_score: float = 0.0          # 综合热度分 (0-100)
    composite_score: float = 0.0     # 综合排名分 (0-1)

    # 龙头判断
    is_leader: bool = False
    leader_rank: int = 0             # 1=龙一, 2=龙二, 3=龙三

    # 信号强度
    signal_strength: float = 0.0     # 信号强度 (0-1)

    # 时间戳
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'market': self.market,
            'plate_code': self.plate_code,
            'plate_name': self.plate_name,
            'last_price': round(self.last_price, 3),
            'change_pct': round(self.change_pct, 2),
            'volume': self.volume,
            'turnover': round(self.turnover, 2),
            'turnover_rate': round(self.turnover_rate, 2),
            'heat_score': round(self.heat_score, 2),
            'composite_score': round(self.composite_score, 3),
            'is_leader': self.is_leader,
            'leader_rank': self.leader_rank,
            'signal_strength': round(self.signal_strength, 3),
            'timestamp': self.timestamp
        }


@dataclass
class LeaderFilterConfig:
    """
    龙头股筛选配置 - 热度+涨幅综合型

    设计理念：龙头股通常处于高位强势状态，不应限制价格位置上限。
    筛选门槛尽量宽松，依靠综合评分排序来选出真正的龙头。
    """
    # 涨幅筛选
    min_change_pct: float = 3.0       # 最低涨幅 (%)，过滤弱势股
    max_change_pct: float = 50.0      # 最高涨幅 (%)，防止异常数据

    # 成交量筛选（港股成交量比美股小）
    min_volume: int = 1000000         # 最低成交量 100万股

    # 换手率筛选
    min_turnover_rate: float = 0.8    # 最低换手率 (%)

    # 龙头股数量
    max_leaders_per_plate: int = 3

    # 信号筛选
    min_signal_strength: float = 0.3

    # 综合评分权重
    weight_change_pct: float = 0.40   # 涨幅权重
    weight_volume: float = 0.30       # 成交活跃度权重
    weight_turnover_rate: float = 0.30  # 换手率权重

    # 归一化参数
    change_pct_cap: float = 20.0      # 涨幅归一化上限 (%)
    volume_cap: float = 10000000      # 成交量归一化上限 (1000万股)
    turnover_rate_cap: float = 5.0    # 换手率归一化上限 (%)


class LeaderStockFilter:
    """
    龙头股筛选服务 - 热度+涨幅综合型

    筛选逻辑：
    1. 基本门槛：涨幅>=1%、成交量>=50万股（宽松过滤）
    2. 综合评分：涨幅×40% + 成交活跃度×30% + 换手率×30%
    3. 按综合分排序，每板块取前N只作为龙头
    """

    def __init__(self, kline_service=None, config: LeaderFilterConfig = None,
                 capital_analyzer=None, big_order_tracker=None, enhanced_calculator=None):
        self.kline_service = kline_service
        self.config = config or LeaderFilterConfig()
        self.logger = logging.getLogger(__name__)

        # 增强模式组件
        self.capital_analyzer = capital_analyzer
        self.big_order_tracker = big_order_tracker
        self.enhanced_calculator = enhanced_calculator
        self.enhanced_enabled = all([capital_analyzer, big_order_tracker, enhanced_calculator])

    def filter_leader_stocks(
        self,
        plate_code: str,
        plate_name: str,
        stocks: List[Dict[str, Any]],
        quotes: Dict[str, Dict[str, Any]],
        kline_data: Dict[str, List[Dict]] = None
    ) -> List[LeaderStockCandidate]:
        """
        从板块中筛选龙头股

        Returns:
            龙头股候选列表（按综合分排序）
        """
        candidates = []

        for stock in stocks:
            stock_code = stock.get('code', '')
            stock_name = stock.get('name', '')
            market = stock.get('market', '')

            quote = quotes.get(stock_code, {})
            if not quote:
                continue

            last_price = quote.get('last_price', 0) or 0
            change_pct = quote.get('change_percent', 0) or 0
            volume = quote.get('volume', 0) or 0
            turnover = quote.get('turnover', 0) or 0
            turnover_rate = quote.get('turnover_rate', 0) or 0

            # 基本门槛筛选
            if not self._check_filter_conditions(change_pct, volume, turnover_rate, stock_code):
                continue

            # 增强模式：资金流向和大单确认
            if self.enhanced_enabled:
                if not self._check_enhanced_conditions(stock_code, quote, kline_data):
                    continue

            # 计算综合评分
            composite_score = self._calculate_composite_score(
                change_pct, volume, turnover_rate
            )

            candidate = LeaderStockCandidate(
                stock_code=stock_code,
                stock_name=stock_name,
                market=market,
                plate_code=plate_code,
                plate_name=plate_name,
                last_price=last_price,
                change_pct=change_pct,
                volume=volume,
                turnover=turnover,
                turnover_rate=turnover_rate,
                composite_score=composite_score,
                heat_score=composite_score * 100,
                signal_strength=composite_score
            )
            candidates.append(candidate)

        # 按综合分排序
        candidates.sort(key=lambda x: x.composite_score, reverse=True)

        # 标记龙头排名
        for i, c in enumerate(candidates[:self.config.max_leaders_per_plate]):
            c.is_leader = True
            c.leader_rank = i + 1

        self.logger.debug(
            f"板块 {plate_name}: {len(candidates)} 只候选, "
            f"龙头 {min(len(candidates), self.config.max_leaders_per_plate)} 只"
        )
        return candidates

    def _check_filter_conditions(
        self, change_pct: float, volume: int, turnover_rate: float,
        stock_code: str = ''
    ) -> bool:
        """
        基本门槛筛选

        条件：涨幅>=3%、成交量>=100万股、换手率>=0.8%、涨幅不超上限。
        不限制价格位置（龙头股通常在高位）。
        """
        if change_pct < self.config.min_change_pct:
            return False
        if change_pct > self.config.max_change_pct:
            self.logger.debug(f"{stock_code} 涨幅异常 {change_pct:.2f}%")
            return False
        if volume < self.config.min_volume:
            self.logger.debug(f"{stock_code} 成交量不足 {volume}")
            return False
        if turnover_rate < self.config.min_turnover_rate:
            self.logger.debug(f"{stock_code} 换手率不足 {turnover_rate:.2f}%")
            return False
        return True

    def _check_enhanced_conditions(
        self, stock_code: str, quote: Dict, kline_data: Dict = None
    ) -> bool:
        """增强模式：资金流向和大单确认"""
        # 检查资金流向
        capital_data = self._get_capital_data(stock_code)
        if capital_data:
            net_inflow_ratio = capital_data.get('net_inflow_ratio', 0)
            if net_inflow_ratio < 0.1:
                self.logger.debug(f"{stock_code} 资金流向不足")
                return False

        # 检查大单强度
        big_order_data = self._get_big_order_data(stock_code)
        if big_order_data:
            buy_sell_ratio = big_order_data.get('buy_sell_ratio', 0)
            if buy_sell_ratio < 1.0:
                self.logger.debug(f"{stock_code} 大单卖出为主")
                return False

        # 检查追高风险
        if self.enhanced_calculator:
            klines = kline_data.get(stock_code) if kline_data else None
            is_risky, reason = self.enhanced_calculator.check_chase_high_risk(
                stock_code, quote, klines
            )
            if is_risky:
                self.logger.debug(f"{stock_code} 追高风险: {reason}")
                return False

        return True

    def _calculate_composite_score(
        self, change_pct: float, volume: int, turnover_rate: float
    ) -> float:
        """
        计算综合评分（热度+涨幅综合型）

        公式：涨幅得分×40% + 成交活跃度×30% + 换手率得分×30%
        所有维度归一化到 0-1 后加权求和。
        """
        cfg = self.config

        # 涨幅得分：线性归一化，cap 以内线性映射
        change_score = min(max(change_pct, 0) / cfg.change_pct_cap, 1.0)

        # 成交量得分：线性归一化
        volume_score = min(volume / cfg.volume_cap, 1.0)

        # 换手率得分：线性归一化
        tr_score = min(max(turnover_rate, 0) / cfg.turnover_rate_cap, 1.0)

        composite = (
            change_score * cfg.weight_change_pct +
            volume_score * cfg.weight_volume +
            tr_score * cfg.weight_turnover_rate
        )
        return round(composite, 4)

    def _get_capital_data(self, stock_code: str) -> Optional[Dict]:
        """获取资金流向数据"""
        if not self.capital_analyzer:
            return None
        try:
            data = self.capital_analyzer.fetch_capital_flow_data([stock_code])
            return data.get(stock_code)
        except Exception as e:
            self.logger.error(f"获取资金流向失败: {stock_code}, {e}")
            return None

    def _get_big_order_data(self, stock_code: str) -> Optional[Dict]:
        """获取大单追踪数据"""
        if not self.big_order_tracker:
            return None
        try:
            data = self.big_order_tracker.track_rt_tickers([stock_code], top_n=1)
            return data.get(stock_code)
        except Exception as e:
            self.logger.error(f"获取大单数据失败: {stock_code}, {e}")
            return None

    def get_all_leaders(
        self,
        plates_data: List[Dict[str, Any]],
        all_quotes: Dict[str, Dict[str, Any]],
        all_kline_data: Dict[str, List[Dict]] = None,
        max_total: int = 10
    ) -> List[LeaderStockCandidate]:
        """
        从多个板块中获取所有龙头股（按综合分排序）
        """
        all_leaders = []
        total_stocks = 0
        total_with_quotes = 0

        for plate in plates_data:
            plate_code = plate.get('plate_code') or plate.get('code', '')
            plate_name = plate.get('plate_name') or plate.get('name', '')
            stocks = plate.get('stocks', [])
            total_stocks += len(stocks)

            for s in stocks:
                if s.get('code', '') in all_quotes:
                    total_with_quotes += 1

            leaders = self.filter_leader_stocks(
                plate_code=plate_code,
                plate_name=plate_name,
                stocks=stocks,
                quotes=all_quotes,
                kline_data=all_kline_data
            )
            plate_leaders = [l for l in leaders if l.is_leader]
            all_leaders.extend(plate_leaders)

        # 按综合分排序
        all_leaders.sort(key=lambda x: x.composite_score, reverse=True)
        result = all_leaders[:max_total]

        self.logger.info(
            f"龙头股筛选: {len(plates_data)}个板块, {total_stocks}只股票, "
            f"{total_with_quotes}只有报价, {len(all_leaders)}只龙头, "
            f"返回前{len(result)}只 "
            f"(条件: 涨幅>={self.config.min_change_pct}%, "
            f"量>={self.config.min_volume})"
        )
        return result

    def filter_by_signal_strength(
        self, candidates: List[LeaderStockCandidate],
        min_strength: float = None
    ) -> List[LeaderStockCandidate]:
        """按信号强度筛选"""
        if min_strength is None:
            min_strength = self.config.min_signal_strength
        return [c for c in candidates if c.signal_strength >= min_strength]

    def update_config(self, **kwargs):
        """更新配置"""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
                self.logger.info(f"更新配置 {key} = {value}")
