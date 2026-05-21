#!/usr/bin/env python3
"""精确分析09:40~10:30的1分钟级数据"""
import sqlite3, datetime
db_path = '/data/futu_trade_data/trade.db'
conn = sqlite3.connect(db_path)
c = conn.cursor()
today = '2026-05-21'
stock = 'HK.00981'
tz8 = datetime.timezone(datetime.timedelta(hours=8))

# 先看逐笔数据的时间分布
c.execute('''SELECT
    CAST(timestamp / 60000 AS INTEGER) * 60000 as min_ts,
    COUNT(*) as ticks,
    SUM(CASE WHEN direction='BUY' THEN turnover ELSE 0 END) as buy,
    SUM(CASE WHEN direction='SELL' THEN turnover ELSE 0 END) as sell,
    SUM(CASE WHEN direction='BUY' THEN volume ELSE 0 END) as buy_v,
    SUM(CASE WHEN direction='SELL' THEN volume ELSE 0 END) as sell_v,
    AVG(price) as avg_p, MIN(price) as low_p, MAX(price) as high_p
FROM ticker_data WHERE stock_code=? AND trade_date=?
GROUP BY min_ts ORDER BY min_ts''', (stock, today))

rows = c.fetchall()
print(f"逐笔数据覆盖: {len(rows)} 个1分钟bar\n")

cum_delta = 0; peak_delta = 0; prev_bsr = None
print(f"时间  | 均价   | 范围          | BSR  | Delta    | CumΔ      | 笔数 | 信号")
print("-"*100)

for r in rows:
    ts = datetime.datetime.fromtimestamp(r[0]/1000, tz=tz8)
    time_str = ts.strftime('%H:%M')
    ticks = r[1]
    buy, sell = r[2] or 0, r[3] or 0
    buy_v, sell_v = r[4] or 0, r[5] or 0
    avg_p, low_p, high_p = r[6], r[7], r[8]
    
    bsr = min(buy/sell if sell > 0 else 9.9, 9.9)
    delta = buy_v - sell_v
    cum_delta += delta
    if cum_delta > peak_delta: peak_delta = cum_delta
    
    sigs = []
    if bsr > 1.3: sigs.append("🟢买强")
    elif bsr < 0.7: sigs.append("🔴卖强")
    if prev_bsr and prev_bsr > 1.1 and bsr < 0.85: sigs.append("⚠️衰竭")
    if peak_delta > 0 and cum_delta < peak_delta * 0.7: sigs.append("↘️Δ拐")
    
    print(f"{time_str} | {avg_p:>6.2f} | {low_p:.2f}~{high_p:.2f} | {bsr:.2f} | {delta:>+8.0f} | {cum_delta:>+9.0f} | {ticks:>4} | {' '.join(sigs)}")
    prev_bsr = bsr

# 还要检查：逐笔数据的第一条和最后一条时间
c.execute('SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM ticker_data WHERE stock_code=? AND trade_date=?', (stock, today))
r = c.fetchone()
first = datetime.datetime.fromtimestamp(r[0]/1000, tz=tz8).strftime('%H:%M:%S')
last = datetime.datetime.fromtimestamp(r[1]/1000, tz=tz8).strftime('%H:%M:%S')
print(f"\n逐笔总计: {r[2]}条, 首条={first}, 末条={last}")

# 检查是否有09:50~14:00之间的数据
c.execute('''SELECT COUNT(*) FROM ticker_data 
WHERE stock_code=? AND trade_date=?
AND timestamp > 1779328800000 AND timestamp < 1779343200000''', (stock, today))
# 09:50 CST = roughly ts > earlier bars, 14:00 = later
mid_count = c.fetchone()[0]
print(f"09:50~14:00之间的数据: {mid_count}条")

conn.close()
