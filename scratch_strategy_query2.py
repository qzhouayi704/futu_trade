#!/usr/bin/env python3
"""查信号管道+隔夜筛选+trade_signals表结构"""
import sqlite3, json

conn = sqlite3.connect('simple_trade/data/trade.db')
conn.row_factory = sqlite3.Row

codes = ['HK.00772', 'HK.03888']
names = {'HK.00772': '阅文集团', 'HK.03888': '金山软件'}

# 1. signal_pipeline
print("=" * 70)
print("  signal_pipeline 最近信号")
print("=" * 70)
for code in codes:
    cur = conn.execute("""
        SELECT trade_date, stock_code, stock_name, signal_type, score, mode,
               entry_price, reason, status, created_at
        FROM signal_pipeline
        WHERE stock_code = ?
        ORDER BY created_at DESC
        LIMIT 8
    """, (code,))
    rows = cur.fetchall()
    print(f"\n  --- {code} {names[code]} ({len(rows)} signals) ---")
    for r in rows:
        print(f"  [{r['trade_date']}] {r['signal_type']} | 评分:{r['score']} | 模式:{r['mode']} | 价格:{r['entry_price']} | 状态:{r['status']}")
        print(f"    原因: {r['reason']}")

# 2. overnight_screen - 仅查这两只是否在候选中
print("\n" + "=" * 70)
print("  隔夜筛选 - 两只股票在近5次筛选中的情况")
print("=" * 70)
cur = conn.execute("""
    SELECT screen_date, candidates_json, created_at
    FROM overnight_screen_results
    ORDER BY screen_date DESC
    LIMIT 5
""")
rows = cur.fetchall()
for r in rows:
    try:
        candidates = json.loads(r['candidates_json'])
        found = []
        for c in candidates:
            sc = c.get('stock_code', '')
            if sc in codes:
                found.append(c)
        if found:
            print(f"\n  [{r['screen_date']}] 命中 {len(found)} 只:")
            for f in found:
                score = f.get('score', f.get('total_score', '?'))
                rank = f.get('rank', '?')
                name = f.get('stock_name', f.get('name', ''))
                print(f"    {f.get('stock_code', '')} {name} | 评分:{score} | 排名:{rank}")
                # 打印关键指标
                for k in ['change_pct', 'volume_ratio', 'turnover_rate', 'amplitude',
                          'net_inflow_ratio', 'pattern', 'strategy', 'mode',
                          'buy_reason', 'sell_reason', 'excluded', 'exclude_reason',
                          'penalty_factor', 'r5_candidate', 'details']:
                    if k in f and f[k]:
                        val = f[k]
                        if isinstance(val, dict):
                            print(f"      {k}:")
                            for kk, vv in val.items():
                                print(f"        {kk}: {vv}")
                        else:
                            print(f"      {k}: {val}")
        else:
            print(f"\n  [{r['screen_date']}] 两只均未入选 (共{len(candidates)}只候选)")
    except Exception as e:
        print(f"\n  [{r['screen_date']}] 解析错误: {e}")

# 3. trade_signals 表结构
print("\n" + "=" * 70)
print("  trade_signals 表结构")
print("=" * 70)
cur = conn.execute("PRAGMA table_info(trade_signals)")
for r in cur.fetchall():
    print(f"  {r}")

# 查 simulated_trade_records
print("\n" + "=" * 70)
print("  simulated_trade_records 最近记录")
print("=" * 70)
for code in codes:
    cur = conn.execute("""
        SELECT * FROM simulated_trade_records
        WHERE stock_code = ?
        ORDER BY created_at DESC
        LIMIT 3
    """, (code,))
    rows = cur.fetchall()
    print(f"\n  --- {code} {names[code]} ({len(rows)} records) ---")
    if rows:
        cols = [d[0] for d in cur.description]
        for r in rows:
            for c in cols:
                print(f"    {c}: {r[c]}")
            print()

# 4. signal_performance
print("\n" + "=" * 70)
print("  signal_performance 信号表现")
print("=" * 70)
for code in codes:
    cur = conn.execute("""
        SELECT * FROM signal_performance
        WHERE stock_code = ?
        ORDER BY created_at DESC
        LIMIT 3
    """, (code,))
    rows = cur.fetchall()
    print(f"\n  --- {code} {names[code]} ({len(rows)} records) ---")
    if rows:
        cols = [d[0] for d in cur.description]
        for r in rows:
            for c in cols:
                print(f"    {c}: {r[c]}")
            print()

conn.close()
