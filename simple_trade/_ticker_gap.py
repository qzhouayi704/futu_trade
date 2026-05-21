#!/usr/bin/env python3
"""诊断ticker数据空洞"""
import sqlite3
from datetime import datetime

DB = '/data/futu_trade_data/trade.db'
c = sqlite3.connect(DB)

print("=== 今日Ticker数据分布 ===")
rows = c.execute("""
    SELECT stock_code, COUNT(*) as cnt,
           MIN(timestamp) as first_ts,
           MAX(timestamp) as last_ts
    FROM ticker_data
    WHERE trade_date = '2026-05-21'
    GROUP BY stock_code
    ORDER BY cnt DESC
    LIMIT 20
""").fetchall()

for r in rows:
    first_t = datetime.fromtimestamp(r[2]/1000).strftime('%H:%M') if r[2] else '?'
    last_t = datetime.fromtimestamp(r[3]/1000).strftime('%H:%M') if r[3] else '?'
    print(f"  {r[0]}: {r[1]}条 ({first_t}~{last_t})")

print(f"\n共 {len(rows)} 只股票有ticker数据")

# 检查数据空洞模式
print("\n=== 数据空洞分析(HK.00981) ===")
rows981 = c.execute("""
    SELECT timestamp, COUNT(*) as cnt
    FROM ticker_data
    WHERE stock_code='HK.00981' AND trade_date='2026-05-21'
    GROUP BY timestamp / 60000
    ORDER BY timestamp
""").fetchall()

if rows981:
    prev_min = None
    gaps = []
    for r in rows981:
        curr_min = r[0] // 60000
        if prev_min and curr_min - prev_min > 2:
            gap_start = datetime.fromtimestamp(prev_min * 60).strftime('%H:%M')
            gap_end = datetime.fromtimestamp(curr_min * 60).strftime('%H:%M')
            gap_mins = curr_min - prev_min
            gaps.append((gap_start, gap_end, gap_mins))
        prev_min = curr_min

    if gaps:
        for gs, ge, gm in gaps:
            print(f"  空洞: {gs} → {ge} ({gm}分钟)")
    else:
        print("  无空洞")
else:
    print("  无数据")
