#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
激进交易策略

专注于强势板块中的热门龙头股，进行当日或隔日短线交易。
基于回测数据优化的参数配置。
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import datetime

from .base_strategy import BaseStrategy, StrategyResult, ConditionDetail, TradingConditionResult
from .strategy_registry import register_strategy


@dataclass
class AggressiveStrategyConfig:
    """激进策略配置"""

    # 板块筛选
    min_plate_strength: float = 70.0     # 最低板块强势度
    max_plate_rank: int = 3              # 最大板块排名
    min_up_ratio: float = 0.6            # 最低上涨占比

    # 股票筛选（基于回测优化）
    min_change_pct: float = 2.5          # 最低涨幅 (%)
    max_change_pct: float = 5.0          # 最高涨幅 (%)
    min_volume: int = 5000000            # 最低成交量 (股)
    min_price_position: float = 0        # 最低价格位置 (%)
    max_price_position: float = 40       # 最高价格位置 (%)

    # 止盈参数
    target_profit_pct: float = 8.0       # 目标止盈 (%)
    trailing_trigger_pct: float = 6.0    # 移动止盈触发 (%)
    trailing_callback_pct: float = 2.0   # 移动止盈回撤 (%)

    # 止损参数
    fixed_stop_loss_pct: float = -5.0    # 固定止损 (%)
    quick_stop_loss_pct: float = -3.0    # 快速止损 (%)
    plate_rank_threshold: int = 5        # 板块止损排名阈值
    max_holding_days: int = 1            # 最大持有天数

    # 信号控制
    max_daily_signals: int = 2           # 每日最大信号数
    min_signal_strength: float = 0.7     # 最低信号强度
    prefer_intraday: bool = True         # 优先当日交易


