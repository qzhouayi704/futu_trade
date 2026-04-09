#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日内交易策略
基于开盘价偏离度和历史日内低点规律的日内交易策略
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import datetime, time
from .base_strategy import BaseBacktestStrategy


@dataclass
class IntradaySignal:
    """日内交易信号"""
    date: str                           # 交易日期
    stock_code: str                     # 股票代码
    stock_name: str = ""                # 股票名称

    # 买入信息
    buy_time: str = ""                  # 买入时间 (HH:MM)
    buy_price: float = 0.0              # 买入价格
    open_price: float = 0.0             # 开盘价
    buy_deviation: float = 0.0          # 买入偏离度 (%)

    # 卖出信息
    sell_time: str = ""                 # 卖出时间
    sell_price: float = 0.0             # 卖出价格
    exit_type: str = ""                 # 退出类型: profit/loss/timeout

    # 收益信息
    gross_profit_pct: float = 0.0       # 毛收益率 (%)
    fee_amount: float = 0.0             # 手续费金额
    net_profit_pct: float = 0.0         # 净收益率 (%)

    # 筛选条件数据
    turnover_rate: float = 0.0          # 换手率
    daily_volume: int = 0               # 日成交量
    price_position: float = 0.0         # 股价位置 (%)
    recent_change: float = 0.0          # 近期涨跌幅 (%)
    avg_amplitude: float = 0.0          # 平均日内振幅 (%)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'date': self.date,
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'buy_time': self.buy_time,
            'buy_price': self.buy_price,
            'open_price': self.open_price,
            'buy_deviation': self.buy_deviation,
            'sell_time': self.sell_time,
            'sell_price': self.sell_price,
            'exit_type': self.exit_type,
            'gross_profit_pct': self.gross_profit_pct,
            'fee_amount': self.fee_amount,
            'net_profit_pct': self.net_profit_pct,
            'turnover_rate': self.turnover_rate,
            'daily_volume': self.daily_volume,
            'price_position': self.price_position,
            'recent_change': self.recent_change,
            'avg_amplitude': self.avg_amplitude
        }


@dataclass
class StockFilterParams:
    """股票筛选参数"""
    min_turnover_rate: float = 1.0      # 最低换手率 (%)
    max_turnover_rate: float = 8.0      # 最高换手率 (%)
    min_daily_turnover: float = 10000000  # 最低日成交额
    price_position_min: float = 20.0    # 股价位置下限 (%)
    price_position_max: float = 60.0    # 股价位置上限 (%)
    recent_change_min: float = -10.0    # 近期涨跌幅下限 (%)
    recent_change_max: float = 5.0      # 近期涨跌幅上限 (%)
    min_amplitude: float = 2.0          # 最低日内振幅 (%)
    lookback_days: int = 12             # 回看天数


@dataclass
class IntradayTradeParams:
    """日内交易参数"""
    buy_deviation: float = 1.5          # 买入偏离度 (%)
    target_profit: float = 2.0          # 目标收益率 (%)
    stop_loss: float = 1.5              # 止损比例 (%)
    entry_start_time: str = "09:45"     # 入场开始时间
    entry_end_time: str = "14:30"       # 入场结束时间
    force_exit_time: str = "15:30"      # 强制平仓时间


