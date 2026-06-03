"""信号数据分布和胜率统计"""
import sqlite3
DB = "simple_trade/data/trade.db"
conn = sqlite3.connect(DB)
c = conn.cursor()

print("=== sniper_signals 日期分布 ===")
c.execute("SELECT trade_date, COUNT(*) FROM sniper_signals GROUP BY trade_date ORDER BY trade_date DESC LIMIT 10")
for r in c.fetchall(): print(f"  {r[0]}: {r[1]}条")

print("\n=== kline_data 最新记录 ===")
c.execute("SELECT MAX(time_key), MIN(time_key), COUNT(DISTINCT stock_code) FROM kline_data")
r = c.fetchone()
print(f"  最新={r[0]} 最早={r[1]} 股票数={r[2]}")

print("\n=== trade_signals 日期分布 ===")
c.execute("SELECT substr(created_at,1,10) as d, COUNT(*) FROM trade_signals GROUP BY d ORDER BY d DESC LIMIT 10")
for r in c.fetchall(): print(f"  {r[0]}: {r[1]}条")

print("\n=== signal_performance 状态 ===")
c.execute("SELECT tracking_status, COUNT(*) FROM signal_performance GROUP BY 1")
for r in c.fetchall(): print(f"  {r[0]}: {r[1]}条")

print("\n=== signal_performance 日期分布(近10天) ===")
c.execute("""SELECT substr(created_at,1,10) as d, COUNT(*), 
    SUM(CASE WHEN tracking_status='completed' THEN 1 ELSE 0 END) as comp
    FROM signal_performance GROUP BY d ORDER BY d DESC LIMIT 10""")
for r in c.fetchall(): print(f"  {r[0]}: {r[1]}条 (completed={r[2]})")

print("\n=== BUY信号D3胜率(按策略,近14天completed) ===")
c.execute("""
    SELECT strategy_id, COUNT(*) as total,
           SUM(CASE WHEN day3_max_rise > 2 THEN 1 ELSE 0 END) as win,
           ROUND(AVG(day3_max_rise), 2) as avg_rise,
           ROUND(AVG(day3_max_drop), 2) as avg_drop
    FROM signal_performance
    WHERE signal_type='BUY' AND tracking_status='completed'
    AND created_at >= datetime('now', '-14 days')
    GROUP BY strategy_id ORDER BY total DESC
""")
for r in c.fetchall():
    pct = r[2]/r[1]*100 if r[1]>0 else 0
    print(f"  {r[0]}: {r[2]}/{r[1]}={pct:.0f}% avg_rise={r[3]}% avg_drop={r[4]}%")

# 抽样看一些BUY信号的后续表现（最近已完成的）
print("\n=== 近期BUY信号已完成追踪样本(D1涨>5%) ===")
c.execute("""
    SELECT stock_code, signal_price, strategy_id, 
           day1_max_rise, day1_max_drop, day3_max_rise, day3_max_drop,
           day5_max_rise, day5_max_drop, created_at
    FROM signal_performance
    WHERE signal_type='BUY' AND tracking_status='completed'
    AND day1_max_rise > 5
    AND created_at >= datetime('now', '-7 days')
    ORDER BY day1_max_rise DESC LIMIT 15
""")
for r in c.fetchall():
    print(f"  {r[0]} @{r[1]:.2f} strat={r[2]} "
          f"D1[+{r[3]:.1f}%/{r[4]:.1f}%] D3[+{r[5]:.1f}%/{r[6]:.1f}%] "
          f"D5[+{r[7]:.1f}%/{r[8]:.1f}%] {r[9][:10]}")

# 看看亏损信号（BUY但D3跌超5%）
print("\n=== 近期BUY信号失败样本(D3跌>5%) ===")
c.execute("""
    SELECT stock_code, signal_price, strategy_id, 
           day1_max_rise, day1_max_drop, day3_max_rise, day3_max_drop, created_at
    FROM signal_performance
    WHERE signal_type='BUY' AND tracking_status='completed'
    AND day3_max_drop < -5
    AND created_at >= datetime('now', '-7 days')
    ORDER BY day3_max_drop ASC LIMIT 15
""")
for r in c.fetchall():
    print(f"  {r[0]} @{r[1]:.2f} strat={r[2]} "
          f"D1[+{r[3]:.1f}%/{r[4]:.1f}%] D3[+{r[5]:.1f}%/{r[6]:.1f}%] {r[7][:10]}")

conn.close()
