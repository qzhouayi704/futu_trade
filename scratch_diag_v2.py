#!/usr/bin/env python3
"""诊断: 1) HK.02587价格走势 2) 每日top gainers是否被预警"""
import sqlite3
db = sqlite3.connect('/opt/futu_trade_sys/simple_trade/data/trade.db')

# === 诊断1: HK.02587 05-19 价格走势 ===
print("="*80)
print("诊断1: HK.02587 2026-05-19 分钟价格走势")
print("="*80)
rows = db.execute("""
    SELECT substr(datetime(timestamp/1000,'unixepoch','+8 hours'),12,5) as minute,
           AVG(price) as avg_price, MIN(price) as low, MAX(price) as high
    FROM ticker_data WHERE stock_code='HK.02587' AND trade_date='2026-05-19' AND price>0
    GROUP BY minute ORDER BY minute
""").fetchall()
entry = 4.077  # 实际买入价
for m, ap, lo, hi in rows:
    chg = (float(ap)/entry - 1)*100
    chg_hi = (float(hi)/entry - 1)*100
    bar = '█' * max(0, int(chg))
    print(f"  {m}  avg=${float(ap):.3f}  hi=${float(hi):.3f}  从买入:{chg:+.1f}%  最高:{chg_hi:+.1f}%  {bar}")

# === 诊断2: 每日top gainers覆盖率 ===
print("\n" + "="*80)
print("诊断2: 每日涨幅TOP10股票 vs 信号覆盖")
print("="*80)
dates = [r[0] for r in db.execute("SELECT DISTINCT trade_date FROM ticker_data ORDER BY trade_date").fetchall()]
for td in dates:
    # 计算每只股票的日涨幅
    stocks = db.execute("""
        SELECT stock_code, 
               MIN(CASE WHEN substr(datetime(timestamp/1000,'unixepoch','+8 hours'),12,5) <= '09:40' THEN price END) as open_price,
               MAX(price) as day_high
        FROM ticker_data 
        WHERE trade_date=? AND price>0
        GROUP BY stock_code
        HAVING open_price > 0
    """, (td,)).fetchall()
    gainers = []
    for code, op, hi in stocks:
        pct = (float(hi)/float(op) - 1)*100
        if pct > 5:  # 只看涨幅>5%的
            gainers.append((code, round(pct,1), float(op), float(hi)))
    gainers.sort(key=lambda x:-x[1])
    if not gainers:
        continue
    print(f"\n  📅 {td}  涨幅>5% 的股票 ({len(gainers)}只):")
    for code, pct, op, hi in gainers[:10]:
        # 检查该股是否有mega_buy信号数据
        cnt = db.execute("SELECT COUNT(*) FROM ticker_data WHERE stock_code=? AND trade_date=?", (code, td)).fetchone()[0]
        buy_tv = db.execute("SELECT SUM(turnover) FROM ticker_data WHERE stock_code=? AND trade_date=? AND direction='BUY'", (code, td)).fetchone()[0] or 0
        sell_tv = db.execute("SELECT SUM(turnover) FROM ticker_data WHERE stock_code=? AND trade_date=? AND direction='SELL'", (code, td)).fetchone()[0] or 0
        net_wan = round((buy_tv - sell_tv)/10000)
        tv_wan = round((buy_tv + sell_tv)/10000)
        has_data = "有数据" if cnt > 50 else f"仅{cnt}条"
        print(f"    {code:<12}  涨幅:{pct:+.1f}%  开${op:.2f}→高${hi:.2f}  净流{net_wan:+d}万  成交{tv_wan}万  [{has_data}]")

db.close()
