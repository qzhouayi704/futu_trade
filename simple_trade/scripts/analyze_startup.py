import sqlite3

DB = r"D:\Program Files\futu_trade_sys\simple_trade\data\trade.db"
conn = sqlite3.connect(DB)

# 富通国际启动前特征：横盘期振幅极小 + 成交量极低 → 突然放量突破
# 验证：00465 在启动前(4/20~4/30)的振幅和成交量
print("=== REF: HK.00465 consolidation check ===")
ref = conn.execute(
    "SELECT time_key,close_price,high_price,low_price,volume,turnover_rate "
    "FROM kline_data WHERE stock_code='HK.00465' ORDER BY time_key DESC LIMIT 30"
).fetchall()
# 横盘期 = 第4~15日（跳过最近3天的启动期）
consol = ref[4:15]
if consol:
    ch = max(r[2] for r in consol)
    cl = min(r[3] for r in consol)
    cm = (ch + cl) / 2
    consol_range = (ch - cl) / cm * 100 if cm > 0 else 999
    consol_avg_vol = sum(r[4] for r in consol) / len(consol)
    print(f"  Consolidation range: {consol_range:.1f}% (H={ch:.3f} L={cl:.3f})")
    print(f"  Avg volume: {consol_avg_vol:.0f}")

# 全市场扫描
stocks = conn.execute("SELECT code,name FROM stocks WHERE is_low_activity=0 AND code LIKE 'HK.%'").fetchall()
results = []

for s in stocks:
    code, name = s[0], s[1]
    kl = conn.execute(
        "SELECT close_price,high_price,low_price,volume,turnover_rate,time_key "
        "FROM kline_data WHERE stock_code=? ORDER BY time_key DESC LIMIT 90", (code,)
    ).fetchall()
    if len(kl) < 25:
        continue

    cur = kl[0][0]
    if cur <= 0:
        continue

    # 横盘期：第4~15日
    consol = kl[4:15]
    if len(consol) < 8:
        continue

    ch = max(r[1] for r in consol)
    cl = min(r[2] for r in consol)
    cm = (ch + cl) / 2
    if cm <= 0:
        continue
    consol_range = (ch - cl) / cm * 100
    consol_avg_vol = sum(r[3] for r in consol) / len(consol)

    # 条件1: 横盘期振幅 < 20%（越小越好）
    if consol_range > 20:
        continue

    # 条件2: 近3日放量 vs 横盘期
    v3 = sum(r[3] for r in kl[:3]) / 3
    if consol_avg_vol <= 0:
        continue
    vol_ratio = v3 / consol_avg_vol
    if vol_ratio < 2.0:
        continue

    # 条件3: 近3日有上涨 (0~15%)
    p3 = kl[2][0]
    chg3 = (cur - p3) / p3 * 100 if p3 > 0 else 0
    if chg3 < 0 or chg3 > 20:
        continue

    # 条件4: 90日位置低 (<40%)，排除高位回落
    h90 = max(r[1] for r in kl)
    l90 = min(r[2] for r in kl)
    if h90 == l90:
        continue
    pos90 = (cur - l90) / (h90 - l90) * 100
    if pos90 > 40:
        continue

    # 条件5: 当前价已突破横盘区间上沿
    breakout = cur > ch

    tr3 = sum((r[4] or 0) for r in kl[:3]) / 3
    last_date = kl[0][5][:10]

    results.append({
        'code': code, 'name': name, 'price': cur,
        'consol_range': consol_range, 'vol_ratio': vol_ratio,
        'chg3': chg3, 'pos90': pos90, 'tr3': tr3,
        'breakout': breakout, 'date': last_date,
    })

# 排序：横盘越窄+放量越大 = 越好
results.sort(key=lambda x: x['consol_range'] - x['vol_ratio'] * 3)

with open(r"D:\Program Files\futu_trade_sys\simple_trade\scripts\_startup.txt", "w", encoding="utf-8") as f:
    f.write(f"Found {len(results)} stocks with consolidation-then-breakout pattern\n\n")
    for i, r in enumerate(results, 1):
        bo = "BREAKOUT" if r['breakout'] else "approaching"
        f.write(f"{i:2d}. {r['code']} {r['name']}\n")
        f.write(f"    Price: {r['price']:.3f} | 90d pos: {r['pos90']:.1f}%\n")
        f.write(f"    Consolidation range: {r['consol_range']:.1f}% | Vol expansion: {r['vol_ratio']:.1f}x\n")
        f.write(f"    3d change: {r['chg3']:+.2f}% | Turnover: {r['tr3']:.2f}% | {bo}\n")
        f.write(f"    Last date: {r['date']}\n\n")

conn.close()
print("done")
