#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量活跃度筛选脚本

功能：
1. 批量订阅目标板块美股的实时行情
2. 筛选换手率低于阈值的股票
3. 标记为低活跃度
4. 支持断点续传
"""

import sys
import os
import time
import logging
import json
from datetime import datetime
from typing import List, Dict, Any

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from simple_trade.database.core.db_manager import DatabaseManager
from simple_trade.api.futu_client import FutuClient
from simple_trade.api.subscription_manager import SubscriptionManager
from simple_trade.services.core import StockMarkerService


def setup_logging():
    """配置日志"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def load_progress(progress_file: str) -> Dict[str, Any]:
    """加载进度文件

    Args:
        progress_file: 进度文件路径

    Returns:
        dict: 进度数据
    """
    if os.path.exists(progress_file):
        try:
            with open(progress_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.warning(f"加载进度文件失败: {e}")

    return {
        'processed_stocks': [],
        'low_activity_stocks': [],
        'last_batch_index': 0,
        'start_time': None
    }


def save_progress(progress_file: str, progress: Dict[str, Any]):
    """保存进度文件

    Args:
        progress_file: 进度文件路径
        progress: 进度数据
    """
    try:
        with open(progress_file, 'w', encoding='utf-8') as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"保存进度文件失败: {e}")


def get_unchecked_stocks(db: DatabaseManager, market: str = 'US') -> List[tuple]:
    """获取未检查活跃度的目标板块股票

    Args:
        db: 数据库管理器
        market: 市场代码

    Returns:
        list: 股票列表 [(code, id, name), ...]
    """
    sql = '''
        SELECT DISTINCT s.code, s.id, s.name
        FROM stocks s
        JOIN stock_plates sp ON s.id = sp.stock_id
        JOIN plates p ON sp.plate_id = p.id
        WHERE s.market = ?
          AND p.is_target = 1
          AND (s.activity_score IS NULL OR s.activity_score = 0)
          AND (s.is_low_activity IS NULL OR s.is_low_activity = 0)
          AND (s.is_otc IS NULL OR s.is_otc = 0)
        ORDER BY s.code
    '''

    try:
        rows = db.execute_query(sql, (market,))
        return rows if rows else []
    except Exception as e:
        logging.error(f"查询未检查股票失败: {e}")
        return []


def filter_by_turnover_rate(
    futu_client: FutuClient,
    stock_codes: List[str],
    threshold: float = 0.1,
    min_volume: int = 500000
) -> tuple:
    """根据换手率和成交量筛选股票

    Args:
        futu_client: 富途客户端
        stock_codes: 股票代码列表
        threshold: 换手率阈值（百分比）
        min_volume: 最低成交量阈值

    Returns:
        tuple: (活跃股票列表, 低活跃股票列表, 活跃度分数字典)
    """
    active_stocks = []
    low_activity_stocks = []
    activity_scores = {}

    try:
        # 获取实时报价
        ret, data = futu_client.client.get_stock_quote(stock_codes)

        if ret != 0:
            logging.error(f"获取报价失败: {data}")
            return active_stocks, low_activity_stocks, activity_scores

        # 筛选
        for _, row in data.iterrows():
            code = row['code']
            turnover_rate = row.get('turnover_rate', 0)
            volume = row.get('volume', 0)

            # 计算活跃度分数（换手率）
            activity_scores[code] = turnover_rate

            # 双重条件：换手率 AND 成交量
            if turnover_rate < threshold or volume < min_volume:
                low_activity_stocks.append(code)
                logging.debug(f"低活跃: {code} 换手率={turnover_rate:.2f}%, 成交量={volume:,}")
            else:
                active_stocks.append(code)
                logging.debug(f"活跃: {code} 换手率={turnover_rate:.2f}%, 成交量={volume:,}")

    except Exception as e:
        logging.error(f"筛选股票失败: {e}")

    return active_stocks, low_activity_stocks, activity_scores


