#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重新分析已有新闻 - 调用系统 NewsService.reanalyze_news 接口
支持批量 Gemini 分析（多条新闻一次 API 请求）

用法:
    python scripts/reanalyze_news.py [limit] [batch_size]
    limit: 最大处理数量，默认 50
    batch_size: 每批发送给 Gemini 的新闻数量，默认 10
"""

import os
import sys
import asyncio
import logging

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.config.config import ConfigManager
from simple_trade.database.core.db_manager import DatabaseManager
from simple_trade.services.news.news_service import NewsService
from dataclasses import asdict


async def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    batch_size = int(sys.argv[2]) if len(sys.argv) > 2 else 50

    config = ConfigManager.load_config("simple_trade/config.json")
    config_dict = asdict(config)

    gemini = config_dict.get('gemini', {})
    print(f"Gemini: enabled={gemini.get('enabled')}, "
          f"model={gemini.get('model')}, "
          f"api_key={'已设置' if gemini.get('api_key') else '未设置'}")

    db = DatabaseManager(config_dict.get('database_path', 'simple_trade/data/trade.db'))
    service = NewsService(db, config=config_dict)

    print(f"Gemini 分析器: {'已就绪' if service.analyzer.gemini_analyzer else '未初始化'}")
    print(f"开始重新分析，limit={limit}, batch_size={batch_size}\n")

    result = await service.reanalyze_news(limit, batch_size)

    print(f"\n结果: {result}")
    if result.get('errors'):
        print(f"错误({len(result['errors'])}条):")
        for e in result['errors'][:10]:
            print(f"  {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    asyncio.run(main())
