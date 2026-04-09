"""
回测运行器基类

提供统一的回测运行流程和初始化逻辑
"""

import sys
import os
from abc import ABC, abstractmethod
from typing import Optional
import logging

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from simple_trade.database.core.db_manager import DatabaseManager
from simple_trade.config.config import Config
from simple_trade.backtest.core.loaders.backtest_only_loader import BacktestOnlyDataLoader
from simple_trade.backtest.strategies.base_strategy import BaseBacktestStrategy
from simple_trade.backtest.utils.logging_config import setup_backtest_logging
from simple_trade.backtest.utils.date_utils import parse_date_range


class BaseBacktestRunner(ABC):
    """回测运行器基类"""

    def __init__(self, args):
        """
        初始化回测运行器

        Args:
            args: 命令行参数对象
        """
        self.args = args
        self.logger: Optional[logging.Logger] = None
        self.db_manager: Optional[DatabaseManager] = None
        self.data_loader: Optional[BacktestOnlyDataLoader] = None
        self.config: Optional[Config] = None

    def run(self):
        """运行回测（主入口）"""
        # 1. 初始化
        self.setup()

        # 2. 根据模式选择运行方式
        if hasattr(self.args, 'optimize') and self.args.optimize:
            self.run_optimization()
        else:
            self.run_baseline()

    def setup(self):
        """初始化配置"""
        # 1. 配置日志
        self.logger = setup_backtest_logging(
            output_dir=self.args.output,
            log_name=self.get_log_name()
        )

        self.logger.info("=" * 80)
        self.logger.info(f"{self.get_strategy_name()} 回测系统启动")
        self.logger.info("=" * 80)

        # 2. 解析日期范围
        start_date, end_date = parse_date_range(
            self.args.start if hasattr(self.args, 'start') else None,
            self.args.end if hasattr(self.args, 'end') else None
        )
        self.args.start = start_date
        self.args.end = end_date

        self.logger.info(f"回测时间范围：{start_date} 至 {end_date}")

        # 3. 初始化配置
        self.config = Config()

        # 4. 初始化数据库
        self.db_manager = DatabaseManager(self.config.database_path)

        # 5. 初始化数据加载器
        self.data_loader = self.create_data_loader()

        self.logger.info("初始化完成")

    def create_data_loader(self) -> BacktestOnlyDataLoader:
        """
        创建回测专用数据加载器（只读数据库）

        Returns:
            BacktestOnlyDataLoader实例
        """
        return BacktestOnlyDataLoader(
            self.db_manager,
            market='HK',
            use_stock_pool_only=True,
            only_stocks_with_kline=True,
            min_kline_days=20
        )

    @abstractmethod
    def create_strategy(self) -> BaseBacktestStrategy:
        """
        创建策略实例（子类必须实现）

        Returns:
            策略实例
        """
        pass

    @abstractmethod
    def run_baseline(self):
        """运行基准回测（子类必须实现）"""
        pass

    @abstractmethod
    def run_optimization(self):
        """运行参数优化（子类必须实现）"""
        pass

    @abstractmethod
    def get_strategy_name(self) -> str:
        """获取策略名称（子类必须实现）"""
        pass

    def get_log_name(self) -> str:
        """获取日志文件名"""
        return 'backtest'

    def print_summary(self, analysis: dict):
        """
        打印回测结果摘要

        Args:
            analysis: 分析结果字典
        """
        self.logger.info("=" * 80)
        self.logger.info("回测结果摘要")
        self.logger.info("=" * 80)
        self.logger.info(f"总信号数：{analysis.get('total_signals', 0)}")
        self.logger.info(f"上涨次数：{analysis.get('rise_count', 0)}")
        self.logger.info(f"胜率：{analysis.get('win_rate', 0):.2f}%")
        self.logger.info(f"平均涨幅：{analysis.get('avg_rise', 0):.2f}%")
        self.logger.info(f"最大涨幅：{analysis.get('max_rise', 0):.2f}%")
        if 'avg_days_to_peak' in analysis:
            self.logger.info(
                f"平均达到最高点天数：{analysis['avg_days_to_peak']:.1f}天"
            )
        self.logger.info("=" * 80)
