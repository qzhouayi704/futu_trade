"""
回测框架

这是一个通用的回测框架，支持多种策略的回测和参数优化。

核心组件：
- core.engine: 通用回测引擎
- core.data_loader: 通用数据加载器
- core.analyzer: 通用结果分析器
- core.reporter: 通用报告生成器

策略组件：
- strategies.base_strategy: 策略基类（抽象接口）
- strategies.low_turnover_strategy: 低换手率策略

使用示例：
    from simple_trade.backtest.core.engine import BacktestEngine
    from simple_trade.backtest.core.data_loader import BacktestDataLoader
    from simple_trade.backtest.strategies.low_turnover_strategy import LowTurnoverStrategy

    # 初始化组件
    data_loader = BacktestDataLoader(db_manager, market='HK')
    strategy = LowTurnoverStrategy(lookback_days=8, turnover_threshold=0.1)
    engine = BacktestEngine(strategy, data_loader, start_date, end_date)

    # 执行回测
    result = engine.run()
"""

from simple_trade.backtest.core.engine import BacktestEngine
from simple_trade.backtest.core.data_loader import BacktestDataLoader
from simple_trade.backtest.core.analyzer import BacktestAnalyzer
from simple_trade.backtest.core.reporter import BacktestReporter
from simple_trade.backtest.strategies.base_strategy import BaseBacktestStrategy

__all__ = [
    'BacktestEngine',
    'BacktestDataLoader',
    'BacktestAnalyzer',
    'BacktestReporter',
    'BaseBacktestStrategy',
]
