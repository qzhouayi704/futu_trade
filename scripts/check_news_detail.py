#!/usr/bin/env python3
"""检查指定新闻的关联数据详情"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.database.core.db_manager import DatabaseManager

db = DatabaseManager('simple_trade/data/trade.db')

# 今天抓取但无关联数据的新闻 ID
ids = [305,306,308,315,316,317,318,319,321,322,323,324,327,328,330,332,334,336,337,339,340,341,343]

for i in ids:
    stocks = db.execute_query("SELECT COUNT(1) FROM news_stocks WHERE news_id=?", (i,))[0][0]
    plates = db.execute_query("SELECT COUNT(1) FROM news_plates WHERE news_id=?", (i,))[0][0]
    sent = db.execute_query("SELECT sentiment, sentiment_score FROM news WHERE id=?", (i,))[0]
    print(f"id={i:3d}  stocks={stocks}  plates={plates}  sentiment={sent[0]:8s}  score={sent[1]:+.2f}")