@register_strategy("aggressive", is_default=False)
class AggressiveStrategy(BaseStrategy):
    """
    激进交易策略

    专注于强势板块中的热门龙头股，进行当日或隔日短线交易。

    核心逻辑：
    1. 筛选强势板块（强势度>=70，排名前3）
    2. 从强势板块中筛选龙头股（涨幅2.5%-5%，低位0-40%）
    3. 生成买入/卖出信号
    4. 严格的止盈止损控制

    策略特点：
    - 高频短线交易
    - 精选信号（每天1-2个）
    - 严格风险控制
    """

    STRATEGY_ID = "aggressive"
    IS_DEFAULT = False

    def __init__(self, data_service=None, config: Dict[str, Any] = None):
        """
        初始化激进策略

        Args:
            data_service: 数据服务
            config: 策略配置
        """
        super().__init__(data_service, config)

        # 解析配置
        self.strategy_config = AggressiveStrategyConfig()
        if config:
            self._apply_config(config)

        self.logger = logging.getLogger(__name__)

        # 板块强势度缓存
        self._plate_strength_cache: Dict[str, Dict] = {}

    def _apply_config(self, config: Dict[str, Any]):
        """应用配置参数"""
        for key, value in config.items():
            if hasattr(self.strategy_config, key):
                setattr(self.strategy_config, key, value)

    @property
    def name(self) -> str:
        return "强势板块激进策略"

    @property
    def description(self) -> str:
        return "追踪强势板块龙头股，进行当日/隔日短线交易"

    def get_buy_conditions(self) -> List[str]:
        """获取买入条件列表"""
        return [
            f"板块强势度 >= {self.strategy_config.min_plate_strength}",
            f"板块排名 <= {self.strategy_config.max_plate_rank}",
            f"涨幅 {self.strategy_config.min_change_pct}% ~ {self.strategy_config.max_change_pct}%",
            f"成交量 >= {self.strategy_config.min_volume / 10000:.0f}万股",
            f"价格位置 {self.strategy_config.min_price_position}% ~ {self.strategy_config.max_price_position}%",
            "股票为板块涨幅前3（龙头股）"
        ]

    def get_sell_conditions(self) -> List[str]:
        """获取卖出条件列表"""
        return [
            f"目标止盈: 盈利 >= {self.strategy_config.target_profit_pct}%",
            f"移动止盈: 盈利 >= {self.strategy_config.trailing_trigger_pct}% 后回撤 {self.strategy_config.trailing_callback_pct}%",
            f"固定止损: 亏损 >= {abs(self.strategy_config.fixed_stop_loss_pct)}%",
            f"快速止损: 亏损 >= {abs(self.strategy_config.quick_stop_loss_pct)}% 且板块走弱",
            f"板块止损: 板块跌出前{self.strategy_config.plate_rank_threshold}名",
            f"时间止损: 持有超过{self.strategy_config.max_holding_days}天且盈利不足"
        ]

    def get_required_kline_days(self) -> int:
        """需要的K线天数"""
        return 30  # 需要30天数据计算价格位置

    def check_signals(
        self,
        stock_code: str,
        quote_data: Dict[str, Any],
        kline_data: List[Dict[str, Any]],
        plate_data: Optional[Dict[str, Any]] = None
    ) -> StrategyResult:
        """
        检查交易信号

        Args:
            stock_code: 股票代码
            quote_data: 实时报价
            kline_data: K线数据
            plate_data: 板块数据（包含强势度信息）

        Returns:
            StrategyResult: 策略检查结果
        """
        result = StrategyResult(stock_code=stock_code)

        # 提取报价数据
        change_pct = quote_data.get('change_percent', 0) or 0
        volume = quote_data.get('volume', 0) or 0
        last_price = quote_data.get('last_price', 0) or 0

        # 计算价格位置
        price_position = self._calculate_price_position(last_price, kline_data)

        # 存储策略数据
        result.strategy_data = {
            'change_pct': change_pct,
            'volume': volume,
            'price_position': price_position,
            'plate_data': plate_data
        }

        # 检查板块强势度（如果提供）
        plate_check = self._check_plate_strength(plate_data)
        if not plate_check['passed']:
            result.buy_reason = plate_check['reason']
            return result

        # 检查买入信号
        buy_check = self._check_buy_conditions(change_pct, volume, price_position)
        if buy_check['passed']:
            result.buy_signal = True
            result.buy_reason = buy_check['reason']
            result.signal_strength = buy_check['strength']
            return result

        # 如果不满足买入条件，说明原因
        result.buy_reason = buy_check['reason']

        return result

    def _check_plate_strength(self, plate_data: Optional[Dict]) -> Dict[str, Any]:
        """
        检查板块强势度

        Args:
            plate_data: 板块数据

        Returns:
            检查结果 {passed, reason}
        """
        if not plate_data:
            # 如果没有板块数据，跳过板块检查
            return {'passed': True, 'reason': ''}

        strength_score = plate_data.get('strength_score', 0)
        rank = plate_data.get('rank', 999)

        if strength_score < self.strategy_config.min_plate_strength:
            return {
                'passed': False,
                'reason': f"板块强势度不足 ({strength_score:.1f} < {self.strategy_config.min_plate_strength})"
            }

        if rank > self.strategy_config.max_plate_rank:
            return {
                'passed': False,
                'reason': f"板块排名过低 (第{rank}名 > 前{self.strategy_config.max_plate_rank}名)"
            }

        return {'passed': True, 'reason': ''}

    def _check_buy_conditions(
        self,
        change_pct: float,
        volume: int,
        price_position: float
    ) -> Dict[str, Any]:
        """
        检查买入条件

        Args:
            change_pct: 涨跌幅 (%)
            volume: 成交量
            price_position: 价格位置 (0-100)

        Returns:
            检查结果 {passed, reason, strength}
        """
        reasons = []

        # 涨幅检查
        if change_pct < self.strategy_config.min_change_pct:
            reasons.append(f"涨幅不足 ({change_pct:.2f}% < {self.strategy_config.min_change_pct}%)")
        elif change_pct > self.strategy_config.max_change_pct:
            reasons.append(f"涨幅过高 ({change_pct:.2f}% > {self.strategy_config.max_change_pct}%)")

        # 成交量检查
        if volume < self.strategy_config.min_volume:
            volume_wan = volume / 10000
            min_volume_wan = self.strategy_config.min_volume / 10000
            reasons.append(f"成交量不足 ({volume_wan:.0f}万 < {min_volume_wan:.0f}万)")

        # 价格位置检查
        if price_position < self.strategy_config.min_price_position:
            reasons.append(f"价格位置过低 ({price_position:.1f}% < {self.strategy_config.min_price_position}%)")
        elif price_position > self.strategy_config.max_price_position:
            reasons.append(f"价格位置过高 ({price_position:.1f}% > {self.strategy_config.max_price_position}%)")

        if reasons:
            return {
                'passed': False,
                'reason': '; '.join(reasons),
                'strength': 0.0
            }

        # 计算信号强度
        strength = self._calculate_signal_strength(change_pct, volume, price_position)

        return {
            'passed': True,
            'reason': f"满足买入条件: 涨幅{change_pct:.2f}%, 成交量{volume/10000:.0f}万, 位置{price_position:.1f}%",
            'strength': strength
        }

    def _calculate_price_position(
        self,
        current_price: float,
        kline_data: List[Dict[str, Any]]
    ) -> float:
        """
        计算30日价格位置

        Args:
            current_price: 当前价格
            kline_data: K线数据

        Returns:
            价格位置 (0-100)
        """
        if not kline_data or len(kline_data) < 5:
            return 50.0  # 默认中间位置

        # 取最近30天
        recent = kline_data[-30:] if len(kline_data) >= 30 else kline_data

        # 找出最高价和最低价
        highs = [k.get('high_price', 0) or k.get('high', 0) for k in recent]
        lows = [k.get('low_price', 0) or k.get('low', 0) for k in recent]

        high_30d = max(highs) if highs else current_price
        low_30d = min(lows) if lows else current_price

        if high_30d == low_30d:
            return 50.0

        position = (current_price - low_30d) / (high_30d - low_30d) * 100
        return max(0.0, min(100.0, position))

    def _calculate_signal_strength(
        self,
        change_pct: float,
        volume: int,
        price_position: float
    ) -> float:
        """
        计算信号强度

        Args:
            change_pct: 涨跌幅 (%)
            volume: 成交量
            price_position: 价格位置 (0-100)

        Returns:
            信号强度 (0-1)
        """
        # 涨幅评分 (0-0.4)
        # 最佳区间 3%-4%
        if 3.0 <= change_pct <= 4.0:
            change_score = 0.4
        elif 2.5 <= change_pct < 3.0 or 4.0 < change_pct <= 5.0:
            change_score = 0.3
        else:
            change_score = 0.2

        # 成交量评分 (0-0.3)
        volume_ratio = min(volume / 10000000, 1.0)
        volume_score = volume_ratio * 0.3

        # 价格位置评分 (0-0.3)
        # 越低位越好
        position_score = (1 - price_position / 100) * 0.3

        return change_score + volume_score + position_score

    def calculate_signal_strength(self, result: StrategyResult) -> float:
        """
        计算信号强度（覆盖基类方法）

        Args:
            result: 策略结果

        Returns:
            信号强度 (0-1)
        """
        if not result.has_signal:
            return 0.0

        data = result.strategy_data
        return self._calculate_signal_strength(
            data.get('change_pct', 0),
            data.get('volume', 0),
            data.get('price_position', 50)
        )

    def _build_condition_details(
        self,
        strategy_result: StrategyResult,
        quote_data: Dict[str, Any],
        kline_data: List[Dict[str, Any]]
    ) -> List[ConditionDetail]:
        """构建条件详情"""
        details = []
        data = strategy_result.strategy_data

        # 涨幅条件
        change_pct = data.get('change_pct', 0)
        change_passed = (self.strategy_config.min_change_pct <= change_pct <= self.strategy_config.max_change_pct)
        details.append(ConditionDetail(
            name="涨幅条件",
            current_value=f"{change_pct:.2f}%",
            target_value=f"{self.strategy_config.min_change_pct}% ~ {self.strategy_config.max_change_pct}%",
            passed=change_passed,
            description="涨幅应在2.5%-5%区间内"
        ))

        # 成交量条件
        volume = data.get('volume', 0)
        volume_passed = (volume >= self.strategy_config.min_volume)
        details.append(ConditionDetail(
            name="成交量条件",
            current_value=f"{volume/10000:.0f}万股",
            target_value=f">= {self.strategy_config.min_volume/10000:.0f}万股",
            passed=volume_passed,
            description="成交量应不低于500万股"
        ))

        # 价格位置条件
        position = data.get('price_position', 50)
        position_passed = (self.strategy_config.min_price_position <= position <= self.strategy_config.max_price_position)
        details.append(ConditionDetail(
            name="价格位置",
            current_value=f"{position:.1f}%",
            target_value=f"{self.strategy_config.min_price_position}% ~ {self.strategy_config.max_price_position}%",
            passed=position_passed,
            description="30日价格位置应在低位区间"
        ))

        # 板块强势度
        plate_data = data.get('plate_data', {})
        if plate_data:
            strength = plate_data.get('strength_score', 0)
            rank = plate_data.get('rank', 999)
            plate_passed = (strength >= self.strategy_config.min_plate_strength and
                          rank <= self.strategy_config.max_plate_rank)
            details.append(ConditionDetail(
                name="板块强势度",
                current_value=f"强势度{strength:.1f}, 排名第{rank}",
                target_value=f">= {self.strategy_config.min_plate_strength}, 前{self.strategy_config.max_plate_rank}名",
                passed=plate_passed,
                description="所属板块应处于强势状态"
            ))

        # 信号强度
        details.append(ConditionDetail(
            name="信号强度",
            current_value=f"{strategy_result.signal_strength:.2f}",
            target_value=f">= {self.strategy_config.min_signal_strength}",
            passed=strategy_result.signal_strength >= self.strategy_config.min_signal_strength,
            description="综合信号强度评分"
        ))

        return details

    def set_plate_strength(self, plate_code: str, strength_data: Dict[str, Any]):
        """
        设置板块强势度缓存

        Args:
            plate_code: 板块代码
            strength_data: 强势度数据
        """
        self._plate_strength_cache[plate_code] = strength_data

    def get_plate_strength(self, plate_code: str) -> Optional[Dict[str, Any]]:
        """获取板块强势度"""
        return self._plate_strength_cache.get(plate_code)

    def clear_plate_cache(self):
        """清空板块缓存"""
        self._plate_strength_cache.clear()
