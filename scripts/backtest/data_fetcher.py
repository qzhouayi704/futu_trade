"""
数据获取工具

用于获取回测所需的K线数据，支持日线和分钟线
"""

import sys
import os
import logging
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from simple_trade.database.core.db_manager import DatabaseManager
from simple_trade.config.config import Config
from simple_trade.api.futu_client import FutuClient
from simple_trade.services.analysis.kline.kline_5min_fetcher import Kline5MinFetcher
from simple_trade.services.analysis.kline.kline_fetcher import KlineFetcher
from simple_trade.backtest.utils.logging_config import setup_backtest_logging


# 热门港股科网股列表（用于快速回测）
HOT_TECH_STOCKS = [
    'HK.09988',  # 阿里巴巴
    'HK.00700',  # 腾讯控股
    'HK.09999',  # 网易
    'HK.03690',  # 美团
    'HK.09618',  # 京东
    'HK.09888',  # 百度
    'HK.01024',  # 快手
    'HK.09626',  # 哔哩哔哩
    'HK.00981',  # 中芯国际
    'HK.01810',  # 小米集团
    'HK.02015',  # 理想汽车
    'HK.09866',  # 蔚来
    'HK.09868',  # 小鹏汽车
    'HK.06060',  # 众安在线
    'HK.02518',  # 汽车之家
]


class DataFetcher:
    """数据获取工具"""

    def __init__(self, args):
        """
        初始化数据获取工具

        Args:
            args: 命令行参数对象
        """
        self.args = args
        self.logger = None
        self.config = None
        self.db_manager = None
        self.futu_client = None

    def fetch(self):
        """获取数据（主入口）"""
        # 1. 配置日志
        self.logger = setup_backtest_logging(
            output_dir='logs',
            log_name='data_fetch'
        )

        # 2. 初始化配置和数据库
        self.config = Config()
        self.db_manager = DatabaseManager(self.config.database_path)

        # 3. 连接富途API
        self.futu_client = FutuClient(
            self.config.futu_host,
            self.config.futu_port
        )

        if not self.futu_client.connect():
            self.logger.error("无法连接富途API")
            return

        # 4. 根据参数选择获取类型
        kline_type = getattr(self.args, 'kline_type', '5min')

        if kline_type == 'daily':
            self._fetch_daily_kline()
        elif kline_type == '5min':
            self._fetch_5min_kline()
        elif kline_type == 'both':
            self._fetch_daily_kline()
            self._fetch_5min_kline()
        else:
            self.logger.error(f"不支持的K线类型: {kline_type}")

        # 关闭连接
        self.futu_client.disconnect()
        self.logger.info("数据获取完成")

    def _fetch_daily_kline(self):
        """获取日线数据"""
        self.logger.info("=" * 80)
        self.logger.info("开始获取日线数据...")
        self.logger.info("=" * 80)

        # 创建K线获取器
        fetcher = KlineFetcher(self.futu_client, self.config)

        # 获取股票池中的股票
        stocks = self._get_stock_list()
        self.logger.info(f"找到 {len(stocks)} 只股票")

        # 限制数量
        if hasattr(self.args, 'limit') and self.args.limit:
            if self.args.limit < len(stocks):
                stocks = stocks[:self.args.limit]
                self.logger.info(f"限制为前 {self.args.limit} 只股票")

        # 计算日期范围
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)

        # 批量获取
        success_count = 0
        failed_count = 0

        for i, stock in enumerate(stocks, 1):
            stock_code = stock['code']
            self.logger.info(f"[{i}/{len(stocks)}] 获取 {stock_code} 的日线数据...")

            try:
                # 获取K线数据
                kline_data = fetcher.fetch_kline_data(
                    stock_code,
                    days=365,
                    ktype='K_DAY'
                )

                if kline_data:
                    # 保存到数据库
                    self._save_kline_to_db(stock_code, kline_data, 'daily')
                    success_count += 1
                    self.logger.info(f"  ✓ 成功获取 {len(kline_data)} 条日线数据")
                else:
                    failed_count += 1
                    self.logger.warning(f"  ✗ 未获取到数据")

            except Exception as e:
                failed_count += 1
                self.logger.error(f"  ✗ 获取失败: {e}")

        # 输出统计
        self.logger.info("=" * 80)
        self.logger.info(f"日线数据获取完成: 成功 {success_count}, 失败 {failed_count}")
        self.logger.info("=" * 80)

    def _fetch_5min_kline(self):
        """获取5分钟K线数据"""
        self.logger.info("=" * 80)
        self.logger.info("开始获取5分钟K线数据...")
        self.logger.info("=" * 80)

        # 创建K线获取器
        fetcher = Kline5MinFetcher(
            self.futu_client,
            self.db_manager,
            self.config
        )

        # 根据参数选择股票列表
        stock_filter = getattr(self.args, 'stock_filter', None)

        if stock_filter == 'hot_tech':
            stocks = HOT_TECH_STOCKS
            self.logger.info(f"使用热门科网股列表: {len(stocks)} 只")
            for s in stocks:
                self.logger.info(f"  - {s}")
        elif stock_filter == 'custom' and hasattr(self.args, 'custom_stocks'):
            stocks = self.args.custom_stocks
            self.logger.info(f"使用自定义股票列表: {len(stocks)} 只")
        else:
            # 默认：获取已有日线数据的股票
            stocks = fetcher.get_stocks_with_daily_kline()
            self.logger.info(f"找到 {len(stocks)} 只有日线数据的股票")

        # 限制数量
        if hasattr(self.args, 'limit') and self.args.limit:
            if self.args.limit < len(stocks):
                stocks = stocks[:self.args.limit]
                self.logger.info(f"限制为前 {self.args.limit} 只股票")

        # 计算日期范围（5分钟线3个月足够日内回测）
        end_date = datetime.now().strftime('%Y-%m-%d')
        days_back = getattr(self.args, 'days', 90)
        start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')

        # 批量获取
        results = fetcher.fetch_batch(stocks, start_date, end_date)

        # 输出统计
        self.logger.info("=" * 80)
        self.logger.info(f"成功获取 {len(results)} 只股票的5分钟K线")
        skipped = fetcher.get_skipped_stocks()
        if skipped:
            self.logger.info(f"跳过 {len(skipped)} 只股票:")
            for item in skipped[:10]:
                self.logger.info(f"  - {item['code']}: {item['reason']}")
        self.logger.info("=" * 80)

    def _get_stock_list(self):
        """获取股票列表"""
        # 从股票池获取
        query = """
            SELECT DISTINCT s.id, s.code, s.name
            FROM stocks s
            INNER JOIN stock_plates sp ON s.id = sp.stock_id
            WHERE s.market = 'HK'
            ORDER BY s.code
        """
        results = self.db_manager.execute_query(query)

        stocks = []
        for row in results:
            stocks.append({
                'id': row[0],
                'code': row[1],
                'name': row[2]
            })

        return stocks

    def _save_kline_to_db(self, stock_code, kline_data, kline_type):
        """保存K线数据到数据库"""
        # 这里需要根据实际的数据库表结构来实现
        # 暂时留空，由具体的fetcher实现
        pass