def process_batch(
    batch: List[tuple],
    batch_index: int,
    total_batches: int,
    subscription_manager: SubscriptionManager,
    futu_client: FutuClient,
    stock_marker: StockMarkerService,
    threshold: float,
    min_volume: int = 500000,
    wait_quote_time: int = 3,
    batch_interval: int = 90
) -> Dict[str, Any]:
    """处理单个批次

    Args:
        batch: 股票批次 [(code, id, name), ...]
        batch_index: 批次索引
        total_batches: 总批次数
        subscription_manager: 订阅管理器
        futu_client: 富途客户端
        stock_marker: 股票标记服务
        threshold: 换手率阈值
        min_volume: 最低成交量阈值
        wait_quote_time: 等待报价时间（秒）
        batch_interval: 批次间隔时间（秒）

    Returns:
        dict: 处理结果
    """
    result = {
        'success': False,
        'active_count': 0,
        'low_activity_count': 0,
        'quota_exhausted': False
    }

    batch_codes = [stock[0] for stock in batch]

    logging.info(f"\n{'='*70}")
    logging.info(f"处理第 {batch_index}/{total_batches} 批: {len(batch_codes)} 只股票")
    logging.info(f"{'='*70}")

    try:
        # 记录订阅开始时间
        subscribe_start_time = time.time()

        # 1. 订阅
        logging.info("步骤1: 订阅实时行情...")
        sub_result = subscription_manager.subscribe(batch_codes)

        if not sub_result['success']:
            logging.error(f"订阅失败: {sub_result['message']}")

            # 检查是否额度不足
            if sub_result.get('deferred_stocks'):
                logging.warning(f"订阅额度不足，{len(sub_result['deferred_stocks'])} 只股票被延迟")
                result['quota_exhausted'] = True

            return result

        successful_codes = sub_result['successful_stocks']
        logging.info(f"成功订阅 {len(successful_codes)} 只股票")

        # 2. 等待报价数据
        logging.info(f"步骤2: 等待 {wait_quote_time} 秒获取报价数据...")
        time.sleep(wait_quote_time)

        # 3. 获取报价并筛选
        logging.info(f"步骤3: 筛选换手率低于 {threshold}% 且成交量低于 {min_volume} 的股票...")
        active, low_activity, scores = filter_by_turnover_rate(
            futu_client, successful_codes, threshold, min_volume
        )

        result['active_count'] = len(active)
        result['low_activity_count'] = len(low_activity)

        logging.info(f"筛选结果: 活跃 {len(active)} 只, 低活跃 {len(low_activity)} 只")

        # 4. 标记低活跃股票
        if low_activity:
            logging.info(f"步骤4: 标记 {len(low_activity)} 只低活跃股票...")
            stock_marker.mark_low_activity_stocks(low_activity, scores)

        # 5. 确保订阅至少70秒后才取消（富途API限制，保守设置）
        elapsed_time = time.time() - subscribe_start_time
        min_subscribe_time = 70  # 保守设置为70秒

        if elapsed_time < min_subscribe_time:
            wait_time = min_subscribe_time - elapsed_time
            logging.info(f"步骤5: 等待 {wait_time:.1f} 秒以满足取消订阅的最小时间要求...")
            time.sleep(wait_time)

        # 6. 取消订阅所有股票（释放额度）
        logging.info(f"步骤6: 取消订阅所有股票以释放额度...")
        subscription_manager.unsubscribe(successful_codes)

        # 7. 批次间隔
        if batch_index < total_batches:
            # 计算已经过的总时间
            total_elapsed = time.time() - subscribe_start_time
            remaining_interval = max(0, batch_interval - total_elapsed)

            if remaining_interval > 0:
                logging.info(f"步骤7: 等待 {remaining_interval:.1f} 秒后处理下一批...")
                time.sleep(remaining_interval)

        result['success'] = True

    except Exception as e:
        logging.error(f"处理批次失败: {e}", exc_info=True)

    return result


