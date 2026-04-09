"""
回测引擎

通用的回测引擎，负责：
- 管理回测流程
- 遍历历史数据
- 调用策略判断
- 记录交易信号
- 跟踪未来表现

支持单参数测试和参数优化模式。
"""

import logging
import pandas as pd
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict

from simple_trade.backtest.strategies.base_strategy import BaseBacktestStrategy
from simple_trade.backtest.core.data_loader import BacktestDataLoader
from simple_trade.backtest.core.strategy_adapter import LiveStrategyAdapter

logger = logging.getLogger(__name__)


@dataclass
class BacktestSignal:
    """回测信号数据结构"""
    date: str  # 买入日期
    stock_code: str  # 股票代码
    stock_name: str  # 股票名称
    buy_price: float  # 买入价格
    turnover_rate: float  # 换手率

    # 未来表现数据
    max_rise_pct: float = 0.0  # 最大涨幅（%）
    max_rise_days: int = 0  # 达到最大涨幅的天数
    day1_rise: float = 0.0  # 第1日涨幅
    day2_rise: float = 0.0  # 第2日涨幅
    day3_rise: float = 0.0  # 第3日涨幅
    is_target_reached: bool = False  # 是否达到目标涨幅

    # 策略特定数据
    strategy_data: Dict[str, Any] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        if result['strategy_data'] is None:
            result['strategy_data'] = {}
        return result


@dataclass
class BacktestResult:
    """回测结果数据结构"""
    # 基本信息
    start_date: str
    end_date: str
    stock_count: int

    # 信号统计
    signals: List[BacktestSignal]
    total_signals: int

    # 策略参数
    strategy_params: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'start_date': self.start_date,
            'end_date': self.end_date,
            'stock_count': self.stock_count,
            'total_signals': self.total_signals,
            'strategy_params': self.strategy_params,
            'signals': [s.to_dict() for s in self.signals]
        }


