#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日内交易回测引擎
支持5分钟K线级别的日内交易回测
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from ..strategies.intraday_strategy import (
    IntradayStrategy,
    IntradaySignal,
    StockFilterParams,
    IntradayTradeParams
)
from .fee_calculator import FeeCalculator


@dataclass
class IntradayBacktestResult:
    """日内回测结果"""
    signals: List[IntradaySignal]
    total_trades: int = 0
    win_count: int = 0
    loss_count: int = 0
    timeout_count: int = 0
    win_rate: float = 0.0
    avg_gross_profit: float = 0.0
    avg_net_profit: float = 0.0
    total_fee: float = 0.0
    max_profit: float = 0.0
    max_loss: float = 0.0
    profit_factor: float = 0.0
    stocks_traded: int = 0
    trading_days: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'total_trades': self.total_trades,
            'win_count': self.win_count,
            'loss_count': self.loss_count,
            'timeout_count': self.timeout_count,
            'win_rate': self.win_rate,
            'avg_gross_profit': self.avg_gross_profit,
            'avg_net_profit': self.avg_net_profit,
            'total_fee': self.total_fee,
            'max_profit': self.max_profit,
            'max_loss': self.max_loss,
            'profit_factor': self.profit_factor,
            'stocks_traded': self.stocks_traded,
            'trading_days': self.trading_days
        }


