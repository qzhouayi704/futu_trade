#!/usr/bin/env python3
"""查隔夜筛选详情 + CCASS持仓"""
import sqlite3, json

conn = sqlite3.connect('simple_trade/data/trade.db')
conn.row_factory = sqlite3.Row

codes = ['HK.00772', 'HK.03888']

# 1. overnight 详细评分
print("=== overnight_screen 详细评分 ===")
cur = conn.execute("SELECT screen_date, candidates_json FROM overnight_screen_results ORDER BY screen_date DESC LIMIT 1")
row = cur.fetchone()
if row:
    cands = json.loads(row['candidates_json'])
    for c in cands:
        if c.get('stock_code') in codes:
            print(f"\n--- {c.get('stock_code')} {c.get('stock_name','')} ---")
            print(f"  总分: {c.get('total_score')} | 排名: {c.get('rank')}")
            if 'details' in c:
                print(f"  评分详情:")
                for k, v in c['details'].items():
                    print(f"    {k}: {v}")
            # 打印所有key
            for k, v in c.items():
                if k not in ('details', 'candidates_json') and not isinstance(v, (dict, list)):
                    print(f"  {k}: {v}")
            # 额外字段
            for k in ['kline_data', 'indicators', 'analysis', 'buy_point', 'trend']:
                if k in c:
                    print(f"  {k}: {json.dumps(c[k], ensure_ascii=False)[:200]}")

# 2. CCASS 持仓变动
print("\n=== ccass_holdings ===")
for code in codes:
    cur = conn.execute("""
        SELECT * FROM ccass_holdings
        WHERE stock_code = ?
        ORDER BY date DESC
        LIMIT 5
    """, (code,))
    rows = cur.fetchall()
    if rows:
        cols = [d[0] for d in cur.description]
        print(f"\n{code} ({len(rows)}):")
        for r in rows:
            print({c: r[c] for c in cols})
    else:
        print(f"\n{code}: No CCASS data")

# 3. 查今日的 signal_pipeline (可能日期格式问题)
print("\n=== signal_pipeline 全部最近20条 ===")
cur = conn.execute("SELECT trade_date, stock_code, stock_name, source, direction, strength, final_action, final_reason FROM signal_pipeline ORDER BY id DESC LIMIT 20")
for r in cur.fetchall():
    print(f"  [{r['trade_date']}] {r['stock_code']} {r['stock_name']:6s} {r['source']:8s} {r['direction']:4s} str={r['strength']:5.0f} -> {r['final_action']:8s} | {r['final_reason'][:60]}")

# 4. 查 recommendation_log
print("\n=== recommendation_log ===")
for code in codes:
    cur = conn.execute("""
        SELECT * FROM recommendation_log
        WHERE stock_code = ?
        ORDER BY created_at DESC
        LIMIT 3
    """, (code,))
    rows = cur.fetchall()
    if rows:
        cols = [d[0] for d in cur.description]
        print(f"\n{code} ({len(rows)}):")
        for r in rows:
            for c in cols:
                print(f"  {c}: {r[c]}")
            print()
    else:
        print(f"\n{code}: No recommendation data")

conn.close()
