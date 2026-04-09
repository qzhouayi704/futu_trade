"""
低换手率策略

测试条件：
1. 股票处于近N日最低点（低吸位）
2. 当天换手率低于阈值
3. 统计未来N日内是否达到目标涨幅

参数：
- lookback_days: 回看天数（计算最低点）
- turnover_threshold: 换手率阈值（%）
- low_position_tolerance: 低位容忍度（1.0=必须最低，1.02=最低点的102%以内）
- target_rise: 目标涨幅（%）
- holding_days: 持有天数（跟踪未来表现）
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
import pandas as pd

from simple_trade.backtest.strategies.base_strategy import BaseBacktestStrategy


class LowTurnoverStrategy(BaseBacktestStrategy):
    """
    低换手率策略

    买入条件：
    1. 股票处于近N日最低点（或接近最低点）
    2. 当天换手率 < 阈值

    胜利条件：
    未来N日内最高涨幅 >= 目标涨幅
    """

    def __init__(
        self,
        lookback_days: int = 8,
        turnover_threshold: float = 0.1,
        low_position_tolerance: float = 1.02,
        target_rise: float = 5.0,
        holding_days: int = 3
    ):
        """
        初始化策略参数

        Args:
            lookback_days: 回看天数，用于计算最低点
            turnover_threshold: 换手率阈值（%），低于此值才触发
            low_position_tolerance: 低位容忍度，1.0=必须是最低点，1.02=最低点的102%以内
            target_rise: 目标涨幅（%），用于判断是否成功
            holding_days: 持有天数，用于跟踪未来表现
        """
        super().__init__(
            lookback_days=lookback_days,
            turnover_threshold=turnover_threshold,
            low_position_tolerance=low_position_tolerance,
            target_rise=target_rise,
            holding_days=holding_days
        )
        self.lookback_days = lookback_days
        self.turnover_threshold = turnover_threshold
        self.low_position_tolerance = low_position_tolerance
        self.target_rise = target_rise
        self.holding_days = holding_days

    def get_strategy_name(self) -> str:
        """返回策略名称"""
        return "低换手率策略"

    def check_buy_signal(
        self,
        stock_code: str,
        date: str,
        current_kline: Dict[str, Any],
        historical_kline: List[Dict[str, Any]]
    ) -> bool:
        """
        检查是否满足买入条件

        Args:
            stock_code: 股票代码
            date: 当前日期
            current_kline: 当天的K线数据
            historical_kline: 历史K线数据（包含当天及之前的数据）

        Returns:
            是否满足买入条件
        """
        # 1. 检查换手率
        turnover_rate = current_kline.get('turnover_rate', 0)
        # 改进：如果换手率为None，使用0（表示极低换手）
        if turnover_rate is None:
            turnover_rate = 0
        if turnover_rate >= self.turnover_threshold:
            return False

        # 2. 检查是否处于低吸位
        if not self._is_low_position(current_kline, historical_kline):
            return False

        return True

    def check_exit_condition(
        self,
        buy_date: str,
        buy_price: float,
        current_date: str,
        current_kline: Dict[str, Any],
        future_kline: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        检查是否满足退出条件

        对于低换手率策略，我们只跟踪未来表现，不主动退出。

        Args:
            buy_date: 买入日期
            buy_price: 买入价格
            current_date: 当前日期
            current_kline: 当日K线数据
            future_kline: 未来K线数据列表

        Returns:
            退出结果字典
        """
        # 计算表现
        performance = self.calculate_performance(buy_price, future_kline)

        # 计算持有天数
        holding_days = min(len(future_kline), self.holding_days)

        return {
            'is_exit': True,  # 总是在持有期结束后退出
            'exit_type': 'timeout',
            'exit_date': current_date,
            'exit_price': future_kline[-1].get('close_price', buy_price) if future_kline else buy_price,
            'holding_days': holding_days,
            'return_pct': performance['max_rise_pct'],
            'max_rise_pct': performance['max_rise_pct'],
            'max_rise_date': buy_date,  # 简化处理
            'max_drawdown_pct': 0.0  # 暂不计算回撤
        }

    def calculate_performance(
        self,
        buy_price: float,
        future_kline: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        计算买入后的表现

        Args:
            buy_price: 买入价格
            future_kline: 未来的K线数据

        Returns:
            表现指标字典
        """
        if not future_kline:
            return {
                'max_rise_pct': 0.0,
                'max_rise_days': 0,
                'is_target_reached': False,
                'day_rises': {}
            }

        # 计算每日涨幅
        day_rises = {}
        max_rise_pct = 0.0
        max_rise_days = 0
        is_target_reached = False

        for i, kline in enumerate(future_kline[:self.holding_days], 1):
            high_price = kline.get('high_price', 0)
            if high_price <= 0:
                continue

            # 计算涨幅
            rise_pct = ((high_price - buy_price) / buy_price) * 100
            day_rises[f'day{i}_rise'] = round(rise_pct, 2)

            # 更新最高涨幅
            if rise_pct > max_rise_pct:
                max_rise_pct = rise_pct
                max_rise_days = i

            # 检查是否达到目标
            if rise_pct >= self.target_rise:
                is_target_reached = True

        return {
            'max_rise_pct': round(max_rise_pct, 2),
            'max_rise_days': max_rise_days,
            'is_target_reached': is_target_reached,
            'day_rises': day_rises
        }

    def _is_low_position(
        self,
        current_kline: Dict[str, Any],
        history_kline: List[Dict[str, Any]]
    ) -> bool:
        """
        判断是否处于低吸位

        Args:
            current_kline: 当天K线
            history_kline: 历史K线（包含当天）

        Returns:
            是否处于低吸位
        """
        # 获取当前价格（使用收盘价）
        current_price = current_kline.get('close_price', 0)
        if current_price <= 0:
            return False

        # 获取近N日K线（不包括当天）
        recent_kline = [k for k in history_kline if k != current_kline][-self.lookback_days:]

        # 改进：放宽数据不足的要求，只要有至少70%的数据就可以
        min_required_days = max(int(self.lookback_days * 0.7), 3)
        if len(recent_kline) < min_required_days:
            # 数据不足，无法判断
            return False

        # 计算近N日最低价
        low_prices = [k.get('low_price', float('inf')) for k in recent_kline]
        # 过滤掉无效值
        low_prices = [p for p in low_prices if p > 0 and p != float('inf')]

        if not low_prices:
            return False

        min_low_price = min(low_prices)

        # 判断当前价格是否接近最低点
        # 例如：tolerance=1.02 表示当前价格 <= 最低点 * 1.02
        threshold_price = min_low_price * self.low_position_tolerance

        return current_price <= threshold_price

    def get_required_lookback_days(self) -> int:
        """
        获取所需的历史数据天数

        Returns:
            需要的历史天数
        """
        return self.lookback_days + 5  # 额外5天作为缓冲

    def get_required_future_days(self) -> int:
        """
        获取需要跟踪的未来天数

        Returns:
            需要的未来天数
        """
        return self.holding_days

    def validate_params(self) -> bool:
        """
        验证策略参数是否合法

        Returns:
            参数是否合法
        """
        if self.lookback_days < 1:
            return False
        if self.turnover_threshold < 0:
            return False
        if self.low_position_tolerance < 1.0:
            return False
        if self.target_rise <= 0:
            return False
        if self.holding_days < 1:
            return False
        return True

    def get_strategy_description(self) -> str:
        """
        获取策略描述

        Returns:
            策略描述文本
        """
        return f"""
低换手率策略

买入条件：
1. 股票处于近{self.lookback_days}日最低点的{self.low_position_tolerance}倍以内
2. 当天换手率 < {self.turnover_threshold}%

成功标准：
未来{self.holding_days}日内最高涨幅 >= {self.target_rise}%
        """.strip()
