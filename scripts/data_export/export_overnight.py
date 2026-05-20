import sqlite3
import json

db_path = r"d:\Program Files\futu_trade_sys\simple_trade\data\trade.db"
conn = sqlite3.connect(db_path)
cur = conn.cursor()
try:
    cur.execute("SELECT * FROM overnight_screen_results ORDER BY created_at DESC LIMIT 5")
    rows = cur.fetchall()
    cols = [description[0] for description in cur.description]
    data = [dict(zip(cols, row)) for row in rows]
    with open(r"d:\Program Files\futu_trade_sys\overnight_export.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print(f"Exported {len(data)} rows.")
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
