import sqlite3
from collections import defaultdict
c = sqlite3.connect('simple_trade/data/trade.db')

# 1. sniper_signals 每日统计
print("=== Sniper信号每日分布 ===")
for r in c.execute("""SELECT trade_date, signal_type, COUNT(*), COUNT(DISTINCT stock_code)
    FROM sniper_signals GROUP BY trade_date, signal_type ORDER BY trade_date, signal_type""").fetchall():
    print(f"  {r[0]} | {r[1]:>15} | {r[2]:>3}条 | {r[3]:>3}只股票")

# 2. 买入信号共振: 同一天同一股有mega_buy + accel_in
print("\n=== 买入信号共振(mega_buy + accel_in 同日同股) ===")
resonance = c.execute("""
    SELECT a.trade_date, a.stock_code, a.stock_name, 
           GROUP_CONCAT(DISTINCT a.signal_type) as types,
           COUNT(*) as total_sigs
    FROM sniper_signals a
    WHERE a.signal_type IN ('mega_buy','accel_in')
    GROUP BY a.trade_date, a.stock_code
    HAVING COUNT(DISTINCT signal_type) >= 2
    ORDER BY a.trade_date, total_sigs DESC
""").fetchall()
print(f"  共 {len(resonance)} 组共振信号")
for r in resonance:
    print(f"  {r[0]} | {r[2]:>10} | {r[3]} | {r[4]}条")

# 3. 这些共振股票次日表现如何？
print("\n=== 共振股票次日表现(kline) ===")
print(f"{'日期':>12} {'股票':>10} {'当日涨跌':>8} {'次日涨跌':>8} {'次日最高':>8} {'次日最低':>8}")
print("-"*65)
wins = losses = 0; total_ret = 0
for r in resonance:
    td = r[0]; code = r[1]; name = r[2]
    # 查kline次日表现
    klines = c.execute("""SELECT substr(time_key,1,10) as d, open_price, close_price, high_price, low_price
        FROM kline_data WHERE stock_code=? AND time_key>=? ORDER BY time_key LIMIT 3""", (code, td)).fetchall()
    if len(klines) < 2: continue
    today_close = float(klines[0][2])
    next_open = float(klines[1][1]); next_close = float(klines[1][2])
    next_high = float(klines[1][3]); next_low = float(klines[1][4])
    if today_close <= 0: continue
    next_ret = (next_close - today_close)/today_close*100
    next_max_gain = (next_high - today_close)/today_close*100
    next_max_loss = (next_low - today_close)/today_close*100
    today_chg = (today_close - float(klines[0][1]))/float(klines[0][1])*100 if float(klines[0][1])>0 else 0
    flag = "✅" if next_ret>0 else "❌"
    print(f"  {td} {name:>8} {today_chg:>+7.1f}% {flag}{next_ret:>+7.1f}% {next_max_gain:>+7.1f}% {next_max_loss:>+7.1f}%")
    if next_ret > 0: wins += 1
    else: losses += 1
    total_ret += next_ret

n = wins + losses
if n > 0:
    print(f"\n📈 共振总体: {wins}胜{losses}负 | 胜率{wins/n*100:.1f}% | 平均{total_ret/n:+.2f}%")

# 4. 对比: 单一mega_buy / accel_in 次日表现
print("\n=== 单一信号次日表现 ===")
for stype in ['mega_buy', 'accel_in', 'mega_sell']:
    sigs = c.execute("""SELECT s.trade_date, s.stock_code FROM sniper_signals s 
        WHERE s.signal_type=? GROUP BY s.trade_date, s.stock_code""", (stype,)).fetchall()
    rets = []
    for td, code in sigs:
        klines = c.execute("""SELECT open_price, close_price, high_price, low_price
            FROM kline_data WHERE stock_code=? AND time_key>? ORDER BY time_key LIMIT 1""", (code, td)).fetchall()
        if not klines: continue
        today = c.execute("SELECT close_price FROM kline_data WHERE stock_code=? AND substr(time_key,1,10)=?", (code, td)).fetchone()
        if not today: continue
        tc = float(today[0])
        if tc<=0: continue
        nc = float(klines[0][1])
        rets.append((nc-tc)/tc*100)
    if rets:
        w = sum(1 for r in rets if r>0)
        print(f"  {stype:>15}: {len(rets)}条 | 胜率{w/len(rets)*100:.1f}% | 平均{sum(rets)/len(rets):+.2f}%")

c.close()
