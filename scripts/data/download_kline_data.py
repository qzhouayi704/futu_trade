"""
K线数据批量下载脚本

用法：
python scripts/download_kline_data.py --start 2024-06-02 --end 2026-02-06

参数：
--start: 开始日期（默认：1年前）
--end: 结束日期（默认：今天）
--stocks: 最大股票数量（默认：500）
--delay: 请求间隔秒数（默认：0.5）
--check-quota: 只检查额度，不下载
--resume: 从上次中断处继续
"""

import os
import sys
import json
import time
import argparse
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from simple_trade.database.core.db_manager import DatabaseManager
from simple_trade.services.analysis.kline_fetcher import KlineFetcher
from simple_trade.services.analysis.kline_storage import KlineStorage
from simple_trade.backtest.core.data_loader import BacktestDataLoader
from simple_trade.config.config import Config
from simple_trade.api.futu_client import FutuClient

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,  # 改为DEBUG级别以查看详细错误
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/kline_download.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


# 导入统一的 RateLimiter
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from simple_trade.utils.rate_limiter import RateLimiter


def load_progress(progress_file='backtest_results/kline_download_progress.json'):
    """加载下载进度"""
    if os.path.exists(progress_file):
        try:
            with open(progress_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"加载进度文件失败: {e}")
    return None


def save_progress(progress, progress_file='backtest_results/kline_download_progress.json'):
    """保存下载进度"""
    try:
        os.makedirs(os.path.dirname(progress_file), exist_ok=True)
        with open(progress_file, 'w', encoding='utf-8') as f:
            json.dump(progress, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"保存进度文件失败: {e}")


def check_quota(kline_fetcher):
    """检查K线额度"""
    try:
        quota_info = kline_fetcher.get_quota_info()
        logger.info("=" * 60)
        logger.info("K线额度信息：")
        logger.info(f"- 剩余额度：{quota_info.get('remaining', 'N/A')}")
        logger.info(f"- 已使用：{quota_info.get('used', 'N/A')}")
        logger.info("=" * 60)
        return quota_info
    except Exception as e:
        logger.error(f"检查额度失败: {e}")
        return None


