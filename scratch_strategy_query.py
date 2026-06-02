#!/usr/bin/env python3
"""综合查询：信号管道、隔夜筛选、资金流信号、大单追踪"""
import sqlite3, json

conn = sqlite3.connect('simple_trade/data/trade.db')
conn.row_factory = sqlite3.Row

codes = ['HK.00772', 'HK.03888']
names = {'HK.00772': '阅文集团', 'HK.03888': '金山软件'}

# 1. signal_pipeline (信号管道 - 盘中买卖点)
print("=" * 70)
print("  1. 信号管道 signal_pipeline (最近5天)")
print("=" * 70)
for code in codes:
    cur = conn.execute("""
        SELECT * FROM signal_pipeline
        WHERE stock_code = ?
        ORDER BY created_at DESC
        LIMIT 10
    """, (code,))
    rows = cur.fetchall()
    print(f"\n  --- {code} {names[code]} ({len(rows)} signals) ---")
    if rows:
        cols = [d[0] for d in cur.description]
        for r in rows:
            vals = {c: r[c] for c in cols}
            print(f"  {vals}")
    else:
        print("  No signals")

# 2. overnight_screen_results (隔夜筛选)
print("\n" + "=" * 70)
print("  2. 隔夜筛选 overnight_screen_results (最近3次)")
print("=" * 70)
cur = conn.execute("""
    SELECT screen_date, total_count, candidates_json, created_at
    FROM overnight_screen_results
    ORDER BY screen_date DESC
    LIMIT 3
""")
rows = cur.fetchall()
for r in rows:
    print(f"\n  日期: {r['screen_date']} | 总候选: {r['total_count']} | 创建: {r['created_at']}")
    try:
        candidates = json.loads(r['candidates_json'])
        for c in candidates:
            sc = c.get('stock_code', '')
            if sc in codes:
                print(f"  >>> 命中: {json.dumps(c, ensure_ascii=False, indent=4)}")
    except:
        print("  (parse error)")

# 3. capital_flow_signals (资金流信号)
print("\n" + "=" * 70)
print("  3. 资金流信号 capital_flow_signals")
print("=" * 70)
for code in codes:
    cur = conn.execute("""
        SELECT * FROM capital_flow_signals
        WHERE stock_code = ?
        ORDER BY created_at DESC
        LIMIT 5
    """, (code,))
    rows = cur.fetchall()
    print(f"\n  --- {code} {names[code]} ({len(rows)} signals) ---")
    if rows:
        cols = [d[0] for d in cur.description]
        for r in rows:
            vals = {c: r[c] for c in cols}
            print(f"  {vals}")

# 4. big_order_tracking (大单追踪)
print("\n" + "=" * 70)
print("  4. 大单追踪 big_order_tracking")
print("=" * 70)
for code in codes:
    cur = conn.execute("""
        SELECT * FROM big_order_tracking
        WHERE stock_code = ?
        ORDER BY created_at DESC
        LIMIT 5
    """, (code,))
    rows = cur.fetchall()
    print(f"\n  --- {code} {names[code]} ({len(rows)} orders) ---")
    if rows:
        cols = [d[0] for d in cur.description]
        for r in rows:
            vals = {c: r[c] for c in cols}
            print(f"  {vals}")

# 5. scalping_signals (狙击信号)
print("\n" + "=" * 70)
print("  5. 狙击信号 scalping_signals")
print("=" * 70)
for code in codes:
    cur = conn.execute("""
        SELECT * FROM scalping_signals
        WHERE stock_code = ?
        ORDER BY created_at DESC
        LIMIT 5
    """, (code,))
    rows = cur.fetchall()
    print(f"\n  --- {code} {names[code]} ({len(rows)} signals) ---")
    if rows:
        cols = [d[0] for d in cur.description]
        for r in rows:
            vals = {c: r[c] for c in cols}
            print(f"  {vals}")

# 6. trade_signals (交易信号)
print("\n" + "=" * 70)
print("  6. 交易信号 trade_signals")
print("=" * 70)
for code in codes:
    cur = conn.execute("""
        SELECT * FROM trade_signals
        WHERE stock_code = ?
        ORDER BY created_at DESC
        LIMIT 5
    """, (code,))
    rows = cur.fetchall()
    print(f"\n  --- {code} {names[code]} ({len(rows)} signals) ---")
    if rows:
        cols = [d[0] for d in cur.description]
        for r in rows:
            vals = {c: r[c] for c in cols}
            print(f"  {vals}")

# 7. simulated_trade_records (模拟交易记录)
print("\n" + "=" * 70)
print("  7. 模拟交易记录 simulated_trade_records")
print("=" * 70)
for code in codes:
    cur = conn.execute("""
        SELECT * FROM simulated_trade_records
        WHERE stock_code = ?
        ORDER BY created_at DESC
        LIMIT 5
    """, (code,))
    rows = cur.fetchall()
    print(f"\n  --- {code} {names[code]} ({len(rows)} records) ---")
    if rows:
        cols = [d[0] for d in cur.description]
        for r in rows:
            vals = {c: r[c] for c in cols}
            print(f"  {vals}")

# 8. signal_performance (信号表现)
print("\n" + "=" * 70)
print("  8. 信号表现 signal_performance")
print("=" * 70)
for code in codes:
    cur = conn.execute("""
        SELECT * FROM signal_performance
        WHERE stock_code = ?
        ORDER BY created_at DESC
        LIMIT 5
    """, (code,))
    rows = cur.fetchall()
    print(f"\n  --- {code} {names[code]} ({len(rows)} records) ---")
    if rows:
        cols = [d[0] for d in cur.description]
        for r in rows:
            vals = {c: r[c] for c in cols}
            print(f"  {vals}")

conn.close()