def main(
    threshold: float = 0.3,
    batch_size: int = 300,
    wait_quote_time: int = 3,
    batch_interval: int = 90,
    market: str = 'US',
    min_volume: int = 500000,
    resume: bool = False,
    auto_confirm: bool = False
):
    """主函数

    Args:
        threshold: 换手率阈值（百分比）
        batch_size: 批次大小
        wait_quote_time: 等待报价时间（秒）
        batch_interval: 批次间隔时间（秒）
        market: 市场代码
        min_volume: 最低成交量阈值
        resume: 是否从上次中断处继续
        auto_confirm: 是否自动确认
    """
    setup_logging()

    print("=" * 70)
    print("批量活跃度筛选")
    print("=" * 70)
    print(f"市场: {market}")
    print(f"换手率阈值: {threshold}%")
    print(f"批次大小: {batch_size} 只/批")
    print(f"等待报价时间: {wait_quote_time} 秒")
    print(f"批次间隔: {batch_interval} 秒")
    print()

    # 初始化服务
    db_path = 'simple_trade/data/trade.db'
    db = DatabaseManager(db_path)

    futu_client = FutuClient()
    if not futu_client.connect():
        print("✗ 富途API连接失败，请检查OpenD是否运行")
        sys.exit(1)

    subscription_manager = SubscriptionManager(futu_client, db)
    stock_marker = StockMarkerService(db)

    # 加载进度
    progress_file = f'scripts/.batch_filter_progress_{market}.json'
    progress = load_progress(progress_file) if resume else {
        'processed_stocks': [],
        'low_activity_stocks': [],
        'last_batch_index': 0,
        'start_time': datetime.now().isoformat()
    }

    # 获取未检查股票
    logging.info(f"正在查询未检查的{market}股票...")
    unchecked_stocks = get_unchecked_stocks(db, market)

    if not unchecked_stocks:
        print(f"\n✓ 没有需要检查的{market}股票")
        return

    # 过滤已处理的股票
    if resume and progress['processed_stocks']:
        processed_codes = set(progress['processed_stocks'])
        unchecked_stocks = [s for s in unchecked_stocks if s[0] not in processed_codes]
        logging.info(f"从上次中断处继续，剩余 {len(unchecked_stocks)} 只股票")

    print(f"\n找到 {len(unchecked_stocks)} 只未检查的{market}股票")

    # 分批处理
    total_batches = (len(unchecked_stocks) + batch_size - 1) // batch_size
    print(f"将分 {total_batches} 批处理\n")

    # 确认开始
    if not auto_confirm:
        confirm = input("确认开始批量筛选吗？(yes/no): ")
        if confirm.lower() not in ['yes', 'y']:
            print("已取消操作")
            return

    # 处理每个批次
    start_batch = progress['last_batch_index']
    total_active = 0
    total_low_activity = 0

    for i in range(start_batch, total_batches):
        batch_start = i * batch_size
        batch_end = min(batch_start + batch_size, len(unchecked_stocks))
        batch = unchecked_stocks[batch_start:batch_end]

        result = process_batch(
            batch, i + 1, total_batches,
            subscription_manager, futu_client, stock_marker,
            threshold, min_volume, wait_quote_time, batch_interval
        )

        if result['success']:
            total_active += result['active_count']
            total_low_activity += result['low_activity_count']

            # 更新进度
            progress['processed_stocks'].extend([s[0] for s in batch])
            progress['last_batch_index'] = i + 1
            save_progress(progress_file, progress)

        # 检查额度是否耗尽
        if result.get('quota_exhausted'):
            logging.warning("\n订阅额度已耗尽，停止处理")
            print("\n⚠ 订阅额度已耗尽")
            print(f"已处理: {i + 1}/{total_batches} 批")
            print(f"进度已保存到: {progress_file}")
            print("使用 --resume 参数可从中断处继续")
            break

    # 显示统计
    print("\n" + "=" * 70)
    print("筛选完成")
    print("=" * 70)
    print(f"活跃股票: {total_active} 只")
    print(f"低活跃股票: {total_low_activity} 只")
    print(f"处理批次: {progress['last_batch_index']}/{total_batches}")

    # 清理进度文件
    if progress['last_batch_index'] >= total_batches:
        if os.path.exists(progress_file):
            os.remove(progress_file)
        print("\n✓ 全部处理完成！")
    else:
        print(f"\n进度已保存: {progress_file}")

    # 断开连接
    futu_client.disconnect()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='批量活跃度筛选')
    parser.add_argument('--threshold', type=float, default=0.3, help='换手率阈值（默认0.3%%）')
    parser.add_argument('--batch-size', type=int, default=300, help='批次大小（默认300）')
    parser.add_argument('--wait-quote', type=int, default=3, help='等待报价时间（秒，默认3）')
    parser.add_argument('--batch-interval', type=int, default=90, help='批次间隔（秒，默认90）')
    parser.add_argument('--market', default='US', choices=['US', 'HK'], help='市场代码（默认US）')
    parser.add_argument('--min-volume', type=int, default=500000, help='最低成交量阈值（默认500000）')
    parser.add_argument('--resume', action='store_true', help='从上次中断处继续')
    parser.add_argument('--auto-confirm', action='store_true', help='自动确认，不询问用户')

    args = parser.parse_args()

    main(
        threshold=args.threshold,
        batch_size=args.batch_size,
        wait_quote_time=args.wait_quote,
        batch_interval=args.batch_interval,
        market=args.market,
        min_volume=args.min_volume,
        resume=args.resume,
        auto_confirm=args.auto_confirm
    )
