#!/usr/bin/env python3
"""临时脚本：查询今日交易记录"""
import sqlite3, json
from datetime import date

db = sqlite3.connect("/opt/futu_trade_sys/simple_trade/data/trade.db")
db.row_factory = sqlite3.Row

# 1. 查看所有表
tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("=== TABLES ===")
print(tables)

# 2. 查找可能的交易记录表
for t in tables:
    if any(k in t.lower() for k in ['trade', 'deal', 'order', 'execution', 'history', 'signal']):
        cols = [r[1] for r in db.execute(f"PRAGMA table_info({t})").fetchall()]
        count = db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"\n=== {t} ({count} rows) ===")
        print(f"Columns: {cols}")
        # 查今天的记录
        today = date.today().isoformat()
        for col in cols:
            if any(k in col.lower() for k in ['date', 'time', 'created', 'timestamp']):
                try:
                    rows = db.execute(f"SELECT * FROM {t} WHERE {col} >= ? ORDER BY {col} DESC LIMIT 20", (today,)).fetchall()
                    if rows:
                        print(f"Today records ({col} >= {today}): {len(rows)}")
                        for r in rows:
                            print(dict(r))
                except:
                    pass
                break

db.close()
