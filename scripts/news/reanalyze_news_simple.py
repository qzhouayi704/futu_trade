#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量重新分析新闻（使用 Gemini）- 简化版

使用方法:
    python scripts/reanalyze_news_simple.py --limit 10 --dry-run
    python scripts/reanalyze_news_simple.py --batch-size 10 --delay 10
"""

import asyncio
import argparse
import json
import logging
import sys
import sqlite3
from pathlib import Path
from datetime import datetime

# 添加项目路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# 只导入必要的模块，避免导入整个 simple_trade 包
from simple_trade.services.news.gemini_analyzer import GeminiNewsAnalyzer

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SimpleNewsQueries:
    """简化的新闻查询类（直接使用 sqlite3）"""

    def __init__(self, db_path):
        self.db_path = db_path

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def get_all_news_for_reanalysis(self, limit=None):
        """获取所有需要重新分析的新闻"""
        conn = self.get_connection()
        cursor = conn.cursor()

        sql = '''
            SELECT id, news_id, title, summary
            FROM news
            ORDER BY publish_time DESC
        '''
        if limit:
            sql += f' LIMIT {limit}'

        cursor.execute(sql)
        rows = cursor.fetchall()
        conn.close()

        return [
            {
                'id': row[0],
                'news_id': row[1],
                'title': row[2],
                'summary': row[3]
            }
            for row in rows
        ]

    def update_news_analysis(self, news_id, sentiment, sentiment_score):
        """更新新闻分析结果"""
        conn = self.get_connection()
        cursor = conn.cursor()

        sql = '''
            UPDATE news
            SET sentiment = ?, sentiment_score = ?
            WHERE id = ?
        '''
        cursor.execute(sql, (sentiment, sentiment_score, news_id))
        conn.commit()
        conn.close()

    def delete_news_stocks(self, news_id):
        """删除新闻的股票关联"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM news_stocks WHERE news_id = ?', (news_id,))
        conn.commit()
        conn.close()

    def delete_news_plates(self, news_id):
        """删除新闻的板块关联"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM news_plates WHERE news_id = ?', (news_id,))
        conn.commit()
        conn.close()

    def save_news_stock(self, news_id, stock_data):
        """保存新闻-股票关联"""
        conn = self.get_connection()
        cursor = conn.cursor()

        sql = '''
            INSERT OR REPLACE INTO news_stocks
            (news_id, stock_code, stock_name, impact_type)
            VALUES (?, ?, ?, ?)
        '''
        cursor.execute(sql, (
            news_id,
            stock_data.get('stock_code'),
            stock_data.get('stock_name'),
            stock_data.get('impact_type')
        ))
        conn.commit()
        conn.close()

    def save_news_plate(self, news_id, plate_data):
        """保存新闻-板块关联"""
        conn = self.get_connection()
        cursor = conn.cursor()

        sql = '''
            INSERT OR REPLACE INTO news_plates
            (news_id, plate_code, plate_name, impact_type)
            VALUES (?, ?, ?, ?)
        '''
        cursor.execute(sql, (
            news_id,
            plate_data.get('plate_code'),
            plate_data.get('plate_name'),
            plate_data.get('impact_type')
        ))
        conn.commit()
        conn.close()


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
    config_path = project_root / "simple_trade" / "config.json"
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    # 检查 Gemini 配置
    gemini_config = config.get('gemini', {})
    if not gemini_config or not gemini_config.get('enabled'):
        print("错误: Gemini 未启用，请在 config.json 中启用")
        return

    # 初始化数据库（使用简化版）
    db_path = project_root / config['database_path']
    news_queries = SimpleNewsQueries(str(db_path))

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
