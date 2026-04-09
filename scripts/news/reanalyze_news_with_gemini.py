#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量重新分析新闻（使用 Gemini）

使用方法:
    python scripts/reanalyze_news_with_gemini.py --limit 10 --dry-run
    python scripts/reanalyze_news_with_gemini.py --batch-size 10 --delay 10
"""

import asyncio
import argparse
import logging
import sys
from pathlib import Path
from datetime import datetime

# 添加项目路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from simple_trade.database.core.db_manager import DatabaseManager
from simple_trade.database.queries.news_queries import NewsQueries
from simple_trade.services.news.gemini_analyzer import GeminiNewsAnalyzer
from simple_trade.config.config import ConfigManager

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def reanalyze_news_batch(
    news_list,
    gemini_analyzer,
    news_queries,
    batch_size=10,
    delay=10.0,
    dry_run=False
):
    """批量重新分析新闻"""
    total = len(news_list)
    success_count = 0
    failed_count = 0
    failed_ids = []

    print(f"\n{'=' * 80}")
    print(f"批量重新分析新闻（使用 Gemini）")
    print(f"{'=' * 80}")
    print(f"总新闻数: {total} 条")
    print(f"批次大小: {batch_size} 条/批")
    print(f"请求间隔: {delay} 秒")
    print(f"模式: {'试运行（不更新数据库）' if dry_run else '正式运行'}")
    print(f"{'=' * 80}\n")

    for i, news in enumerate(news_list, 1):
        try:
            print(f"[{i}/{total}] 分析中: {news['title'][:40]}...")

            # 调用 Gemini 分析
            analysis = await gemini_analyzer.analyze(news['title'], news['summary'] or '')

            if not analysis:
                raise Exception("Gemini 分析返回空结果")

            print(f"  ✓ 情感: {analysis.sentiment}, 分数: {analysis.sentiment_score:.2f}")
            print(f"    相关股票: {len(analysis.related_stocks)} 个")
            print(f"    相关板块: {len(analysis.related_plates)} 个")

            # 如果不是试运行，更新数据库
            if not dry_run:
                # 更新新闻表
                news_queries.update_news_analysis(
                    news['id'],
                    analysis.sentiment,
                    analysis.sentiment_score
                )

                # 删除旧关联
                news_queries.delete_news_stocks(news['id'])
                news_queries.delete_news_plates(news['id'])

                # 创建新关联
                for stock in analysis.related_stocks:
                    news_queries.save_news_stock(news['id'], stock)

                for plate in analysis.related_plates:
                    news_queries.save_news_plate(news['id'], plate)

            success_count += 1

            # 批次间延迟
            if i % batch_size == 0 and i < total:
                print(f"\n批次完成，等待 {delay} 秒...\n")
                await asyncio.sleep(delay)

        except Exception as e:
            print(f"  ✗ 失败: {str(e)}")
            failed_count += 1
            failed_ids.append(news['id'])
            continue

    # 打印总结
    print(f"\n{'=' * 80}")
    print(f"分析完成")
    print(f"{'=' * 80}")
    print(f"总计: {total} 条")
    print(f"成功: {success_count} 条")
    print(f"失败: {failed_count} 条")
    if failed_ids:
        print(f"失败ID: {failed_ids}")
    print(f"{'=' * 80}\n")

    return {
        'total': total,
        'success': success_count,
        'failed': failed_count,
        'failed_ids': failed_ids
    }


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='批量重新分析新闻（使用 Gemini）')
    parser.add_argument('--limit', type=int, default=None, help='限制处理数量（用于测试）')
    parser.add_argument('--batch-size', type=int, default=10, help='批次大小（默认10）')
    parser.add_argument('--delay', type=float, default=10.0, help='请求间隔（秒，默认10）')
    parser.add_argument('--dry-run', action='store_true', help='试运行模式（不更新数据库）')

    args = parser.parse_args()

    # 加载配置
    config_manager = ConfigManager()
    config = config_manager.load_config()

    # 检查 Gemini 配置
    gemini_config = config.gemini
    if not gemini_config or not gemini_config.get('enabled'):
        print("错误: Gemini 未启用，请在 config.json 中启用")
        return

    # 初始化数据库
    db_manager = DatabaseManager(config.database_path)
    db_manager.init_database()
    news_queries = NewsQueries(db_manager)

    # 初始化 Gemini 分析器
    gemini_analyzer = GeminiNewsAnalyzer(
        api_key=gemini_config['api_key'],
        model=gemini_config.get('model', 'gemini-2.0-flash-exp'),
        timeout=gemini_config.get('timeout', 30)
    )

    if not gemini_analyzer.is_available():
        print("错误: Gemini 分析器不可用")
        return

    # 获取所有新闻
    print("正在加载新闻...")
    news_list = news_queries.get_all_news_for_reanalysis(limit=args.limit)
    print(f"加载完成，共 {len(news_list)} 条新闻\n")

    if not news_list:
        print("没有需要分析的新闻")
        return

    # 执行批量分析
    result = await reanalyze_news_batch(
        news_list,
        gemini_analyzer,
        news_queries,
        batch_size=args.batch_size,
        delay=args.delay,
        dry_run=args.dry_run
    )

    return result


if __name__ == "__main__":
    asyncio.run(main())
