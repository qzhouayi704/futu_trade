"""
实盘策略适配器

将实盘策略（BaseStrategy）适配为回测策略接口（BaseBacktestStrategy），
使回测引擎能直接调用实盘策略的 check_signals() 方法。

这样新增策略只需实现一次实盘接口，即可同时用于实盘和回测。
"""

import logging
from typing import Dict, List, Any

from simple_trade.backtest.strategies.base_strategy import BaseBacktestStrategy
from simple_trade.strategy.base_strategy import BaseStrategy, StrategyResult

logger = logging.getLogger(__name__)


class LiveStrategyAdapter(BaseBacktestStrategy):
    """
    将实盘策略适配为回测策略接口

    适配层负责：
    1. 将回测 K 线数据格式转换为实盘策略所需的 quote_data 和 kline_data 格式
    2. 调用实盘策略的 check_signals() 获取买入信号
    3. 调用实盘策略的 check_stop_loss()（如有）或 check_signals() 获取退出信号
    """

    def __init__(self, live_strategy: BaseStrategy, **kwargs):
        """
        初始化适配器

        Args:
            live_strategy: 实盘策略实例
            **kwargs: 传递给 BaseBacktestStrategy 的参数
        """
        super().__init__(**kwargs)
        self.live_strategy = live_strategy

    def get_strategy_name(self) -> str:
        """返回实盘策略名称"""
        return self.live_strategy.name

    def check_buy_signal(
        self,
        stock_code: str,
        date: str,
        current_kline: Dict[str, Any],
        historical_kline: List[Dict[str, Any]]
    ) -> bool:
        """
        通过实盘策略检查买入信号

        将回测 K 线数据转换为实盘格式，调用 check_signals()。

        Args:
            stock_code: 股票代码
            date: 当前日期
            current_kline: 当日 K 线数据（回测格式）
            historical_kline: 历史 K 线列表（回测格式）

        Returns:
            是否满足买入条件
        """
        quote_data = self._kline_to_quote(current_kline)
        kline_data = self._convert_kline_list(historical_kline)

        try:
            result: StrategyResult = self.live_strategy.check_signals(
                stock_code, quote_data, kline_data
            )
            return result.buy_signal
        except Exception as e:
            logger.error(f"适配器买入信号检查失败 {stock_code}: {e}")
            return False

    def check_exit_condition(
        self,
        buy_date: str,
        buy_price: float,
        current_date: str,
        current_kline: Dict[str, Any],
        future_kline: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        通过实盘策略检查退出条件

        优先使用 check_stop_loss()（如有），否则使用 check_signals() 的卖出信号。

        Args:
            buy_date: 买入日期
            buy_price: 买入价格
            current_date: 当前日期
            current_kline: 当日 K 线数据
            future_kline: 未来 K 线列表

        Returns:
            退出结果字典，包含 is_exit, exit_type, exit_date, exit_price 等
        """
        current_price = current_kline.get('close_price', 0)
        holding_days = self.calculate_days_diff(buy_date, current_date)

        # 默认退出结果
        exit_result = {
            'is_exit': False,
            'exit_type': '',
            'exit_date': current_date,
            'exit_price': current_price,
            'holding_days': holding_days,
            'return_pct': self.calculate_rise_pct(buy_price, current_price),
            'max_rise_pct': 0.0,
            'max_rise_date': '',
            'max_drawdown_pct': 0.0,
        }

        # 计算未来 K 线中的最大涨幅和最大回撤
        self._calc_future_extremes(exit_result, buy_price, future_kline)

        try:
            # 优先使用 check_stop_loss
            if hasattr(self.live_strategy, 'check_stop_loss'):
                exit_result = self._check_exit_via_stop_loss(
                    exit_result, buy_price, current_kline, future_kline
                )
            else:
                exit_result = self._check_exit_via_signals(
                    exit_result, current_kline, future_kline
                )
        except Exception as e:
            logger.error(f"适配器退出条件检查失败: {e}")

        return exit_result

    # ==================== 数据转换方法 ====================

    def _kline_to_quote(self, kline: Dict[str, Any]) -> Dict[str, Any]:
        """
        将回测 K 线数据转换为实盘报价格式

        Args:
            kline: 回测 K 线字典（含 close_price, high_price 等）

        Returns:
            实盘 quote_data 格式字典
        """
        return {
            'last_price': kline.get('close_price', 0),
            'high_price': kline.get('high_price', 0),
            'low_price': kline.get('low_price', 0),
            'open_price': kline.get('open_price', 0),
            'volume': kline.get('volume', 0),
        }

    def _convert_kline_list(self, klines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        将回测 K 线列表转换为实盘 K 线格式

        Args:
            klines: 回测 K 线列表（含 time_key, open_price 等）

        Returns:
            实盘 kline_data 格式列表
        """
        return [
            {
                'date': k.get('time_key', ''),
                'open': k.get('open_price', 0),
                'close': k.get('close_price', 0),
                'high': k.get('high_price', 0),
                'low': k.get('low_price', 0),
                'volume': k.get('volume', 0),
            }
            for k in klines
        ]

    # ==================== 退出检查辅助方法 ====================

    def _check_exit_via_stop_loss(
        self,
        exit_result: Dict[str, Any],
        buy_price: float,
        current_kline: Dict[str, Any],
        future_kline: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """通过实盘策略的 check_stop_loss 检查退出"""
        current_price = current_kline.get('close_price', 0)
        buy_date_high = current_kline.get('high_price', buy_price)
        kline_since_buy = self._convert_kline_list(future_kline)

        stop_result = self.live_strategy.check_stop_loss(
            stock_code='',
            buy_price=buy_price,
            buy_date_high=buy_date_high,
            current_price=current_price,
            kline_since_buy=kline_since_buy
        )

        if stop_result.should_stop_loss:
            exit_result['is_exit'] = True
            exit_result['exit_type'] = 'loss'
            exit_result['exit_price'] = current_price
            exit_result['return_pct'] = self.calculate_rise_pct(buy_price, current_price)

        return exit_result

    def _check_exit_via_signals(
        self,
        exit_result: Dict[str, Any],
        current_kline: Dict[str, Any],
        future_kline: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """通过实盘策略的 check_signals 卖出信号检查退出"""
        quote_data = self._kline_to_quote(current_kline)
        kline_data = self._convert_kline_list(future_kline)
        stock_code = ''

        result: StrategyResult = self.live_strategy.check_signals(
            stock_code, quote_data, kline_data
        )

        if result.sell_signal:
            current_price = current_kline.get('close_price', 0)
            exit_result['is_exit'] = True
            exit_result['exit_type'] = 'profit'
            exit_result['exit_price'] = current_price

        return exit_result

    def _calc_future_extremes(
        self,
        exit_result: Dict[str, Any],
        buy_price: float,
        future_kline: List[Dict[str, Any]]
    ) -> None:
        """计算未来 K 线中的最大涨幅和最大回撤"""
        if not future_kline or buy_price <= 0:
            return

        max_rise = 0.0
        max_rise_date = ''
        max_drawdown = 0.0

        for k in future_kline:
            high = k.get('high_price', 0)
            low = k.get('low_price', 0)
            date = k.get('time_key', '')

            if high > 0:
                rise = self.calculate_rise_pct(buy_price, high)
                if rise > max_rise:
                    max_rise = rise
                    max_rise_date = date

            if low > 0:
                drop = self.calculate_rise_pct(buy_price, low)
                if drop < max_drawdown:
                    max_drawdown = drop

        exit_result['max_rise_pct'] = max_rise
        exit_result['max_rise_date'] = max_rise_date
        exit_result['max_drawdown_pct'] = max_drawdown
