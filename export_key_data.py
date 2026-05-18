import sqlite3
import json

db = r"d:\Program Files\futu_trade_sys\simple_trade\data\trade.db"
conn = sqlite3.connect(db)
cur = conn.cursor()

# List all tables
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
all_tables = [r[0] for r in cur.fetchall()]
print("All tables:", all_tables)

# Check row counts for key tables
for t in all_tables:
    try:
        cur.execute(f"SELECT COUNT(*) FROM [{t}]")
        count = cur.fetchone()[0]
        if count > 0:
            print(f"  {t}: {count} rows")
    except:
        pass

conn.close()
