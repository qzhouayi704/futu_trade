import sqlite3
db = sqlite3.connect(r'd:\Program Files\futu_trade_sys\simple_trade\data\trade.db')
c = db.cursor()

print('=== trade_signals 最近10条 ===')
for r in c.execute('''SELECT ts.id, s.code, ts.signal_type, ts.strategy_id, 
    substr(ts.condition_text, 1, 60), ts.created_at 
    FROM trade_signals ts JOIN stocks s ON ts.stock_id = s.id
    ORDER BY ts.created_at DESC LIMIT 10''').fetchall():
    sid = r[3] if r[3] else '(none)'
    cond = r[4] if r[4] else ''
    print(f'  {r[1]:12s} | {r[2]:4s} | {sid:30s} | {cond}')
    print(f'               created: {r[5]}')

print('\n=== 按策略ID统计 ===')
for r in c.execute('SELECT COALESCE(strategy_id, "(none)"), COUNT(*) FROM trade_signals GROUP BY strategy_id ORDER BY COUNT(*) DESC'):
    print(f'  {r[0]:30s} => {r[1]} signals')

print('\n=== 今天的信号 ===')
for r in c.execute('''SELECT s.code, ts.signal_type, ts.strategy_id, 
    substr(ts.condition_text, 1, 70), ts.created_at
    FROM trade_signals ts JOIN stocks s ON ts.stock_id = s.id
    WHERE ts.created_at >= date("now", "start of day")
    ORDER BY ts.created_at DESC LIMIT 15''').fetchall():
    sid = r[2] if r[2] else '(none)'
    print(f'  {r[0]:12s} | {r[1]:4s} | {sid:30s} | {r[3] if r[3] else ""}')

db.close()
