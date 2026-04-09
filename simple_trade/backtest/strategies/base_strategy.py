"""
回测策略抽象基类

所有回测策略都必须继承此基类，并实现关键方法。
这确保了回测引擎可以统一调用不同策略的接口。
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from datetime import datetime


class BaseBacktestStrategy(ABC):
    """
    回测策略抽象基类

    所有策略必须实现以下方法：
    - check_buy_signal: 检查是否满足买入条件
    - check_exit_condition: 检查是否满足退出条件（止盈/止损/超时）
    - get_strategy_name: 返回策略名称
    - get_params: 返回策略参数
    """

    def __init__(self, **kwargs):
        """
        初始化策略

        Args:
            **kwargs: 策略参数，具体参数由子类定义
        """
        self.params = kwargs

    @abstractmethod
    def get_strategy_name(self) -> str:
        """
        返回策略名称

        Returns:
            策略名称字符串
        """
        pass

    @abstractmethod
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
            stock_code: 股票代码（如 HK.00700）
            date: 当前日期（YYYY-MM-DD）
            current_kline: 当日K线数据
                {
                    'time_key': str,
                    'open_price': float,
                    'close_price': float,
                    'high_price': float,
                    'low_price': float,
                    'volume': int,
                    'turnover': float,
                    'turnover_rate': float
                }
            historical_kline: 历史K线数据列表（按时间倒序，最新的在前）

        Returns:
            是否满足买入条件
        """
        pass

    @abstractmethod
    def check_exit_condition(
        self,
        buy_date: str,
        buy_price: float,
        current_date: str,
        current_kline: Dict[str, Any],
        future_kline: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        检查是否满足退出条件（止盈/止损/超时）

        Args:
            buy_date: 买入日期
            buy_price: 买入价格
            current_date: 当前日期
            current_kline: 当日K线数据
            future_kline: 未来K线数据列表（按时间正序）

        Returns:
            退出结果字典
            {
                'is_exit': bool,           # 是否满足退出条件
                'exit_type': str,          # 退出类型：'profit'止盈/'loss'止损/'timeout'超时
                'exit_date': str,          # 退出日期
                'exit_price': float,       # 退出价格
                'holding_days': int,       # 持有天数
                'return_pct': float,       # 收益率（%）
                'max_rise_pct': float,     # 最大涨幅（%）
                'max_rise_date': str,      # 最大涨幅日期
                'max_drawdown_pct': float, # 最大回撤（%）
            }
        """
        pass

    def get_params(self) -> Dict[str, Any]:
        """
        返回策略参数

        Returns:
            参数字典
        """
        return self.params.copy()

    def calculate_rise_pct(self, buy_price: float, current_price: float) -> float:
        """
        计算涨幅百分比

        Args:
            buy_price: 买入价格
            current_price: 当前价格

        Returns:
            涨幅百分比
        """
        if buy_price == 0:
            return 0.0
        return ((current_price - buy_price) / buy_price) * 100.0

    def calculate_days_diff(self, start_date: str, end_date: str) -> int:
        """
        计算日期差

        Args:
            start_date: 开始日期（YYYY-MM-DD）
            end_date: 结束日期（YYYY-MM-DD）

        Returns:
            天数差
        """
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
        return (end - start).days

    def get_lookback_days(self) -> int:
        """
        返回策略需要的历史数据天数

        默认返回30天，子类可以覆盖此方法

        Returns:
            需要的历史天数
        """
        return 30

    def get_forward_days(self) -> int:
        """
        返回策略需要的未来数据天数（用于跟踪持仓表现）

        默认返回10天，子类可以覆盖此方法

        Returns:
            需要的未来天数
        """
        return 10

    def __str__(self) -> str:
        """返回策略描述"""
        params_str = ', '.join([f'{k}={v}' for k, v in self.params.items()])
        return f"{self.get_strategy_name()}({params_str})"

    def __repr__(self) -> str:
        """返回策略表示"""
        return self.__str__()
