#!/usr/bin/env python3
"""深入分析：实际交易记录 + 信号效果 + 富途持仓"""
import sqlite3
import json

DB_PATH = "simple_trade/data/trade.db"
OUT_PATH = "scripts/trade_deep_analysis.json"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

result = {}

# 1. trade_records 表结构和数据
cur.execute("PRAGMA table_info(trade_records)")
result["trade_records_cols"] = [c[1] for c in cur.fetchall()]

cur.execute("SELECT COUNT(*) FROM trade_records")
result["trade_records_total"] = cur.fetchone()[0]

cur.execute("SELECT * FROM trade_records ORDER BY rowid DESC LIMIT 30")
result["trade_records"] = [dict(r) for r in cur.fetchall()]

# 2. signal_performance 详细数据
cur.execute("PRAGMA table_info(signal_performance)")
result["signal_perf_cols"] = [c[1] for c in cur.fetchall()]

cur.execute("SELECT * FROM signal_performance ORDER BY rowid DESC LIMIT 30")
result["signal_performance"] = [dict(r) for r in cur.fetchall()]

# 3. advisor_evaluations (AI 决策评估)
cur.execute("PRAGMA table_info(advisor_evaluations)")
result["advisor_eval_cols"] = [c[1] for c in cur.fetchall()]

cur.execute("SELECT COUNT(*) FROM advisor_evaluations")
result["advisor_eval_total"] = cur.fetchone()[0]

cur.execute("SELECT * FROM advisor_evaluations ORDER BY rowid DESC LIMIT 10")
result["advisor_evaluations"] = [dict(r) for r in cur.fetchall()]

# 4. 按日统计信号数量
cur.execute("""
    SELECT DATE(created_at) as date, 
           COUNT(*) as total,
           SUM(CASE WHEN signal_type='BUY' THEN 1 ELSE 0 END) as buy,
           SUM(CASE WHEN signal_type='SELL' THEN 1 ELSE 0 END) as sell,
           COUNT(DISTINCT stock_id) as unique_stocks
    FROM trade_signals 
    WHERE created_at >= datetime('now', '-30 days')
    GROUP BY DATE(created_at)
    ORDER BY date DESC
""")
result["daily_signal_stats"] = [dict(r) for r in cur.fetchall()]

# 5. 按策略统计
cur.execute("""
    SELECT COALESCE(strategy_id, 'unknown') as strategy, 
           COUNT(*) as total,
           SUM(CASE WHEN signal_type='BUY' THEN 1 ELSE 0 END) as buy,
           SUM(CASE WHEN signal_type='SELL' THEN 1 ELSE 0 END) as sell
    FROM trade_signals 
    WHERE created_at >= datetime('now', '-30 days')
    GROUP BY strategy_id
    ORDER BY total DESC
""")
result["strategy_stats"] = [dict(r) for r in cur.fetchall()]

# 6. take_profit_tasks 和 executions
cur.execute("SELECT * FROM take_profit_tasks ORDER BY created_at DESC LIMIT 10")
result["tp_tasks"] = [dict(r) for r in cur.fetchall()]

cur.execute("SELECT * FROM take_profit_executions ORDER BY rowid DESC LIMIT 10")
result["tp_executions"] = [dict(r) for r in cur.fetchall()]

# 7. 检查 kline_data 表结构
cur.execute("PRAGMA table_info(kline_data)")
result["kline_cols"] = [c[1] for c in cur.fetchall()]

cur.execute("SELECT * FROM kline_data ORDER BY rowid DESC LIMIT 5")
result["kline_sample"] = [dict(r) for r in cur.fetchall()]

cur.execute("SELECT COUNT(*) FROM kline_data")
result["kline_total"] = cur.fetchone()[0]

conn.close()

with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2, default=str)

print(f"Output written to {OUT_PATH}")
for k, v in result.items():
    if isinstance(v, list):
        print(f"  {k}: {len(v)} items")
    else:
        print(f"  {k}: {v}")