class IntradayBacktestEngine:
    """日内交易回测引擎"""

    def __init__(
        self,
        strategy: IntradayStrategy,
        fee_calculator: FeeCalculator,
        market: str = 'HK',
        trade_amount: float = 100000  # 每笔交易金额
    ):
        self.strategy = strategy
        self.fee_calculator = fee_calculator
        self.market = market
        self.trade_amount = trade_amount
        self.logger = logging.getLogger(__name__)

    def run_backtest(
        self,
        daily_kline_data: Dict[str, List[Dict]],
        minute_kline_data: Dict[str, Dict[str, List[Dict]]],
        intraday_stats: Dict[str, Dict[str, Any]],
        stock_names: Dict[str, str],
        start_date: str,
        end_date: str
    ) -> IntradayBacktestResult:
        """
        运行日内回测

        Args:
            daily_kline_data: {stock_code: [daily_klines]}
            minute_kline_data: {stock_code: {date: [minute_klines]}}
            intraday_stats: {stock_code: stats_dict}
            stock_names: {stock_code: stock_name}
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            IntradayBacktestResult
        """
        signals: List[IntradaySignal] = []
        trading_dates = set()
        traded_stocks = set()

        self.logger.info(f"开始日内回测: {start_date} ~ {end_date}")
        self.logger.info(f"股票数量: {len(daily_kline_data)}")

        # 遍历每只股票
        for stock_code, daily_klines in daily_kline_data.items():
            if not daily_klines:
                continue

            # 获取日内统计数据
            stats = intraday_stats.get(stock_code, {})
            stock_name = stock_names.get(stock_code, "")

            # 检查股票筛选条件
            passed, filter_data = self.strategy.check_stock_filter(
                daily_klines, stats
            )
            if not passed:
                continue

            # 获取该股票的分钟K线数据
            stock_minute_data = minute_kline_data.get(stock_code, {})
            if not stock_minute_data:
                continue

            # 遍历每个交易日
            for date, minute_klines in stock_minute_data.items():
                if date < start_date or date > end_date:
                    continue

                if not minute_klines:
                    continue

                # 模拟日内交易
                signal = self.strategy.simulate_intraday_trade(
                    minute_klines, filter_data
                )

                if signal:
                    signal.stock_code = stock_code
                    signal.stock_name = stock_name

                    # 计算手续费
                    fee_result = self.fee_calculator.calculate_round_trip_fee(
                        self.market,
                        self.trade_amount,
                        self.trade_amount * (1 + signal.gross_profit_pct / 100)
                    )
                    signal.fee_amount = fee_result['total_fee']
                    signal.net_profit_pct = (
                        signal.gross_profit_pct - fee_result['fee_rate']
                    )

                    signals.append(signal)
                    trading_dates.add(date)
                    traded_stocks.add(stock_code)

        # 计算统计结果
        result = self._calculate_statistics(signals)
        result.stocks_traded = len(traded_stocks)
        result.trading_days = len(trading_dates)

        self.logger.info(f"回测完成: {result.total_trades} 笔交易")
        return result

    def _calculate_statistics(
        self,
        signals: List[IntradaySignal]
    ) -> IntradayBacktestResult:
        """计算统计结果"""
        result = IntradayBacktestResult(signals=signals)

        if not signals:
            return result

        result.total_trades = len(signals)

        # 统计胜负
        gross_profits = []
        net_profits = []
        total_fee = 0.0
        total_gross_win = 0.0
        total_gross_loss = 0.0

        for signal in signals:
            gross_profits.append(signal.gross_profit_pct)
            net_profits.append(signal.net_profit_pct)
            total_fee += signal.fee_amount

            if signal.exit_type == 'profit':
                result.win_count += 1
                total_gross_win += signal.gross_profit_pct
            elif signal.exit_type == 'loss':
                result.loss_count += 1
                total_gross_loss += abs(signal.gross_profit_pct)
            else:
                result.timeout_count += 1
                if signal.gross_profit_pct >= 0:
                    total_gross_win += signal.gross_profit_pct
                else:
                    total_gross_loss += abs(signal.gross_profit_pct)

        # 计算统计指标
        result.win_rate = result.win_count / result.total_trades * 100
        result.avg_gross_profit = sum(gross_profits) / len(gross_profits)
        result.avg_net_profit = sum(net_profits) / len(net_profits)
        result.total_fee = total_fee
        result.max_profit = max(gross_profits)
        result.max_loss = min(gross_profits)

        # 盈亏比
        if total_gross_loss > 0:
            result.profit_factor = total_gross_win / total_gross_loss
        else:
            result.profit_factor = float('inf') if total_gross_win > 0 else 0

        return result

    def generate_report(
        self,
        result: IntradayBacktestResult,
        output_path: str
    ) -> str:
        """生成回测报告"""
        lines = [
            "# 日内交易回测报告",
            "",
            "## 策略参数",
            f"- 策略名称: {self.strategy.get_strategy_name()}",
            f"- 市场: {self.market}",
            f"- 每笔交易金额: {self.trade_amount:,.0f}",
            "",
            "### 股票筛选参数",
        ]

        params = self.strategy.get_params()
        for key, value in params['filter'].items():
            lines.append(f"- {key}: {value}")

        lines.extend([
            "",
            "### 交易参数",
        ])
        for key, value in params['trade'].items():
            lines.append(f"- {key}: {value}")

        lines.extend([
            "",
            "## 回测结果",
            "",
            f"| 指标 | 数值 |",
            f"|------|------|",
            f"| 总交易次数 | {result.total_trades} |",
            f"| 盈利次数 | {result.win_count} |",
            f"| 亏损次数 | {result.loss_count} |",
            f"| 超时平仓 | {result.timeout_count} |",
            f"| 胜率 | {result.win_rate:.2f}% |",
            f"| 平均毛收益 | {result.avg_gross_profit:.2f}% |",
            f"| 平均净收益 | {result.avg_net_profit:.2f}% |",
            f"| 总手续费 | {result.total_fee:,.2f} |",
            f"| 最大盈利 | {result.max_profit:.2f}% |",
            f"| 最大亏损 | {result.max_loss:.2f}% |",
            f"| 盈亏比 | {result.profit_factor:.2f} |",
            f"| 交易股票数 | {result.stocks_traded} |",
            f"| 交易天数 | {result.trading_days} |",
            "",
        ])

        # 写入文件
        content = "\n".join(lines)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)

        self.logger.info(f"报告已生成: {output_path}")
        return content
