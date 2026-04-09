"""
回测核心模块

包含回测框架的核心组件，这些组件是通用的，可以被所有策略复用。

核心组件：
- engine: 回测引擎，管理回测流程
- data_loader: 数据加载器，加载历史K线数据
- analyzer: 结果分析器，统计回测指标
- reporter: 报告生成器，输出回测报告
"""

from .data_loader import BacktestDataLoader
from .strategy_adapter import LiveStrategyAdapter

__all__ = ['BacktestDataLoader', 'LiveStrategyAdapter']
