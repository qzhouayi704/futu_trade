import sqlite3, statistics

DB = r'd:\Program Files\futu_trade_sys\simple_trade\data\trade.db'
conn = sqlite3.connect(DB)
c = conn.cursor()
CODE = 'HK.02701'

# 1. 股票基本信息
print(f'=== {CODE} 基本信息 ===')
c.execute("SELECT code, name, market FROM stocks WHERE code = ?", (CODE,))
r = c.fetchone()
if r: print(f'{r[0]} | {r[1]} | {r[2]}')

# 2. K线数据（最近30天）
print(f'\n=== K线数据（最近30天）===')
c.execute(
    "SELECT time_key, open_price, high_price, low_price, close_price, volume "
    "FROM kline_data WHERE stock_code = ? ORDER BY time_key DESC LIMIT 30", (CODE,)
)
rows = c.fetchall()
if not rows:
    print('无K线数据')
else:
    rows.reverse()
    print(f"{'日期':>12} {'开盘':>8} {'最高':>8} {'最低':>8} {'收盘':>8} {'成交量':>12} {'涨跌幅':>8}")
    for i, r in enumerate(rows):
        d, o, h, l, cl, v = r
        chg = (cl - rows[i-1][4]) / rows[i-1][4] * 100 if i > 0 and rows[i-1][4] > 0 else 0
        print(f"{d[:10]:>12} {o:>8.3f} {h:>8.3f} {l:>8.3f} {cl:>8.3f} {v:>12,} {chg:>7.2f}%")

    closes = [r[4] for r in rows]
    volumes = [r[5] for r in rows]
    opens = [r[1] for r in rows]
    highs = [r[2] for r in rows]
    lows = [r[3] for r in rows]

    # 技术指标
    print('\n=== 技术指标 ===')
    ma5 = sum(closes[-5:]) / 5
    ma10 = sum(closes[-10:]) / 10
    ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
    print(f"当前价: {closes[-1]:.3f}")
    print(f"MA5: {ma5:.3f} ({'上穿' if closes[-1] > ma5 else '下穿'})")
    print(f"MA10: {ma10:.3f} ({'上穿' if closes[-1] > ma10 else '下穿'})")
    if ma20: print(f"MA20: {ma20:.3f} ({'上穿' if closes[-1] > ma20 else '下穿'})")

    avg_vol_5 = sum(volumes[-6:-1]) / 5 if len(volumes) >= 6 else sum(volumes[:-1]) / max(1, len(volumes)-1)
    vol_ratio = volumes[-1] / avg_vol_5 if avg_vol_5 > 0 else 0
    print(f"最新量: {volumes[-1]:,} | 5日均量: {avg_vol_5:,.0f} | 量比: {vol_ratio:.2f}")

    h20 = max(highs[-20:]) if len(highs) >= 20 else max(highs)
    l20 = min(lows[-20:]) if len(lows) >= 20 else min(lows)
    pos = (closes[-1] - l20) / (h20 - l20) if h20 > l20 else 0.5
    print(f"20日位置: {pos:.2f} | 20日高: {h20:.3f} | 20日低: {l20:.3f}")

    # 涨跌幅
    if len(closes) >= 6: print(f"5日涨跌: {(closes[-1]-closes[-6])/closes[-6]*100:.2f}%")
    if len(closes) >= 11: print(f"10日涨跌: {(closes[-1]-closes[-11])/closes[-11]*100:.2f}%")
    if len(closes) >= 21: print(f"20日涨跌: {(closes[-1]-closes[-21])/closes[-21]*100:.2f}%")

    peak = max(closes[-20:]) if len(closes) >= 20 else max(closes)
    print(f"距高点回撤: {(peak-closes[-1])/peak*100:.2f}%")

    # 均线乖离
    if ma20: print(f"均线乖离率(MA20): {(closes[-1]-ma20)/ma20*100:.2f}%")

    # 连阳连阴
    consec, direction = 0, None
    for i in range(len(closes)-1, max(len(closes)-8, 0), -1):
        d = 'up' if closes[i] > opens[i] else 'down'
        if direction is None: direction = d
        if d == direction: consec += 1
        else: break
    print(f"连续{direction}: {consec}天")

    # K线形态
    body = abs(closes[-1] - opens[-1])
    us = highs[-1] - max(closes[-1], opens[-1])
    ls = min(closes[-1], opens[-1]) - lows[-1]
    tr = highs[-1] - lows[-1] if highs[-1] > lows[-1] else 0.001
    print(f"最后K线: {'阳' if closes[-1]>opens[-1] else '阴'} | 实体{body:.4f} | 上影{us:.4f}({us/tr*100:.0f}%) | 下影{ls:.4f}({ls/tr*100:.0f}%)")

    # ATR
    tr_list = []
    for i in range(max(1, len(rows)-14), len(rows)):
        t = max(rows[i][2]-rows[i][3], abs(rows[i][2]-rows[i-1][4]), abs(rows[i][3]-rows[i-1][4]))
        tr_list.append(t)
    atr = sum(tr_list)/len(tr_list) if tr_list else 0
    print(f"ATR(14): {atr:.4f} ({atr/closes[-1]*100:.2f}%)")
    print(f"预计波动区间: {closes[-1]-atr:.3f} ~ {closes[-1]+atr:.3f}")

    # 支撑阻力
    sl = sorted(lows[-10:])[:3]
    support = statistics.median(sl) if len(sl) >= 3 else min(sl)
    rh = sorted(highs[-10:], reverse=True)[:3]
    resist = statistics.median(rh) if len(rh) >= 3 else max(rh)
    print(f"支撑位: {support:.3f} | 阻力位: {resist:.3f}")

# 3. 资金流
print(f'\n=== 资金流（近10天）===')
c.execute("SELECT date, net_inflow FROM capital_flow_daily WHERE stock_code = ? ORDER BY date DESC LIMIT 10", (CODE,))
cap_rows = c.fetchall()
if cap_rows:
    for r in reversed(cap_rows):
        flag = '🟢' if r[1] and r[1] > 0 else '🔴'
        print(f"  {r[0][:10]} | {flag} {r[1]:>12,.0f}")
    cont = 0
    for r in cap_rows:
        if r[1] and r[1] > 0: cont += 1
        else: break
    print(f"连续净流入天数: {cont}")
else:
    print('无资金流数据')

# 4. 资金评分缓存
print(f'\n=== 资金评分（最新）===')
c.execute(
    "SELECT timestamp, capital_score, net_inflow_ratio, big_order_buy_ratio, main_net_inflow "
    "FROM capital_flow_cache WHERE stock_code = ? ORDER BY timestamp DESC LIMIT 1", (CODE,)
)
cache = c.fetchone()
if cache:
    print(f"时间: {cache[0]}")
    print(f"资金评分: {cache[1]:.1f} | 净流入比: {cache[2]:.4f} | 大单买入比: {cache[3]:.4f} | 主力净流入: {cache[4]:,.0f}")

# 5. daily_active_stocks
print(f'\n=== 活跃度记录 ===')
c.execute(
    "SELECT check_date, is_active, activity_score, turnover_rate, turnover_amount "
    "FROM daily_active_stocks WHERE stock_code = ? ORDER BY check_date DESC LIMIT 5", (CODE,)
)
for r in c.fetchall():
    print(f"  {r[0]} | 活跃:{r[1]} | 评分:{r[2]:.4f} | 换手:{r[3]:.3f}% | 成交额:{r[4]:,.0f}")

conn.close()
