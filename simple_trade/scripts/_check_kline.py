import sqlite3

conn = sqlite3.connect(r'd:\Program Files\futu_trade_sys\simple_trade\data\trade.db')

# 1. 查找近30天涨幅>5%的股票，统计换手率和涨幅分布
print("=== 近30天涨幅>5%的股票分布 ===")
rows = conn.execute("""
    SELECT stock_code, time_key, 
           round((close_price - open_price) / open_price * 100, 1) as chg_pct,
           round(turnover_rate, 2) as tr,
           volume
    FROM kline_data 
    WHERE time_key >= '2026-04-05'
      AND close_price > open_price
      AND (close_price - open_price) / open_price > 0.05
      AND turnover_rate IS NOT NULL
    ORDER BY chg_pct DESC
    LIMIT 100
""").fetchall()

# 分段统计
ranges = {'5-8%': [], '8-10%': [], '10-15%': [], '15-20%': [], '20%+': []}
for r in rows:
    chg = r[2]
    tr = r[3]
    entry = (r[0], r[1][:10], chg, tr)
    if chg >= 20: ranges['20%+'].append(entry)
    elif chg >= 15: ranges['15-20%'].append(entry)
    elif chg >= 10: ranges['10-15%'].append(entry)
    elif chg >= 8: ranges['8-10%'].append(entry)
    else: ranges['5-8%'].append(entry)

for rng, items in ranges.items():
    if items:
        trs = [i[3] for i in items]
        avg_tr = sum(trs) / len(trs) if trs else 0
        print(f"\n涨幅 {rng}: {len(items)} 只, 平均换手率={avg_tr:.2f}%")
        for i in items[:5]:
            print(f"  {i[0]} {i[1]} 涨{i[2]}% 换手率={i[3]}%")

# 2. 日均换手率分布（了解正常值）
print("\n\n=== 日均换手率分布 ===")
tr_dist = conn.execute("""
    SELECT 
        CASE 
            WHEN turnover_rate < 0.5 THEN '<0.5%'
            WHEN turnover_rate < 1 THEN '0.5-1%'
            WHEN turnover_rate < 2 THEN '1-2%'
            WHEN turnover_rate < 3 THEN '2-3%'
            WHEN turnover_rate < 5 THEN '3-5%'
            ELSE '5%+'
        END as tr_range,
        count(*) as cnt
    FROM kline_data
    WHERE time_key >= '2026-04-05' AND turnover_rate IS NOT NULL
    GROUP BY tr_range
    ORDER BY min(turnover_rate)
""").fetchall()
for r in tr_dist:
    print(f"  换手率 {r[0]}: {r[1]} 条")

conn.close()
