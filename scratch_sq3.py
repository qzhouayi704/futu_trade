#!/usr/bin/env python3
"""精简v3：正确列名"""
import sqlite3, json

conn = sqlite3.connect('simple_trade/data/trade.db')
conn.row_factory = sqlite3.Row

codes = ['HK.00772', 'HK.03888']

# 1. signal_pipeline
print("=== signal_pipeline ===")
for code in codes:
    cur = conn.execute(
        "SELECT trade_date, source, direction, strength, final_action, final_reason, "
        "resonance_result, guard_result, raw_detail "
        "FROM signal_pipeline WHERE stock_code = ? ORDER BY id DESC LIMIT 8", (code,))
    rows = cur.fetchall()
    print(f"\n{code} ({len(rows)} signals):")
    for r in rows:
        res = json.loads(r['resonance_result']) if r['resonance_result'] else {}
        guard = json.loads(r['guard_result']) if r['guard_result'] else {}
        raw = json.loads(r['raw_detail']) if r['raw_detail'] else {}
        print(f"  [{r['trade_date']}] {r['source']:8s} {r['direction']:4s} str={r['strength']:5.0f} -> {r['final_action']:8s}")
        print(f"    reason: {r['final_reason']}")
        if res.get('type'):
            print(f"    resonance: {res.get('type')} - {res.get('reason','')[:80]}")
        if not guard.get('passed', True):
            print(f"    guard: BLOCKED - {guard.get('reason','')}")

# 2. overnight - 最近1次
print("\n=== overnight_screen (latest) ===")
cur = conn.execute("SELECT screen_date, candidates_json FROM overnight_screen_results ORDER BY screen_date DESC LIMIT 1")
row = cur.fetchone()
if row:
    cands = json.loads(row['candidates_json'])
    hits = [c for c in cands if c.get('stock_code') in codes]
    print(f"{row['screen_date']} total={len(cands)} hits={len(hits)}")
    for h in hits:
        # 精简输出
        keep = ['stock_code','stock_name','score','total_score','rank',
                'change_pct','volume_ratio','turnover_rate','amplitude',
                'net_inflow_ratio','pattern','strategy','mode',
                'excluded','exclude_reason','r5_candidate',
                'penalty_factor','penalty_reasons']
        out = {k: h[k] for k in keep if k in h}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        # details 单独打印
        if 'details' in h:
            print("  details:", json.dumps(h['details'], ensure_ascii=False, indent=4))

# 3. simulated_trade_records
print("\n=== simulated_trade_records ===")
for code in codes:
    cur = conn.execute("SELECT * FROM simulated_trade_records WHERE stock_code=? ORDER BY created_at DESC LIMIT 3", (code,))
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    print(f"\n{code} ({len(rows)}):")
    for r in rows:
        key_cols = ['direction','price','quantity','resonance_type','reason','status','created_at']
        for c in key_cols:
            if c in cols:
                print(f"  {c}: {r[c]}")
        print()

conn.close()
