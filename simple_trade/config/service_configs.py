#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
服务配置对象模块

提供各个服务的配置类，替代多个参数传递，提高代码可读性和可维护性
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ActivityFilterConfig:
    """
    活跃度筛选配置

    用于 ActivityFilterService 的配置参数
    """
    min_turnover_rate: float = 0.5
    """最小换手率（%）"""

    min_volume: float = 1000000.0
    """最小成交量"""

    min_amount: float = 10000000.0
    """最小成交额"""

    check_days: int = 5
    """检查天数"""

    continuous_days: int = 3
    """连续低活跃天数阈值"""


@dataclass
class HeatCalculatorConfig:
    """
    热度计算配置

    用于 StockHeatCalculator 和 EnhancedHeatCalculator 的配置参数
    """
    base_weight: float = 0.4
    """基础热度权重"""

    capital_weight: float = 0.3
    """资金流向权重"""

    technical_weight: float = 0.2
    """技术指标权重"""

    sentiment_weight: float = 0.1
    """市场情绪权重"""

    min_score: float = 0.0
    """最小热度分数"""

    max_score: float = 100.0
    """最大热度分数"""

    cache_ttl: int = 300
    """缓存过期时间（秒）"""


@dataclass
class SignalProcessorConfig:
    """
    信号处理配置

    用于 AggressiveSignalProcessor 的配置参数
    """
    max_signals: int = 10
    """最大信号数量"""

    min_score: float = 60.0
    """最小信号分数"""

    score_threshold: float = 70.0
    """信号分数阈值"""

    enable_plate_filter: bool = True
    """是否启用板块筛选"""

    enable_leader_filter: bool = True
    """是否启用龙头股筛选"""

    max_position_count: int = 5
    """最大持仓数量"""


@dataclass
class RiskConfig:
    """
    风险控制配置

    用于 RiskChecker 和 RiskCoordinator 的配置参数
    """
    max_position_ratio: float = 0.3
    """单只股票最大持仓比例"""

    max_loss_ratio: float = 0.1
    """最大亏损比例"""

    stop_loss_ratio: float = 0.05
    """止损比例"""

    take_profit_ratio: float = 0.15
    """止盈比例"""

    max_drawdown: float = 0.2
    """最大回撤"""

    enable_dynamic_stop_loss: bool = True
    """是否启用动态止损"""

    trailing_stop_ratio: float = 0.03
    """移动止损比例"""


@dataclass
class ScreeningConfig:
    """
    策略筛选配置

    用于 StrategyScreeningService 的配置参数
    """
    enable_cache: bool = True
    """是否启用缓存"""

    cache_ttl: int = 600
    """缓存过期时间（秒）"""

    max_stocks: int = 100
    """最大筛选股票数"""

    min_market_cap: float = 1000000000.0
    """最小市值"""

    min_turnover_rate: float = 0.5
    """最小换手率"""

    enable_kline_check: bool = True
    """是否启用K线额度检查"""


@dataclass
class MonitorConfig:
    """
    监控配置

    用于 StrategyMonitorService 的配置参数
    """
    check_interval: int = 60
    """检查间隔（秒）"""

    enable_alert: bool = True
    """是否启用告警"""

    alert_threshold: float = 0.05
    """告警阈值"""

    max_history_days: int = 30
    """最大历史天数"""

    enable_signal_history: bool = True
    """是否启用信号历史"""


@dataclass
class TradingConfig:
    """
    交易配置

    用于 FutuTradeService 和 TradeService 的配置参数
    """
    enable_auto_trade: bool = False
    """是否启用自动交易"""

    max_order_amount: float = 100000.0
    """单笔最大订单金额"""

    min_order_amount: float = 1000.0
    """单笔最小订单金额"""

    order_timeout: int = 30
    """订单超时时间（秒）"""

    enable_risk_check: bool = True
    """是否启用风险检查"""

    enable_position_limit: bool = True
    """是否启用持仓限制"""

    max_retry_count: int = 3
    """最大重试次数"""


@dataclass
class BacktestConfig:
    """
    回测配置

    用于回测引擎的配置参数
    """
    initial_capital: float = 1000000.0
    """初始资金"""

    commission_rate: float = 0.0003
    """佣金费率"""

    slippage_rate: float = 0.001
    """滑点率"""

    enable_short_selling: bool = False
    """是否允许做空"""

    max_position_ratio: float = 0.3
    """单只股票最大持仓比例"""

    benchmark: Optional[str] = None
    """基准指数代码"""


@dataclass
class ServiceContainerConfig:
    """
    服务容器配置

    用于 ServiceContainer 的配置参数，包含所有子服务的配置
    """
    activity_filter: ActivityFilterConfig = field(default_factory=ActivityFilterConfig)
    """活跃度筛选配置"""

    heat_calculator: HeatCalculatorConfig = field(default_factory=HeatCalculatorConfig)
    """热度计算配置"""

    signal_processor: SignalProcessorConfig = field(default_factory=SignalProcessorConfig)
    """信号处理配置"""

    risk: RiskConfig = field(default_factory=RiskConfig)
    """风险控制配置"""

    screening: ScreeningConfig = field(default_factory=ScreeningConfig)
    """策略筛选配置"""

    monitor: MonitorConfig = field(default_factory=MonitorConfig)
    """监控配置"""

    trading: TradingConfig = field(default_factory=TradingConfig)
    """交易配置"""

    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    """回测配置"""
