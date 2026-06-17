#!/usr/bin/env python3
"""统计历史信号效果，分析信号准确率"""
import sqlite3
import json

DB_PATH = "simple_trade/data/trade.db"
OUT_PATH = "scripts/signal_accuracy_analysis.json"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

result = {}

# 1. 按策略+信号类型统计已完成追踪的信号效果
cur.execute("""
    SELECT sp.strategy_id, sp.signal_type,
           COUNT(*) as total,
           AVG(sp.day1_max_rise) as avg_day1_rise,
           AVG(sp.day1_max_drop) as avg_day1_drop,
           AVG(sp.day3_max_rise) as avg_day3_rise,
           AVG(sp.day3_max_drop) as avg_day3_drop,
           AVG(sp.day5_max_rise) as avg_day5_rise,
           AVG(sp.day5_max_drop) as avg_day5_drop,
           SUM(CASE WHEN sp.signal_type='BUY' AND sp.day3_max_rise > 3.0 THEN 1 ELSE 0 END) as buy_win_3pct,
           SUM(CASE WHEN sp.signal_type='BUY' AND sp.day3_max_drop < -5.0 THEN 1 ELSE 0 END) as buy_loss_5pct,
           SUM(CASE WHEN sp.signal_type='SELL' AND sp.day3_max_drop < -3.0 THEN 1 ELSE 0 END) as sell_win_3pct,
           SUM(CASE WHEN sp.signal_type='SELL' AND sp.day3_max_rise > 5.0 THEN 1 ELSE 0 END) as sell_loss_5pct
    FROM signal_performance sp
    WHERE sp.tracking_status = 'completed'
    GROUP BY sp.strategy_id, sp.signal_type
    ORDER BY sp.strategy_id, sp.signal_type
""")
result["completed_perf_by_strategy"] = [dict(r) for r in cur.fetchall()]

# 2. 总体统计
cur.execute("""
    SELECT 
        COUNT(*) as total,
        SUM(CASE WHEN tracking_status='completed' THEN 1 ELSE 0 END) as completed,
        SUM(CASE WHEN tracking_status='active' THEN 1 ELSE 0 END) as active
    FROM signal_performance
""")
result["perf_status_counts"] = dict(cur.fetchone())

# 3. 已完成信号的具体样本 - BUY信号效果
cur.execute("""
    SELECT sp.stock_code, sp.signal_type, sp.signal_price, sp.strategy_id,
           sp.day1_max_rise, sp.day1_max_drop,
           sp.day3_max_rise, sp.day3_max_drop,
           sp.day5_max_rise, sp.day5_max_drop,
           sp.created_at
    FROM signal_performance sp
    WHERE sp.tracking_status = 'completed' AND sp.signal_type = 'BUY'
    ORDER BY sp.created_at DESC
    LIMIT 30
""")
result["completed_buy_samples"] = [dict(r) for r in cur.fetchall()]

# 4. 已完成信号的具体样本 - SELL信号效果
cur.execute("""
    SELECT sp.stock_code, sp.signal_type, sp.signal_price, sp.strategy_id,
           sp.day1_max_rise, sp.day1_max_drop,
           sp.day3_max_rise, sp.day3_max_drop,
           sp.day5_max_rise, sp.day5_max_drop,
           sp.created_at
    FROM signal_performance sp
    WHERE sp.tracking_status = 'completed' AND sp.signal_type = 'SELL'
    ORDER BY sp.created_at DESC
    LIMIT 30
""")
result["completed_sell_samples"] = [dict(r) for r in cur.fetchall()]

# 5. 买入信号中实际跌了很多的（假信号）
cur.execute("""
    SELECT sp.stock_code, sp.signal_price, sp.strategy_id,
           sp.day1_max_rise, sp.day1_max_drop,
           sp.day3_max_rise, sp.day3_max_drop,
           sp.day5_max_rise, sp.day5_max_drop,
           sp.created_at
    FROM signal_performance sp
    WHERE sp.tracking_status = 'completed' AND sp.signal_type = 'BUY'
      AND sp.day3_max_drop < -5.0
    ORDER BY sp.day3_max_drop ASC
    LIMIT 20
""")
result["worst_buy_signals"] = [dict(r) for r in cur.fetchall()]

# 6. 卖出信号中实际涨了很多的（假信号）
cur.execute("""
    SELECT sp.stock_code, sp.signal_price, sp.strategy_id,
           sp.day1_max_rise, sp.day1_max_drop,
           sp.day3_max_rise, sp.day3_max_drop,
           sp.day5_max_rise, sp.day5_max_drop,
           sp.created_at
    FROM signal_performance sp
    WHERE sp.tracking_status = 'completed' AND sp.signal_type = 'SELL'
      AND sp.day3_max_rise > 5.0
    ORDER BY sp.day3_max_rise DESC
    LIMIT 20
""")
result["worst_sell_signals"] = [dict(r) for r in cur.fetchall()]

# 7. 已实现收益口径（持有到收盘 vs 摸高率）—— 诚实记分牌
#    胜率 = close_ret > 0 占比；并报均盈/均亏。需先跑 add_signal_close_ret.sql 迁移，
#    旧库无该列时静默跳过（不影响其余分析）。
try:
    cur.execute("""
        SELECT sp.strategy_id, sp.signal_type,
               COUNT(sp.day1_close_ret) as n_close,
               AVG(sp.day1_close_ret) as avg_close_1d,
               AVG(sp.day3_close_ret) as avg_close_3d,
               SUM(CASE WHEN sp.signal_type='BUY' AND sp.day1_close_ret > 0 THEN 1 ELSE 0 END) as buy_close_win_1d,
               AVG(CASE WHEN sp.day1_close_ret > 0 THEN sp.day1_close_ret END) as avg_win_1d,
               AVG(CASE WHEN sp.day1_close_ret <= 0 THEN sp.day1_close_ret END) as avg_loss_1d
        FROM signal_performance sp
        WHERE sp.tracking_status = 'completed' AND sp.day1_close_ret IS NOT NULL
        GROUP BY sp.strategy_id, sp.signal_type
        ORDER BY sp.strategy_id, sp.signal_type
    """)
    result["realized_close_perf_by_strategy"] = [dict(r) for r in cur.fetchall()]
except sqlite3.OperationalError as e:
    result["realized_close_perf_by_strategy"] = {"skipped": f"close_ret 列不存在(需先跑迁移): {e}"}

conn.close()

with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2, default=str)

print(f"Output: {OUT_PATH}")
for k, v in result.items():
    if isinstance(v, list):
        print(f"  {k}: {len(v)} items")
    elif isinstance(v, dict):
        print(f"  {k}: {v}")
