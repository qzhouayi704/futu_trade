import sqlite3, json

DB = "/opt/futu_trade_sys/simple_trade/data/trade.db"
conn = sqlite3.connect(DB)
cur = conn.cursor()

# First check schema
print("=== Tables ===")
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%plate%'")
for r in cur.fetchall():
    print(f"  {r[0]}")
    cur.execute(f"PRAGMA table_info({r[0]})")
    for col in cur.fetchall():
        print(f"    {col}")

# Also check stocks table
cur.execute("PRAGMA table_info(stocks)")
cols = cur.fetchall()
print("\n=== stocks columns ===")
for c in cols:
    print(f"  {c}")

# Check if there's plate data for our stocks
targets = ['HK.02565', 'HK.06651', 'HK.02661', 'HK.02701']
for code in targets:
    cur.execute("SELECT * FROM stocks WHERE code = ?", (code,))
    r = cur.fetchone()
    if r:
        col_names = [c[1] for c in cols]
        print(f"\n{code}: {dict(zip(col_names, r))}")

conn.close()
