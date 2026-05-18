import sqlite3, json

db = r"d:\Program Files\futu_trade_sys\simple_trade\data\trade.db"
conn = sqlite3.connect(db)
cur = conn.cursor()

# 导出 overnight_screen_results
cur.execute("SELECT screen_date, candidates_json, total_count, created_at FROM overnight_screen_results")
rows = cur.fetchall()
conn.close()

# 生成 SQL 插入语句
lines = []
lines.append("CREATE TABLE IF NOT EXISTS overnight_screen_results (id INTEGER PRIMARY KEY AUTOINCREMENT, screen_date TEXT UNIQUE, candidates_json TEXT, total_count INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);")
for row in rows:
    screen_date, candidates_json, total_count, created_at = row
    # Escape single quotes in JSON
    safe_json = candidates_json.replace("'", "''") if candidates_json else ""
    safe_created = (created_at or "").replace("'", "''")
    lines.append(f"INSERT OR REPLACE INTO overnight_screen_results (screen_date, candidates_json, total_count, created_at) VALUES ('{screen_date}', '{safe_json}', {total_count or 0}, '{safe_created}');")

with open(r"d:\Program Files\futu_trade_sys\overnight_import.sql", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"Exported {len(rows)} rows to overnight_import.sql")
