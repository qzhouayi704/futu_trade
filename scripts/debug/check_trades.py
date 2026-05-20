import sqlite3

conn = sqlite3.connect(r'd:\Program Files\futu_trade_sys\simple_trade\data\trade.db')
cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
print("Tables:")
for r in cur.fetchall():
    print(f"  {r[0]}")

# Check trade_signals for BUY signals
print("\n--- trade_signals BUY count ---")
cur = conn.execute("SELECT COUNT(*) FROM trade_signals WHERE signal_type='BUY'")
print(f"BUY signals: {cur.fetchone()[0]}")

# Check trading_records
print("\n--- trading_records count ---")
cur = conn.execute("SELECT COUNT(*) FROM trading_records")
print(f"Total records: {cur.fetchone()[0]}")

# Check signal_performance
print("\n--- signal_performance count ---")
try:
    cur = conn.execute("SELECT COUNT(*) FROM signal_performance")
    print(f"Total: {cur.fetchone()[0]}")
except Exception as e:
    print(f"Error: {e}")

# Show recent BUY signals
print("\n--- Recent BUY signals (last 20) ---")
cur = conn.execute("""
    SELECT ts.id, s.code, s.name, ts.signal_price, ts.created_at, ts.strategy_name
    FROM trade_signals ts
    JOIN stocks s ON ts.stock_id = s.id
    WHERE ts.signal_type='BUY'
    ORDER BY ts.created_at DESC
    LIMIT 20
""")
for r in cur.fetchall():
    print(f"  {r[1]} {r[2]} | price={r[3]} | time={r[4]} | strategy={r[5]}")

conn.close()
