"""检查新闻 publish_time 格式"""
import sqlite3
conn = sqlite3.connect('/opt/futu_trade_sys/simple_trade/data/trade.db')
rows = conn.execute('SELECT publish_time, created_at FROM news ORDER BY id DESC LIMIT 10').fetchall()
for r in rows:
    print(f"publish_time={r[0]}  |  created_at={r[1]}")
total = conn.execute('SELECT COUNT(*) FROM news').fetchone()[0]
print(f"\n总新闻数: {total}")
conn.close()
