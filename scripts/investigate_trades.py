"""深入调查脚本 - 查看近期交易信号、signal_performance和持仓"""
import sqlite3
import json
from datetime import datetime, timedelta

DB_PATH = "simple_trade/data/trade.db"

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 1. 近5天的交易信号
    print("=== 近5天 trade_signals (最近20条) ===")
    cursor.execute("""
        SELECT id, stock_id, signal_type, signal_price, strategy_id, strategy_name, 
               is_executed, created_at 
        FROM trade_signals 
        ORDER BY created_at DESC LIMIT 20
    """)
    for r in cursor.fetchall():
        print(f"  ID={r['id']} stock_id={r['stock_id']} type={r['signal_type']} "
              f"price={r['signal_price']} strategy={r['strategy_id']} "
              f"executed={r['is_executed']} created={r['created_at']}")
    
    # 2. signal_performance 最近记录
    print("\n=== signal_performance 最近20条 ===")
    cursor.execute("""
        SELECT id, stock_code, signal_type, signal_price, strategy_id, 
               day1_max_rise, day1_max_drop, tracking_status, created_at
        FROM signal_performance 
        ORDER BY created_at DESC LIMIT 20
    """)
    for r in cursor.fetchall():
        print(f"  {r['stock_code']} {r['signal_type']} price={r['signal_price']} "
              f"strat={r['strategy_id']} d1_rise={r['day1_max_rise']} d1_drop={r['day1_max_drop']} "
              f"status={r['tracking_status']} created={r['created_at']}")
    
    # 3. signal_pipeline (信号管道)
    print("\n=== signal_pipeline 最近记录 ===")
    cursor.execute("SELECT COUNT(*) FROM signal_pipeline")
    print(f"  总记录: {cursor.fetchone()[0]}")
    cursor.execute("""
        SELECT * FROM signal_pipeline ORDER BY created_at DESC LIMIT 10
    """)
    for r in cursor.fetchall():
        print(f"  {dict(r)}")
    
    # 4. sniper_signals 最近记录
    print("\n=== sniper_signals 最近20条 ===")
    cursor.execute("""
        SELECT trade_date, time, stock_code, stock_name, signal_type, action, 
               price, severity, created_at
        FROM sniper_signals 
        ORDER BY created_at DESC LIMIT 20
    """)
    for r in cursor.fetchall():
        print(f"  {r['trade_date']} {r['time']} {r['stock_code']} {r['stock_name']} "
              f"type={r['signal_type']} action={r['action']} price={r['price']} "
              f"severity={r['severity']}")
    
    # 5. capital_flow_signals 最近记录
    print("\n=== capital_flow_signals 最近10条 ===")
    cursor.execute("""
        SELECT stock_code, stock_name, signal_type, rule_name, price, 
               confidence, priority, created_at
        FROM capital_flow_signals 
        ORDER BY created_at DESC LIMIT 10
    """)
    for r in cursor.fetchall():
        print(f"  {r['stock_code']} {r['stock_name']} {r['signal_type']} "
              f"rule={r['rule_name']} price={r['price']} conf={r['confidence']} "
              f"pri={r['priority']} created={r['created_at']}")
    
    # 6. overnight_screen_results
    print("\n=== overnight_screen_results ===")
    cursor.execute("""
        SELECT * FROM overnight_screen_results ORDER BY rowid DESC LIMIT 10
    """)
    for r in cursor.fetchall():
        print(f"  {dict(r)}")
    
    # 7. recommendation_log 最近
    print("\n=== recommendation_log 表结构和最近记录 ===")
    cursor.execute("PRAGMA table_info(recommendation_log)")
    cols = cursor.fetchall()
    print(f"  列: {[c['name'] for c in cols]}")
    cursor.execute("SELECT * FROM recommendation_log ORDER BY rowid DESC LIMIT 5")
    for r in cursor.fetchall():
        d = dict(r)
        # 截断长字段
        for k, v in d.items():
            if isinstance(v, str) and len(v) > 200:
                d[k] = v[:200] + "..."
        print(f"  {d}")
    
    conn.close()

if __name__ == "__main__":
    main()
