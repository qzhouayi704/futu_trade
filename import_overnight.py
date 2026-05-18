import sqlite3, json

DB = "/opt/futu_trade_sys/simple_trade/data/trade.db"
DATA = "/tmp/overnight_data.json"

conn = sqlite3.connect(DB)
cur = conn.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS overnight_screen_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    screen_date TEXT UNIQUE,
    candidates_json TEXT,
    total_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""")

with open(DATA, "r", encoding="utf-8") as f:
    rows = json.load(f)

for r in rows:
    cur.execute(
        "INSERT OR REPLACE INTO overnight_screen_results (screen_date, candidates_json, total_count, created_at) VALUES (?, ?, ?, ?)",
        (r["d"], r["j"], r["c"], r["t"])
    )

conn.commit()
conn.close()
print(f"Imported {len(rows)} rows OK")
