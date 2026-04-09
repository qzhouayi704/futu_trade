#!/usr/bin/env python3
"""调试 reanalyze 跳过逻辑"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.database.core.db_manager import DatabaseManager
from simple_trade.database.queries.news_queries import NewsQueries

db = DatabaseManager('simple_trade/data/trade.db')
q = NewsQueries(db)

all_news = q.get_all_news_for_reanalysis(limit=200)
print(f"总共获取: {len(all_news)} 条")

target_ids = {305,306,308,315,316,317,318,319,321,322,323,324,327,328,330,332,334,336,337,339,340,341,343}

skipped = 0
pending = 0
for news in all_news:
    nid = news['id']
    has_stocks = bool(q._get_news_stocks(nid))
    has_plates = bool(q._get_news_plates(nid))
    if has_stocks or has_plates:
        skipped += 1
        if nid in target_ids:
            stocks = q._get_news_stocks(nid)
            plates = q._get_news_plates(nid)
            print(f"  [意外跳过] id={nid} stocks={stocks} plates={plates}")
    else:
        pending += 1
        if nid in target_ids:
            print(f"  [待分析] id={nid}")

found_ids = {n['id'] for n in all_news}
missing = target_ids - found_ids
if missing:
    print(f"\n未在 limit=200 结果中的目标ID: {missing}")

print(f"\n跳过: {skipped}, 待分析: {pending}")
