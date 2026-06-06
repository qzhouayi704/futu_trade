import sqlite3
c = sqlite3.connect('/opt/futu_trade_sys/simple_trade/data/trade.db')

# 主库ticker_data范围
cnt = c.execute("SELECT COUNT(*) FROM ticker_data").fetchone()[0]
print(f"主库 ticker_data: {cnt}条")

# 按天统计
rows = c.execute("""
    SELECT trade_date, COUNT(*), COUNT(DISTINCT stock_code) 
    FROM ticker_data 
    GROUP BY trade_date ORDER BY trade_date
""").fetchall()
print(f"\n{'日期':<12} {'条数':>8} {'股票数':>6}")
for r in rows:
    print(f"{r[0]:<12} {r[1]:>8} {r[2]:>6}")

c.close()
