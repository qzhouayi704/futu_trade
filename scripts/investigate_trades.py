"""临时调查脚本 - 查看近期交易记录和模拟交易情况"""
import sqlite3
import json
from datetime import datetime, timedelta

DB_PATH = "simple_trade/data/trade.db"

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 1. 列出所有表
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cursor.fetchall()]
    print("=== 所有表 ===")
    for t in tables:
        cursor.execute(f"SELECT COUNT(*) FROM [{t}]")
        count = cursor.fetchone()[0]
        print(f"  {t}: {count} rows")
    
    print("\n=== 表结构 ===")
    # 查看交易相关表的结构
    for table_name in tables:
        if any(k in table_name.lower() for k in ['trade', 'order', 'signal', 'position', 'simul']):
            cursor.execute(f"PRAGMA table_info([{table_name}])")
            cols = cursor.fetchall()
            print(f"\n--- {table_name} ---")
            for c in cols:
                print(f"  {c['name']} ({c['type']})")
    
    conn.close()

if __name__ == "__main__":
    main()
