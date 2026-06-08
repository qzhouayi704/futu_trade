import sqlite3
c = sqlite3.connect('simple_trade/data/trade.db')

print("kline日期范围:")
for r in c.execute("SELECT MIN(time_key), MAX(time_key), COUNT(*), COUNT(DISTINCT stock_code) FROM kline_data").fetchall():
    print(f"  {r[0]} ~ {r[1]}, {r[2]}行, {r[3]}只股票")

print("\nkline每日股票数:")
for r in c.execute("SELECT substr(time_key,1,10) as d, COUNT(*) FROM kline_data GROUP BY d ORDER BY d").fetchall():
    print(f"  {r[0]}: {r[1]}")

print("\n=== trade_signals 策略分布 ===")
for r in c.execute("SELECT strategy_id, signal_type, COUNT(*) FROM trade_signals GROUP BY strategy_id, signal_type ORDER BY COUNT(*) DESC").fetchall():
    print(f"  {r[0]} / {r[1]}: {r[2]}")

print("\n=== signal_performance 按策略 ===")
for r in c.execute("""SELECT strategy_id, COUNT(*) as total, 
    SUM(CASE WHEN day1_max_rise>0 THEN 1 ELSE 0 END) as has_d1,
    AVG(day1_max_rise) as avg_d1r, AVG(day1_max_drop) as avg_d1d
    FROM signal_performance WHERE signal_type='BUY'
    GROUP BY strategy_id ORDER BY total DESC LIMIT 15""").fetchall():
    print(f"  {r[0]}: {r[1]}条, D1有数据{r[2]}条, 平均涨{r[3]:.2f}% 跌{r[4]:.2f}%")

print("\n=== sniper_signals 类型分布 ===")
cols_ss = c.execute("PRAGMA table_info(sniper_signals)").fetchall()
print("  结构:", [c[1] for c in cols_ss])
for r in c.execute("SELECT signal_type, COUNT(*) FROM sniper_signals GROUP BY signal_type ORDER BY COUNT(*) DESC").fetchall():
    print(f"  {r[0]}: {r[1]}")

c.close()