def download_kline_batch(
    db_manager,
    start_date,
    end_date,
    max_stocks=500,
    delay=0.5,
    resume=False
):
    """批量下载K线数据"""
    logger.info("=" * 60)
    logger.info("K线数据批量下载")
    logger.info("=" * 60)

    # 初始化服务
    config = Config()
    futu_client = FutuClient(host=config.futu_host, port=config.futu_port)

    # 连接富途API
    if not futu_client.connect():
        logger.error("❌ 富途API连接失败，请检查：")
        logger.error("   1. 富途OpenD是否已启动")
        logger.error("   2. 富途客户端是否已登录")
        logger.error("   3. 配置文件中的host和port是否正确")
        logger.error("   4. 网络连接是否正常")
        return

    logger.info("✅ 富途API连接成功")

    kline_fetcher = KlineFetcher(futu_client, config)
    kline_storage = KlineStorage(db_manager)
    data_loader = BacktestDataLoader(
        db_manager=db_manager,
        market='HK',
        enable_api_fetch=False,  # 不在加载时自动获取
        only_stocks_with_kline=False  # 加载所有股票
    )

    # 检查额度
    quota_info = check_quota(kline_fetcher)
    if not quota_info:
        logger.error("无法获取K线额度信息，退出")
        return

    # 加载股票列表
    logger.info("加载股票列表...")
    stocks = data_loader.load_stock_list()
    if max_stocks:
        stocks = stocks[:max_stocks]
    logger.info(f"共 {len(stocks)} 只股票")

    # 加载进度
    progress = load_progress() if resume else None
    downloaded_set = set(progress.get('downloaded_list', [])) if progress else set()
    failed_set = set(progress.get('failed_list', [])) if progress else set()

    # 过滤已下载的股票
    stocks_to_download = [s for s in stocks if s['code'] not in downloaded_set]

    logger.info(f"已下载: {len(downloaded_set)} 只")
    logger.info(f"待下载: {len(stocks_to_download)} 只")

    if not stocks_to_download:
        logger.info("所有股票已下载完成！")
        return

    # 批量下载
    rate_limiter = RateLimiter(max_requests=60, time_window=30)
    start_time = time.time()

    for i, stock in enumerate(stocks_to_download, 1):
        stock_code = stock['code']
        stock_name = stock.get('name', stock_code)

        # 频率控制
        rate_limiter.wait_if_needed()

        try:
            # 计算需要的天数
            days = (end_date - start_date).days + 10

            # 下载K线数据
            logger.info(f"[{i}/{len(stocks_to_download)}] {stock_code} ({stock_name}): 开始下载 {days} 天K线数据...")
            kline_data = kline_fetcher.fetch_kline_data(stock_code, days)

            if kline_data:
                # 保存到数据库
                saved_count = kline_storage.save_kline_batch(stock_code, kline_data)
                logger.info(
                    f"[{i}/{len(stocks_to_download)}] {stock_code} ({stock_name}): "
                    f"下载 {len(kline_data)} 条，保存 {saved_count} 条"
                )

                # 更新进度
                downloaded_set.add(stock_code)
                if stock_code in failed_set:
                    failed_set.remove(stock_code)
            else:
                logger.warning(
                    f"[{i}/{len(stocks_to_download)}] {stock_code} ({stock_name}): "
                    f"下载失败（返回空数据）- 可能原因：1) 股票已退市 2) API额度不足 3) 网络问题"
                )
                failed_set.add(stock_code)

        except Exception as e:
            logger.error(f"[{i}/{len(stocks_to_download)}] {stock_code}: 错误 - {e}")
            failed_set.add(stock_code)

        # 保存进度
        save_progress({
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d'),
            'total_stocks': len(stocks),
            'downloaded_stocks': len(downloaded_set),
            'failed_stocks': len(failed_set),
            'downloaded_list': list(downloaded_set),
            'failed_list': list(failed_set),
            'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })

        # 固定延迟
        rate_limiter.add_delay(delay)

    # 下载完成
    elapsed_time = time.time() - start_time
    logger.info("=" * 60)
    logger.info("下载完成！")
    logger.info(f"- 成功: {len(downloaded_set)} 只")
    logger.info(f"- 失败: {len(failed_set)} 只")
    logger.info(f"- 耗时: {elapsed_time:.1f} 秒")
    logger.info("=" * 60)


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='K线数据批量下载')

    parser.add_argument(
        '--start',
        type=str,
        default=(datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d'),
        help='开始日期（默认：1年前）'
    )

    parser.add_argument(
        '--end',
        type=str,
        default=datetime.now().strftime('%Y-%m-%d'),
        help='结束日期（默认：今天）'
    )

    parser.add_argument(
        '--stocks',
        type=int,
        default=500,
        help='最大股票数量（默认：500）'
    )

    parser.add_argument(
        '--delay',
        type=float,
        default=0.5,
        help='请求间隔秒数（默认：0.5）'
    )

    parser.add_argument(
        '--check-quota',
        action='store_true',
        help='只检查额度，不下载'
    )

    parser.add_argument(
        '--resume',
        action='store_true',
        help='从上次中断处继续'
    )

    return parser.parse_args()


def main():
    """主函数"""
    args = parse_args()

    # 解析日期
    start_date = datetime.strptime(args.start, '%Y-%m-%d')
    end_date = datetime.strptime(args.end, '%Y-%m-%d')

    # 初始化数据库
    db_path = os.path.join(project_root, 'simple_trade', 'data', 'trade.db')
    db_manager = DatabaseManager(db_path)

    # 初始化K线服务
    config = Config()
    futu_client = FutuClient(host=config.futu_host, port=config.futu_port)

    # 连接富途API
    if not futu_client.connect():
        logger.error("❌ 富途API连接失败")
        return

    kline_fetcher = KlineFetcher(futu_client, config)

    # 如果只检查额度
    if args.check_quota:
        check_quota(kline_fetcher)
        return

    # 批量下载
    download_kline_batch(
        db_manager=db_manager,
        start_date=start_date,
        end_date=end_date,
        max_stocks=args.stocks,
        delay=args.delay,
        resume=args.resume
    )


if __name__ == '__main__':
    main()

