import sqlite3, json, sys
sys.stdout.reconfigure(encoding='utf-8')

local_db = r"d:\Program Files\futu_trade_sys\simple_trade\data\trade.db"
conn = sqlite3.connect(local_db)
cur = conn.cursor()
cur.execute("SELECT screen_date, candidates_json, total_count, created_at FROM overnight_screen_results")
rows = cur.fetchall()
conn.close()

# Write as compact JSON for transfer
data = []
for r in rows:
    data.append({"d": r[0], "j": r[1], "c": r[2], "t": r[3]})

with open(r"d:\Program Files\futu_trade_sys\overnight_data.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False)

print(f"Exported {len(data)} rows")
