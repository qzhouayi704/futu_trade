"""
日内交易回测运行器

实现日内交易策略的回测流程
"""

import json
from .base_runner import BaseBacktestRunner
from simple_trade.backtest.core.intraday_engine import IntradayBacktestEngine
from simple_trade.backtest.core.fee_calculator import FeeCalculator
from simple_trade.backtest.strategies.intraday_strategy import (
    IntradayStrategy,
    StockFilterParams,
    IntradayTradeParams
)


class IntradayRunner(BaseBacktestRunner):
    """日内交易回测运行器"""

    def get_strategy_name(self) -> str:
        """获取策略名称"""
        return "日内交易策略"

    def create_strategy(self) -> IntradayStrategy:
        """创建日内交易策略实例"""
        filter_params = StockFilterParams(
            min_turnover_rate=getattr(self.args, 'min_turnover', 1.0),
            max_turnover_rate=getattr(self.args, 'max_turnover', 8.0),
            min_daily_turnover=getattr(self.args, 'min_amount', 10000000),
            min_amplitude=getattr(self.args, 'min_amplitude', 2.0)
        )

        trade_params = IntradayTradeParams(
            buy_deviation=getattr(self.args, 'buy_deviation', 1.5),
            target_profit=getattr(self.args, 'target_profit', 2.0),
            stop_loss=getattr(self.args, 'stop_loss', 1.5)
        )

        return IntradayStrategy(filter_params, trade_params)

    def run_baseline(self):
        """运行基准回测"""
        self.logger.info("开始日内交易回测")

        # 创建策略
        strategy = self.create_strategy()

        # 创建手续费计算器
        fee_calculator = self._create_fee_calculator()

        # 创建回测引擎
        engine = IntradayBacktestEngine(
            strategy=strategy,
            fee_calculator=fee_calculator,
            market='HK',
            trade_amount=getattr(self.args, 'trade_amount', 100000)
        )

        # 加载数据
        self.logger.info("加载数据...")
        daily_kline_data = self._load_daily_kline()
        minute_kline_data = self._load_minute_kline()
        intraday_stats = self._calculate_intraday_stats()
        stock_names = self._load_stock_names()

        self.logger.info(f"日线数据: {len(daily_kline_data)} 只股票")
        self.logger.info(f"分钟数据: {len(minute_kline_data)} 只股票")

        # 运行回测
        result = engine.run_backtest(
            daily_kline_data,
            minute_kline_data,
            intraday_stats,
            stock_names,
            self.args.start,
            self.args.end
        )

        # 生成报告
        import os
        report_path = os.path.join(
            self.args.output,
            f"intraday_{self.args.start}_{self.args.end}.md"
        )
        os.makedirs(self.args.output, exist_ok=True)
        engine.generate_report(result, report_path)

        # 输出结果
        self._print_intraday_summary(result)

    def run_optimization(self):
        """运行参数优化"""
        self.logger.warning("日内交易策略的参数优化暂未实现")

    def _create_fee_calculator(self) -> FeeCalculator:
        """创建手续费计算器"""
        config_path = 'simple_trade/config.json'
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            fee_config = config_data.get('trading_fees', {})
        except Exception as e:
            self.logger.warning(f"无法读取手续费配置: {e}，使用默认配置")
            fee_config = {}

        return FeeCalculator(fee_config)

    def _load_daily_kline(self) -> dict:
        """加载日线K线数据"""
        query = '''
            SELECT stock_code, time_key, open_price, close_price,
                   high_price, low_price, volume, turnover, turnover_rate
            FROM kline_data
            WHERE time_key >= ? AND time_key <= ?
            ORDER BY stock_code, time_key
        '''
        rows = self.db_manager.execute_query(
            query, (self.args.start, self.args.end)
        )

        data = {}
        for row in rows:
            code = row[0]
            if code not in data:
                data[code] = []
            data[code].append({
                'time_key': row[1],
                'open_price': row[2],
                'close_price': row[3],
                'high_price': row[4],
                'low_price': row[5],
                'volume': row[6],
                'turnover': row[7],
                'turnover_rate': row[8]
            })

        return data

    def _load_minute_kline(self) -> dict:
        """加载5分钟K线数据"""
        query = '''
            SELECT stock_code, time_key, open_price, close_price,
                   high_price, low_price, volume, turnover, turnover_rate
            FROM kline_5min_data
            WHERE time_key >= ? AND time_key <= ?
            ORDER BY stock_code, time_key
        '''
        rows = self.db_manager.execute_query(
            query,
            (f"{self.args.start} 00:00:00", f"{self.args.end} 23:59:59")
        )

        data = {}
        for row in rows:
            code = row[0]
            date = row[1][:10]

            if code not in data:
                data[code] = {}
            if date not in data[code]:
                data[code][date] = []

            data[code][date].append({
                'time_key': row[1],
                'open_price': row[2],
                'close_price': row[3],
                'high_price': row[4],
                'low_price': row[5],
                'volume': row[6],
                'turnover': row[7],
                'turnover_rate': row[8]
            })

        return data

    def _calculate_intraday_stats(self) -> dict:
        """计算日内统计数据"""
        query = '''
            SELECT stock_code,
                   AVG((high_price - low_price) / open_price * 100) as avg_amplitude
            FROM (
                SELECT stock_code, DATE(time_key) as trade_date,
                       MAX(high_price) as high_price,
                       MIN(low_price) as low_price,
                       (SELECT open_price FROM kline_5min_data k2
                        WHERE k2.stock_code = k1.stock_code
                        AND DATE(k2.time_key) = DATE(k1.time_key)
                        ORDER BY k2.time_key LIMIT 1) as open_price
                FROM kline_5min_data k1
                WHERE time_key >= ? AND time_key <= ?
                GROUP BY stock_code, DATE(time_key)
            )
            WHERE open_price > 0
            GROUP BY stock_code
        '''

        try:
            rows = self.db_manager.execute_query(
                query,
                (f"{self.args.start} 00:00:00", f"{self.args.end} 23:59:59")
            )
            return {row[0]: {'avg_amplitude': row[1] or 0} for row in rows}
        except Exception:
            return {}

    def _load_stock_names(self) -> dict:
        """加载股票名称"""
        query = 'SELECT code, name FROM stocks'
        rows = self.db_manager.execute_query(query)
        return {row[0]: row[1] or "" for row in rows}

    def _print_intraday_summary(self, result):
        """打印日内回测结果摘要"""
        print("\n" + "=" * 50)
        print("日内交易回测结果")
        print("=" * 50)
        print(f"总交易次数: {result.total_trades}")
        print(f"胜率: {result.win_rate:.2f}%")
        print(f"平均毛收益: {result.avg_gross_profit:.2f}%")
        print(f"平均净收益: {result.avg_net_profit:.2f}%")
        print(f"总手续费: {result.total_fee:,.2f}")
        print(f"盈亏比: {result.profit_factor:.2f}")
        print("=" * 50)
