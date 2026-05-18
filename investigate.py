import sqlite3, json, sys
sys.stdout.reconfigure(encoding='utf-8')

db = r"d:\Program Files\futu_trade_sys\simple_trade\data\trade.db"
conn = sqlite3.connect(db)
cur = conn.cursor()

targets = ['HK.06651', 'HK.01384']

# 1. 查看这两只股票在盘后优选中的历史记录
print("=" * 60)
print("1. 盘后优选历史记录")
print("=" * 60)

cur.execute("SELECT screen_date, candidates_json FROM overnight_screen_results ORDER BY screen_date DESC")
rows = cur.fetchall()

for screen_date, cj in rows:
    candidates = json.loads(cj)
    for c in candidates:
        if c.get('stock_code') in targets:
            print(f"\n  [{screen_date}] {c['stock_code']} {c.get('stock_name','')}")
            print(f"    score={c['total_score']}  category={c.get('category','')}  verdict={c.get('verdict','')}")
            km = c.get('key_metrics', {})
            print(f"    last_price={km.get('last_price',0)}  change={km.get('change_rate',0)}%")
            print(f"    reasons: {c.get('reasons', [])}")

# 2. 查看K线数据（最近几天）
print("\n" + "=" * 60)
print("2. 最近K线数据")
print("=" * 60)

for code in targets:
    cur.execute(
        "SELECT time_key, open_price, high_price, low_price, close_price, volume "
        "FROM kline_data WHERE stock_code = ? ORDER BY time_key DESC LIMIT 10",
        (code,)
    )
    klines = cur.fetchall()
    print(f"\n  {code}:")
    if klines:
        for k in klines:
            print(f"    {k[0]}  O={k[1]:.2f}  H={k[2]:.2f}  L={k[3]:.2f}  C={k[4]:.2f}  Vol={k[5]}")
    else:
        print("    无K线数据")

# 3. 查看自动交易任务记录
print("\n" + "=" * 60)
print("3. 自动交易任务记录")
print("=" * 60)

try:
    cur.execute("SELECT * FROM auto_trade_tasks WHERE stock_code IN (?, ?)", targets)
    tasks = cur.fetchall()
    if tasks:
        cols = [d[0] for d in cur.description]
        for t in tasks:
            row = dict(zip(cols, t))
            print(f"\n  {row}")
    else:
        print("  无自动交易任务记录")
except Exception as e:
    print(f"  查询失败: {e}")

# 4. 查看交易历史
print("\n" + "=" * 60)
print("4. 交易历史")
print("=" * 60)

try:
    cur.execute("SELECT * FROM trade_history WHERE stock_code IN (?, ?) ORDER BY create_time DESC LIMIT 10", targets)
    trades = cur.fetchall()
    if trades:
        cols = [d[0] for d in cur.description]
        for t in trades:
            row = dict(zip(cols, t))
            print(f"\n  {row}")
    else:
        print("  无交易历史")
except Exception as e:
    print(f"  查询失败: {e}")

conn.close()
