#!/usr/bin/env python3
"""分析最近交易记录 - 输出到文件避免编码问题"""
import sqlite3
import json
import sys

DB_PATH = "simple_trade/data/trade.db"
OUT_PATH = "scripts/trade_analysis_output.json"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

result = {}

# 1. 最近30天交易信号
cur.execute("""
    SELECT ts.id, ts.signal_type, ts.signal_price, ts.target_price, ts.stop_loss_price,
           ts.condition_text, ts.is_executed, ts.executed_time, ts.created_at,
           ts.strategy_id, ts.strategy_name, s.code, s.name as stock_name
    FROM trade_signals ts
    JOIN stocks s ON ts.stock_id = s.id
    WHERE ts.created_at >= datetime('now', '-30 days')
    ORDER BY ts.created_at DESC
    LIMIT 100
""")
signals = [dict(r) for r in cur.fetchall()]
result["trade_signals_count"] = len(signals)
result["trade_signals"] = signals

# 2. trading_records
cur.execute("""
    SELECT * FROM trading_records ORDER BY created_at DESC LIMIT 50
""")
records = [dict(r) for r in cur.fetchall()]
result["trading_records_count"] = len(records)
result["trading_records"] = records

# 3. trade_records (另一个表)
cur.execute("PRAGMA table_info(trade_records)")
cols = [c[1] for c in cur.fetchall()]
result["trade_records_columns"] = cols

cur.execute("SELECT * FROM trade_records ORDER BY rowid DESC LIMIT 50")
tr = [dict(r) for r in cur.fetchall()]
result["trade_records_count"] = len(tr)
result["trade_records"] = tr

# 4. take_profit_tasks
cur.execute("""
    SELECT * FROM take_profit_tasks ORDER BY created_at DESC LIMIT 30
""")
tp = [dict(r) for r in cur.fetchall()]
result["tp_tasks_count"] = len(tp)
result["tp_tasks"] = tp

# 5. take_profit_executions
cur.execute("PRAGMA table_info(take_profit_executions)")
tpe_cols = [c[1] for c in cur.fetchall()]
result["tp_executions_columns"] = tpe_cols

cur.execute("SELECT * FROM take_profit_executions ORDER BY rowid DESC LIMIT 30")
tpe = [dict(r) for r in cur.fetchall()]
result["tp_executions_count"] = len(tpe)
result["tp_executions"] = tpe

# 6. signal_performance
cur.execute("PRAGMA table_info(signal_performance)")
sp_cols = [c[1] for c in cur.fetchall()]
result["signal_performance_columns"] = sp_cols

cur.execute("SELECT * FROM signal_performance ORDER BY rowid DESC LIMIT 30")
sp = [dict(r) for r in cur.fetchall()]
result["signal_performance_count"] = len(sp)
result["signal_performance"] = sp

# 7. 统计每个股票的信号频率
cur.execute("""
    SELECT s.code, s.name, COUNT(*) as signal_count,
           SUM(CASE WHEN ts.signal_type='BUY' THEN 1 ELSE 0 END) as buy_count,
           SUM(CASE WHEN ts.signal_type='SELL' THEN 1 ELSE 0 END) as sell_count,
           MIN(ts.created_at) as first_signal,
           MAX(ts.created_at) as last_signal
    FROM trade_signals ts
    JOIN stocks s ON ts.stock_id = s.id
    WHERE ts.created_at >= datetime('now', '-30 days')
    GROUP BY s.code
    ORDER BY signal_count DESC
""")
stock_stats = [dict(r) for r in cur.fetchall()]
result["stock_signal_stats"] = stock_stats

conn.close()

with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2, default=str)

print(f"Output written to {OUT_PATH}")
print(f"Signals: {result['trade_signals_count']}, Records: {result['trading_records_count']}, TradeRecords: {result['trade_records_count']}")
print(f"TP Tasks: {result['tp_tasks_count']}, TP Executions: {result['tp_executions_count']}")
print(f"Signal Perf: {result['signal_performance_count']}")
print(f"Unique stocks with signals: {len(stock_stats)}")
