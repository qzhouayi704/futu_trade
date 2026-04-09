#!/usr/bin/env python3
"""检查今天抓取的新闻是否已被分析"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.database.core.db_manager import DatabaseManager

db = DatabaseManager('simple_trade/data/trade.db')

today_news = db.execute_query("""
    SELECT id, title, publish_time, sentiment, sentiment_score, created_at
    FROM news
    WHERE date(created_at) = date('now', 'localtime')
    ORDER BY id DESC
""")
print(f"今天抓取的新闻（按 created_at）: {len(today_news)} 条\n")
for n in today_news:
    print(f"  id={n[0]}  sentiment={n[3]:8s}  score={n[4]:+.2f}  created={n[5]}  | {n[1][:40]}")

if not today_news:
    recent = db.execute_query("SELECT created_at FROM news ORDER BY created_at DESC LIMIT 5")
    print("\n最近 created_at:")
    for r in recent:
        print(f"  {r[0]}")
    sys.exit(0)

ids = [n[0] for n in today_news]
ids_str = ','.join(str(i) for i in ids)

stocks_count = db.execute_query(f'SELECT COUNT(*) FROM news_stocks WHERE news_id IN ({ids_str})')[0][0]
plates_count = db.execute_query(f'SELECT COUNT(*) FROM news_plates WHERE news_id IN ({ids_str})')[0][0]
print(f"\n今天新闻关联数据: stocks={stocks_count}, plates={plates_count}")

# 无关联数据的
no_data = db.execute_query(f"""
    SELECT n.id, n.title FROM news n
    WHERE n.id IN ({ids_str})
      AND NOT EXISTS (SELECT 1 FROM news_stocks ns WHERE ns.news_id = n.id)
      AND NOT EXISTS (SELECT 1 FROM news_plates np WHERE np.news_id = n.id)
""")
print(f"今天无关联数据的新闻: {len(no_data)} 条")
for n in no_data:
    print(f"  id={n[0]} | {n[1][:60]}")