class IntradayStrategy(BaseBacktestStrategy):
    """日内交易策略"""

    def __init__(
        self,
        filter_params: Optional[StockFilterParams] = None,
        trade_params: Optional[IntradayTradeParams] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.filter_params = filter_params or StockFilterParams()
        self.trade_params = trade_params or IntradayTradeParams()

    def get_strategy_name(self) -> str:
        return "日内交易策略"

    def get_params(self) -> Dict[str, Any]:
        return {
            'filter': {
                'min_turnover_rate': self.filter_params.min_turnover_rate,
                'max_turnover_rate': self.filter_params.max_turnover_rate,
                'min_daily_turnover': self.filter_params.min_daily_turnover,
                'price_position_min': self.filter_params.price_position_min,
                'price_position_max': self.filter_params.price_position_max,
                'recent_change_min': self.filter_params.recent_change_min,
                'recent_change_max': self.filter_params.recent_change_max,
                'min_amplitude': self.filter_params.min_amplitude,
                'lookback_days': self.filter_params.lookback_days
            },
            'trade': {
                'buy_deviation': self.trade_params.buy_deviation,
                'target_profit': self.trade_params.target_profit,
                'stop_loss': self.trade_params.stop_loss,
                'entry_start_time': self.trade_params.entry_start_time,
                'entry_end_time': self.trade_params.entry_end_time,
                'force_exit_time': self.trade_params.force_exit_time
            }
        }

    def check_stock_filter(
        self,
        daily_kline: List[Dict[str, Any]],
        intraday_stats: Dict[str, Any]
    ) -> tuple[bool, Dict[str, Any]]:
        """
        检查股票是否满足筛选条件

        Args:
            daily_kline: 日线K线数据（按时间正序）
            intraday_stats: 日内统计数据

        Returns:
            (是否通过筛选, 筛选数据)
        """
        if len(daily_kline) < self.filter_params.lookback_days:
            return False, {}

        # 取最近的数据
        recent = daily_kline[-self.filter_params.lookback_days:]
        latest = daily_kline[-1]

        # 1. 换手率检查
        turnover_rate = latest.get('turnover_rate', 0) or 0
        if not (self.filter_params.min_turnover_rate <=
                turnover_rate <= self.filter_params.max_turnover_rate):
            return False, {}

        # 2. 成交额检查
        turnover = latest.get('turnover', 0) or 0
        if turnover < self.filter_params.min_daily_turnover:
            return False, {}

        # 3. 股价位置检查
        prices = [k['close_price'] for k in recent if k.get('close_price')]
        if not prices:
            return False, {}

        min_price = min(prices)
        max_price = max(prices)
        current_price = latest['close_price']

        if max_price == min_price:
            price_position = 50.0
        else:
            price_position = (current_price - min_price) / (max_price - min_price) * 100

        if not (self.filter_params.price_position_min <=
                price_position <= self.filter_params.price_position_max):
            return False, {}

        # 4. 近期涨跌幅检查
        first_price = recent[0]['close_price']
        if first_price > 0:
            recent_change = (current_price - first_price) / first_price * 100
        else:
            recent_change = 0

        if not (self.filter_params.recent_change_min <=
                recent_change <= self.filter_params.recent_change_max):
            return False, {}

        # 5. 日内振幅检查
        avg_amplitude = intraday_stats.get('avg_amplitude', 0)
        if avg_amplitude < self.filter_params.min_amplitude:
            return False, {}

        return True, {
            'turnover_rate': turnover_rate,
            'daily_volume': latest.get('volume', 0),
            'price_position': price_position,
            'recent_change': recent_change,
            'avg_amplitude': avg_amplitude
        }

    def simulate_intraday_trade(
        self,
        minute_klines: List[Dict[str, Any]],
        filter_data: Dict[str, Any]
    ) -> Optional[IntradaySignal]:
        """
        模拟日内交易

        Args:
            minute_klines: 5分钟K线数据（按时间正序）
            filter_data: 筛选数据

        Returns:
            IntradaySignal 或 None
        """
        if not minute_klines:
            return None

        # 获取开盘价（第一根K线）
        open_price = minute_klines[0]['open_price']
        if open_price <= 0:
            return None

        # 计算买入目标价
        buy_target = open_price * (1 - self.trade_params.buy_deviation / 100)

        # 解析时间参数
        entry_start = self._parse_time(self.trade_params.entry_start_time)
        entry_end = self._parse_time(self.trade_params.entry_end_time)
        force_exit = self._parse_time(self.trade_params.force_exit_time)

        # 模拟交易
        position = None  # 持仓信息
        signal = None

        for kline in minute_klines:
            kline_time = self._extract_time(kline['time_key'])
            if kline_time is None:
                continue

            low_price = kline['low_price']
            high_price = kline['high_price']
            close_price = kline['close_price']

            # 未持仓：检查买入条件
            if position is None:
                if entry_start <= kline_time <= entry_end:
                    if low_price <= buy_target:
                        # 买入
                        position = {
                            'buy_time': kline['time_key'],
                            'buy_price': buy_target,
                            'open_price': open_price
                        }
            else:
                # 已持仓：检查卖出条件
                buy_price = position['buy_price']

                # 止盈价
                profit_target = buy_price * (1 + self.trade_params.target_profit / 100)
                # 止损价
                stop_loss_price = buy_price * (1 - self.trade_params.stop_loss / 100)

                exit_type = None
                sell_price = None

                # 检查止盈
                if high_price >= profit_target:
                    exit_type = 'profit'
                    sell_price = profit_target
                # 检查止损
                elif low_price <= stop_loss_price:
                    exit_type = 'loss'
                    sell_price = stop_loss_price
                # 检查强制平仓
                elif kline_time >= force_exit:
                    exit_type = 'timeout'
                    sell_price = close_price

                if exit_type:
                    # 计算收益
                    gross_profit = (sell_price - buy_price) / buy_price * 100
                    deviation = (open_price - buy_price) / open_price * 100

                    signal = IntradaySignal(
                        date=kline['time_key'][:10],
                        stock_code="",  # 由调用方填充
                        buy_time=position['buy_time'][11:16],
                        buy_price=buy_price,
                        open_price=open_price,
                        buy_deviation=deviation,
                        sell_time=kline['time_key'][11:16],
                        sell_price=sell_price,
                        exit_type=exit_type,
                        gross_profit_pct=gross_profit,
                        **filter_data
                    )
                    break

        return signal

    def _parse_time(self, time_str: str) -> time:
        """解析时间字符串"""
        parts = time_str.split(':')
        return time(int(parts[0]), int(parts[1]))

    def _extract_time(self, time_key: str) -> Optional[time]:
        """从time_key提取时间"""
        try:
            # 格式: 2025-01-15 09:35:00
            time_part = time_key[11:16]
            parts = time_part.split(':')
            return time(int(parts[0]), int(parts[1]))
        except Exception:
            return None

    # 实现基类的抽象方法（日内策略不使用这些方法）
    def check_buy_signal(
        self,
        stock_code: str,
        date: str,
        current_kline: Dict[str, Any],
        historical_kline: List[Dict[str, Any]]
    ) -> bool:
        """日内策略不使用此方法"""
        return False

    def check_exit_condition(
        self,
        buy_date: str,
        buy_price: float,
        current_date: str,
        current_kline: Dict[str, Any],
        future_kline: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """日内策略不使用此方法"""
        return {'is_exit': False}