class BacktestEngine:
    """
    通用回测引擎

    负责执行回测流程，支持单参数测试和参数优化。
    """

    def __init__(
        self,
        strategy: Union[BaseBacktestStrategy, LiveStrategyAdapter],
        data_loader: BacktestDataLoader,
        start_date: str,
        end_date: str
    ):
        """
        初始化回测引擎

        Args:
            strategy: 回测策略实例，支持原生回测策略或通过适配器包装的实盘策略
            data_loader: 数据加载器实例
            start_date: 回测开始日期（YYYY-MM-DD）
            end_date: 回测结束日期（YYYY-MM-DD）
        """
        self.strategy = strategy
        self.data_loader = data_loader
        self.start_date = start_date
        self.end_date = end_date

        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def run(self) -> BacktestResult:
        """
        执行回测

        Returns:
            BacktestResult: 回测结果
        """
        self.logger.info(f"开始回测: {self.start_date} 至 {self.end_date}")
        self.logger.info(f"策略: {self.strategy.get_strategy_name()}")
        self.logger.info(f"参数: {self.strategy.get_params()}")

        # 1. 加载股票列表
        stock_list = self.data_loader.load_stock_list()
        self.logger.info(f"加载股票列表: {len(stock_list)}只")

        if not stock_list:
            self.logger.warning("股票列表为空，回测终止")
            return self._create_empty_result()

        # 2. 遍历每只股票，检查买入信号
        all_signals: List[BacktestSignal] = []

        for i, stock in enumerate(stock_list, 1):
            if i % 50 == 0:
                self.logger.info(f"处理进度: {i}/{len(stock_list)}")

            # 从股票字典中提取股票代码
            stock_code = stock.get('code') if isinstance(stock, dict) else stock

            try:
                signals = self._backtest_stock(stock_code)
                all_signals.extend(signals)
            except Exception as e:
                self.logger.error(f"处理股票 {stock_code} 失败: {e}")
                continue

        # 3. 生成回测结果
        result = BacktestResult(
            start_date=self.start_date,
            end_date=self.end_date,
            stock_count=len(stock_list),
            signals=all_signals,
            total_signals=len(all_signals),
            strategy_params=self.strategy.get_params()
        )

        self.logger.info(f"回测完成: 共生成 {len(all_signals)} 个信号")

        # 显示API使用统计
        if hasattr(self.data_loader, 'get_api_stats'):
            api_stats = self.data_loader.get_api_stats()
            self.logger.info(f"API使用统计: 请求次数={api_stats['api_request_count']}/{api_stats['max_api_requests']}, "
                           f"跳过股票数={api_stats['skipped_stocks_count']}")

        return result

    def _backtest_stock(self, stock_code: str) -> List[BacktestSignal]:
        """
        回测单只股票

        Args:
            stock_code: 股票代码

        Returns:
            List[BacktestSignal]: 该股票的所有信号
        """
        signals = []

        # 计算需要加载的数据范围
        # 需要提前加载 lookback_days，用于计算低吸位
        # 需要延后加载 holding_days，用于跟踪未来表现
        lookback_days = self.strategy.get_params().get('lookback_days', 30)
        holding_days = self.strategy.get_params().get('holding_days', 10)

        data_start = self._subtract_trading_days(self.start_date, lookback_days + 5)
        data_end = self._add_trading_days(self.end_date, holding_days + 5)

        # 加载K线数据
        kline_df = self.data_loader.load_kline_data(
            stock_code=stock_code,
            start_date=data_start,
            end_date=data_end
        )

        # 改进：不要因为数据不足就跳过整只股票，记录日志并统计
        if kline_df is None or kline_df.empty:
            self.logger.warning(f"{stock_code}: K线数据为空，跳过")
            return signals

        if len(kline_df) < lookback_days + 1:
            self.logger.warning(f"{stock_code}: K线数据不足 ({len(kline_df)}条，需要至少{lookback_days + 1}条)，跳过")
            return signals

        # 获取股票名称
        stock_name = self.data_loader.get_stock_name(stock_code)

        # 改进：使用字符串日期索引，避免datetime转换问题
        # 保持time_key为字符串格式，但只保留日期部分（去掉时间戳）
        kline_df['date'] = kline_df['time_key'].str[:10]  # 提取日期部分 YYYY-MM-DD
        kline_df = kline_df.set_index('date').sort_index()

        # 遍历回测日期范围
        start_dt = datetime.strptime(self.start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(self.end_date, '%Y-%m-%d')

        current_dt = start_dt
        while current_dt <= end_dt:
            date_str = current_dt.strftime('%Y-%m-%d')

            # 检查该日期是否有数据（使用字符串日期）
            if date_str not in kline_df.index:
                current_dt += timedelta(days=1)
                continue

            # 获取历史数据（用于策略判断）
            # 使用字符串日期切片
            historical_data = kline_df.loc[:date_str].tail(lookback_days + 1)

            # 改进：放宽历史数据长度要求，考虑周末/节假日
            # 只要有至少 lookback_days * 0.7 的数据就可以
            min_required_days = max(int(lookback_days * 0.7), 5)
            if len(historical_data) < min_required_days:
                current_dt += timedelta(days=1)
                continue

            # 当日数据
            today_data = historical_data.iloc[-1]

            # 检查买入信号
            is_buy = self.strategy.check_buy_signal(
                stock_code=stock_code,
                date=date_str,
                current_kline=today_data.to_dict(),
                historical_kline=historical_data.to_dict('records')
            )

            if is_buy:
                # 记录买入信号
                signal = BacktestSignal(
                    date=date_str,
                    stock_code=stock_code,
                    stock_name=stock_name,
                    buy_price=today_data['close_price'],
                    turnover_rate=today_data.get('turnover_rate', 0.0),
                    strategy_data=None
                )

                # 跟踪未来表现
                self._track_future_performance(signal, kline_df, current_dt)

                signals.append(signal)

            current_dt += timedelta(days=1)

        return signals

    def _track_future_performance(
        self,
        signal: BacktestSignal,
        kline_df: 'pd.DataFrame',
        buy_date: datetime
    ):
        """
        跟踪买入后的未来表现

        Args:
            signal: 买入信号
            kline_df: K线数据
            buy_date: 买入日期
        """
        holding_days = self.strategy.get_params().get('holding_days', 10)
        buy_price = signal.buy_price

        # 将buy_date转换为字符串格式以匹配索引
        buy_date_str = buy_date.strftime('%Y-%m-%d')

        # 获取未来N日的数据
        future_data = kline_df.loc[buy_date_str:].iloc[1:holding_days+1]  # 不包括买入当天

        if len(future_data) == 0:
            return

        max_rise_pct = 0.0
        max_rise_days = 0

        for i, (date, row) in enumerate(future_data.iterrows(), 1):
            high_price = row['high_price']
            close_price = row['close_price']

            # 计算当日最高涨幅
            day_high_rise = ((high_price - buy_price) / buy_price) * 100

            # 更新最大涨幅
            if day_high_rise > max_rise_pct:
                max_rise_pct = day_high_rise
                max_rise_days = i

            # 记录每日涨幅（基于收盘价）
            close_rise = ((close_price - buy_price) / buy_price) * 100
            if i == 1:
                signal.day1_rise = close_rise
            elif i == 2:
                signal.day2_rise = close_rise
            elif i == 3:
                signal.day3_rise = close_rise

        signal.max_rise_pct = max_rise_pct
        signal.max_rise_days = max_rise_days

        # 判断是否达到目标（对于低换手率策略，检查是否达到目标涨幅）
        target_rise = self.strategy.get_params().get('target_rise', 5.0)
        signal.is_target_reached = (max_rise_pct >= target_rise)

    def _create_empty_result(self) -> BacktestResult:
        """创建空的回测结果"""
        return BacktestResult(
            start_date=self.start_date,
            end_date=self.end_date,
            stock_count=0,
            signals=[],
            total_signals=0,
            strategy_params=self.strategy.get_params()
        )

    def _subtract_trading_days(self, date_str: str, days: int) -> datetime:
        """向前推算交易日（粗略估计）"""
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        # 粗略估计：每5个自然日约有3.5个交易日
        calendar_days = int(days * 1.5) + 5
        result_dt = dt - timedelta(days=calendar_days)
        return result_dt

    def _add_trading_days(self, date_str: str, days: int) -> datetime:
        """向后推算交易日（粗略估计）"""
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        calendar_days = int(days * 1.5) + 5
        result_dt = dt + timedelta(days=calendar_days)
        return result_dt
