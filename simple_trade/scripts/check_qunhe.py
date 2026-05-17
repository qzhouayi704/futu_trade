import sqlite3
db = r'd:\Program Files\futu_trade_sys\simple_trade\data\trade.db'
conn = sqlite3.connect(db)

# 1. 群核基础状态
print("=== 群核科技 (HK.00068) 状态 ===")
row = conn.execute(
    "SELECT code, name, is_low_activity, low_activity_count, activity_score, "
    "low_activity_checked_at, is_otc, is_manual FROM stocks WHERE code='HK.00068'"
).fetchone()
if row:
    print(f"  is_low_activity={row[2]}, count={row[3]}, score={row[4]}")
    print(f"  checked_at={row[5]}, is_otc={row[6]}, is_manual={row[7]}")

# 2. 板块关联
print("\n=== 板块关联 ===")
rows = conn.execute(
    "SELECT p.plate_code, p.plate_name, p.is_target, p.is_enabled "
    "FROM stocks s JOIN stock_plates sp ON s.id=sp.stock_id "
    "JOIN plates p ON sp.plate_id=p.id WHERE s.code='HK.00068'"
).fetchall()
for r in rows:
    print(f"  {r[0]} | {r[1]} | target={r[2]} | enabled={r[3]}")

# 3. daily_active_stocks 缓存
print("\n=== 今日活跃度缓存 ===")
from datetime import date
today = date.today().strftime('%Y-%m-%d')
rows = conn.execute(
    "SELECT check_date, is_active, activity_score, turnover_rate, turnover_amount "
    "FROM daily_active_stocks WHERE stock_code='HK.00068' ORDER BY check_date DESC LIMIT 3"
).fetchall()
if rows:
    for r in rows:
        print(f"  date={r[0]}, active={r[1]}, score={r[2]}, turnover_rate={r[3]}, amount={r[4]}")
else:
    print("  无缓存记录（尚未被筛选）")

# 4. 检查该股票是否在SQL查询的结果中（模拟 _get_priority_stocks_from_db）
print("\n=== SQL模拟查询 ===")
# 不带低活跃度过滤
count_all = conn.execute(
    "SELECT COUNT(DISTINCT s.code) FROM stocks s "
    "INNER JOIN stock_plates sp ON s.id=sp.stock_id "
    "INNER JOIN plates p ON sp.plate_id=p.id "
    "WHERE p.is_target=1 AND p.is_enabled=1 AND (s.is_otc IS NULL OR s.is_otc=0)"
).fetchone()[0]
print(f"  所有目标板块股票(无过滤): {count_all}")

# 带低活跃度过滤 (threshold=5)
count_filtered = conn.execute(
    "SELECT COUNT(DISTINCT s.code) FROM stocks s "
    "INNER JOIN stock_plates sp ON s.id=sp.stock_id "
    "INNER JOIN plates p ON sp.plate_id=p.id "
    "WHERE p.is_target=1 AND p.is_enabled=1 AND (s.is_otc IS NULL OR s.is_otc=0) "
    "AND (s.low_activity_count IS NULL OR s.low_activity_count < 5)"
).fetchone()[0]
print(f"  过滤后(count<5): {count_filtered}")

# 群核是否在过滤后结果中
in_result = conn.execute(
    "SELECT s.code FROM stocks s "
    "INNER JOIN stock_plates sp ON s.id=sp.stock_id "
    "INNER JOIN plates p ON sp.plate_id=p.id "
    "WHERE p.is_target=1 AND p.is_enabled=1 AND (s.is_otc IS NULL OR s.is_otc=0) "
    "AND (s.low_activity_count IS NULL OR s.low_activity_count < 5) "
    "AND s.code='HK.00068'"
).fetchone()
print(f"  群核在结果中: {'是' if in_result else '否'}")

# 5. 当前订阅状态 - 检查是否有max限制
print("\n=== 配置限制 ===")
import json
with open(r'd:\Program Files\futu_trade_sys\simple_trade\config.json', 'r') as f:
    config = json.load(f)
print(f"  max_subscription_stocks: {config.get('max_subscription_stocks', 'N/A')}")
print(f"  max_stocks_monitor: {config.get('max_stocks_monitor', 'N/A')}")
print(f"  monitor_stocks_limit_by_market HK: {config.get('monitor_stocks_limit_by_market', {}).get('HK', 'N/A')}")

conn.close()
