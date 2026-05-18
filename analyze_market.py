import sqlite3, json

DB = "/opt/futu_trade_sys/simple_trade/data/trade.db"
conn = sqlite3.connect(DB)
cur = conn.cursor()

# 1. Find today's big movers (change >= 15%)
cur.execute("""
    SELECT k.stock_code, s.name, k.open_price, k.high_price, k.low_price, k.close_price, k.volume
    FROM kline_data k
    LEFT JOIN stocks s ON k.stock_code = s.code
    WHERE k.time_key LIKE '2026-05-18%'
    AND k.close_price > 0 AND k.open_price > 0
    ORDER BY (k.close_price - k.open_price) / k.open_price DESC
    LIMIT 30
""")
rows = cur.fetchall()

print(f"=== 5/18 涨幅前30 ===")
big_movers = []
for r in rows:
    code, name, o, h, l, c, v = r
    change = (c - o) / o * 100
    amplitude = (h - l) / l * 100 if l > 0 else 0
    if change >= 10:
        big_movers.append(code)
        print(f"{code:12s} {(name or ''):10s} O={o:.2f} H={h:.2f} L={l:.2f} C={c:.2f} chg={change:+.1f}% amp={amplitude:.0f}% vol={v:,}")

# 2. For each big mover, get last 10 days K-line and analyze
print(f"\n=== 爆发股前10日K线分析 ===")
for code in big_movers[:10]:
    cur.execute("""
        SELECT time_key, open_price, high_price, low_price, close_price, volume
        FROM kline_data WHERE stock_code = ?
        ORDER BY time_key DESC LIMIT 11
    """, (code,))
    klines = cur.fetchall()
    klines.reverse()
    
    if len(klines) < 3:
        continue
    
    # Get stock name
    cur.execute("SELECT name FROM stocks WHERE code = ?", (code,))
    nr = cur.fetchone()
    name = nr[0] if nr else code
    
    print(f"\n--- {code} {name} ---")
    
    # Calculate base volume (average of earliest 3 days)
    base_vols = [k[5] for k in klines[:3] if k[5] and k[5] > 0]
    base_vol = sum(base_vols) / len(base_vols) if base_vols else 1
    
    # Track signals
    vol_spike_days = 0      # Days with volume >= 3x base
    support_tests = {}      # Price zones tested
    contraction_before = False
    long_shadow_days = 0
    big_yang_days = 0
    
    prev_vol = None
    for i, k in enumerate(klines):
        dt, o, h, l, c, v = k
        dt_short = str(dt)[:10]
        vol_ratio = v / base_vol if base_vol > 0 else 0
        change = (c - o) / o * 100 if o > 0 else 0
        
        # Volume spike
        if vol_ratio >= 3:
            vol_spike_days += 1
        
        # Support zone (round to nearest integer)
        support_zone = round(l)
        support_tests[support_zone] = support_tests.get(support_zone, 0) + 1
        
        # Long lower shadow
        body_low = min(o, c)
        if body_low > 0 and l > 0 and (body_low - l) / body_low * 100 >= 3:
            long_shadow_days += 1
        
        # Big yang line
        if change >= 5:
            big_yang_days += 1
        
        # Contraction before explosion (2nd to last day volume < 50% of prior)
        if i == len(klines) - 2 and prev_vol and prev_vol > 0:
            if v < prev_vol * 0.6:
                contraction_before = True
        
        prev_vol = v
    
    # Most tested support
    most_tested = max(support_tests.items(), key=lambda x: x[1]) if support_tests else (0, 0)
    
    # Today's data (last entry)
    today = klines[-1]
    today_change = (today[4] - today[1]) / today[1] * 100 if today[1] > 0 else 0
    today_vol_ratio = today[5] / base_vol if base_vol > 0 else 0
    
    print(f"  今日涨幅: {today_change:+.1f}%  量能倍数: {today_vol_ratio:.0f}x")
    print(f"  前期放量天数(>=3x): {vol_spike_days}天")
    print(f"  长下影线天数: {long_shadow_days}天")
    print(f"  大阳线天数(>=5%): {big_yang_days}天")
    print(f"  最频繁支撑位: {most_tested[0]}元 (测试{most_tested[1]}次)")
    print(f"  爆发前缩量: {'✅ 是' if contraction_before else '❌ 否'}")
    
    # Signal score
    signals = 0
    if vol_spike_days >= 2: signals += 1
    if long_shadow_days >= 2: signals += 1  
    if big_yang_days >= 1: signals += 1
    if most_tested[1] >= 3: signals += 1
    if contraction_before: signals += 1
    print(f"  蓄势信号数: {signals}/5")

conn.close()
