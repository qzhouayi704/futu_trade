"""分析近几日信号质量 — 信号发出后价格是否按预期方向运动"""
import sqlite3
import json
from datetime import datetime, timedelta, date
from collections import defaultdict

DB_PATH = "simple_trade/data/trade.db"

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # ==================== 1. Sniper 信号质量分析 ====================
    print("=" * 70)
    print("1. SNIPER 信号分析（近5个交易日）")
    print("=" * 70)

    # 获取近5天的sniper信号
    cursor.execute("""
        SELECT trade_date, time, stock_code, stock_name, signal_type,
               is_red, price, detail, action
        FROM sniper_signals
        WHERE trade_date >= date('now', '-7 days')
        ORDER BY trade_date DESC, time DESC
    """)
    sniper_rows = cursor.fetchall()
    print(f"共 {len(sniper_rows)} 条信号\n")

    # 按天统计
    by_date = defaultdict(list)
    for r in sniper_rows:
        by_date[r['trade_date']].append(r)

    for dt in sorted(by_date.keys(), reverse=True):
        signals = by_date[dt]
        green = [s for s in signals if not s['is_red']]
        red = [s for s in signals if s['is_red']]
        print(f"--- {dt}: {len(signals)}条 (🟢{len(green)} 🔴{len(red)}) ---")

        # 按类型统计
        type_counts = defaultdict(int)
        for s in signals:
            type_counts[s['signal_type']] += 1
        for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
            print(f"  {t}: {c}条")

        # 展示前10条信号
        for s in signals[:10]:
            emoji = "🔴" if s['is_red'] else "🟢"
            print(f"  {emoji} {s['time']} {s['stock_name']}({s['stock_code']}) "
                  f"type={s['signal_type']} price={s['price']:.3f}")
            print(f"       {s['detail'][:80]}")
        if len(signals) > 10:
            print(f"  ... 还有 {len(signals)-10} 条")
        print()

    # ==================== 2. 信号后价格验证 ====================
    print("=" * 70)
    print("2. SNIPER 信号后价格验证（信号价格 vs 后续收盘价）")
    print("=" * 70)

    # 获取每只股票的K线数据
    cursor.execute("""
        SELECT stock_code, time_key, close_price, high_price, low_price
        FROM kline_data
        WHERE time_key >= date('now', '-14 days')
        ORDER BY stock_code, time_key
    """)
    kline_rows = cursor.fetchall()
    kline_map = defaultdict(list)
    for r in kline_rows:
        kline_map[r['stock_code']].append({
            'date': r['time_key'][:10],
            'close': r['close_price'],
            'high': r['high_price'],
            'low': r['low_price'],
        })

    # 对每条绿色买入信号，检查发出后1-3天的价格走势
    print("\n--- 🟢 买入信号验证 ---")
    buy_signals = [s for s in sniper_rows if not s['is_red']
                   and s['signal_type'] in ('mega_buy', 'accel_in', 'reversal_bull')]
    
    win_count, loss_count, no_data = 0, 0, 0
    for s in buy_signals[:30]:
        code = s['stock_code']
        sig_date = s['trade_date']
        sig_price = s['price']
        
        klines = kline_map.get(code, [])
        future_klines = [k for k in klines if k['date'] > sig_date]
        
        if not future_klines:
            no_data += 1
            continue
        
        # 信号后1-3天的最高价和收盘价
        max_high = max(k['high'] for k in future_klines[:3])
        last_close = future_klines[min(2, len(future_klines)-1)]['close']
        
        rise_pct = (max_high - sig_price) / sig_price * 100 if sig_price > 0 else 0
        close_pct = (last_close - sig_price) / sig_price * 100 if sig_price > 0 else 0
        
        won = rise_pct > 1.0  # 最高涨超1%算赢
        if won:
            win_count += 1
        else:
            loss_count += 1
        
        result = "✅" if won else "❌"
        print(f"  {result} {s['trade_date']} {s['time']} {s['stock_name']} "
              f"type={s['signal_type']} 信号价={sig_price:.3f} "
              f"后3日最高涨{rise_pct:+.1f}% 收盘{close_pct:+.1f}%")

    total = win_count + loss_count
    if total > 0:
        print(f"\n  买入信号胜率: {win_count}/{total} = {win_count/total*100:.0f}% "
              f"(无数据{no_data}条)")

    # 红色信号验证
    print("\n--- 🔴 风险信号验证 ---")
    sell_signals = [s for s in sniper_rows if s['is_red']
                    and s['signal_type'] in ('mega_sell', 'sustained_out', 'reversal_bear')]
    
    win_count, loss_count, no_data = 0, 0, 0
    for s in sell_signals[:30]:
        code = s['stock_code']
        sig_date = s['trade_date']
        sig_price = s['price']
        
        klines = kline_map.get(code, [])
        future_klines = [k for k in klines if k['date'] > sig_date]
        
        if not future_klines:
            no_data += 1
            continue
        
        min_low = min(k['low'] for k in future_klines[:3])
        last_close = future_klines[min(2, len(future_klines)-1)]['close']
        
        drop_pct = (min_low - sig_price) / sig_price * 100 if sig_price > 0 else 0
        close_pct = (last_close - sig_price) / sig_price * 100 if sig_price > 0 else 0
        
        won = drop_pct < -1.0  # 最低跌超1%算正确
        if won:
            win_count += 1
        else:
            loss_count += 1
        
        result = "✅" if won else "❌"
        print(f"  {result} {s['trade_date']} {s['time']} {s['stock_name']} "
              f"type={s['signal_type']} 信号价={sig_price:.3f} "
              f"后3日最低跌{drop_pct:+.1f}% 收盘{close_pct:+.1f}%")

    total = win_count + loss_count
    if total > 0:
        print(f"\n  风险信号准确率: {win_count}/{total} = {win_count/total*100:.0f}% "
              f"(无数据{no_data}条)")

    # ==================== 3. 策略信号质量 ====================
    print("\n" + "=" * 70)
    print("3. 策略信号(trade_signals)分析")
    print("=" * 70)

    cursor.execute("""
        SELECT ts.id, ts.stock_id, ts.signal_type, ts.signal_price,
               ts.strategy_id, ts.strategy_name, ts.created_at,
               s.code, s.name
        FROM trade_signals ts
        LEFT JOIN stocks s ON ts.stock_id = s.id
        WHERE ts.created_at >= datetime('now', '-3 days')
        ORDER BY ts.created_at DESC
        LIMIT 50
    """)
    trade_sig_rows = cursor.fetchall()
    print(f"近3天策略信号: {len(trade_sig_rows)}条\n")

    # 按策略统计
    strat_counts = defaultdict(lambda: {'BUY': 0, 'SELL': 0})
    for r in trade_sig_rows:
        strat_counts[r['strategy_id']][r['signal_type']] += 1
    
    for strat, counts in sorted(strat_counts.items()):
        print(f"  {strat}: BUY={counts['BUY']} SELL={counts['SELL']}")

    # 展示BUY信号并验证后续走势
    print(f"\n--- 策略BUY信号后续走势 ---")
    buy_sigs = [r for r in trade_sig_rows if r['signal_type'] == 'BUY']
    
    win_count, loss_count, no_data = 0, 0, 0
    for r in buy_sigs[:20]:
        code = r['code']
        if not code:
            continue
        sig_price = r['signal_price']
        sig_date = r['created_at'][:10]
        
        klines = kline_map.get(code, [])
        future_klines = [k for k in klines if k['date'] > sig_date]
        
        if not future_klines:
            no_data += 1
            continue
        
        max_high = max(k['high'] for k in future_klines[:3])
        last_close = future_klines[min(2, len(future_klines)-1)]['close']
        
        rise_pct = (max_high - sig_price) / sig_price * 100 if sig_price > 0 else 0
        close_pct = (last_close - sig_price) / sig_price * 100 if sig_price > 0 else 0
        
        won = rise_pct > 1.0
        if won:
            win_count += 1
        else:
            loss_count += 1
        
        result = "✅" if won else "❌"
        print(f"  {result} {r['created_at'][:16]} {r['name']}({code}) "
              f"策略={r['strategy_id']} 信号价={sig_price:.2f} "
              f"后3日涨{rise_pct:+.1f}% 收盘{close_pct:+.1f}%")

    total = win_count + loss_count
    if total > 0:
        print(f"\n  策略BUY信号胜率: {win_count}/{total} = {win_count/total*100:.0f}% "
              f"(无数据{no_data}条)")

    # ==================== 4. signal_performance 追踪效果 ====================
    print("\n" + "=" * 70)
    print("4. signal_performance 信号追踪效果")
    print("=" * 70)

    cursor.execute("""
        SELECT stock_code, signal_type, signal_price, strategy_id,
               day1_max_rise, day1_max_drop, day3_max_rise, day3_max_drop,
               day5_max_rise, day5_max_drop, tracking_status, created_at
        FROM signal_performance
        WHERE tracking_status = 'completed'
        AND created_at >= datetime('now', '-7 days')
        ORDER BY created_at DESC
        LIMIT 30
    """)
    perf_rows = cursor.fetchall()
    print(f"近7天已完成追踪: {len(perf_rows)}条\n")

    for r in perf_rows[:20]:
        print(f"  {r['stock_code']} {r['signal_type']} price={r['signal_price']:.2f} "
              f"strat={r['strategy_id']} "
              f"D1[+{r['day1_max_rise']:.1f}%/-{r['day1_max_drop']:.1f}%] "
              f"D3[+{r['day3_max_rise']:.1f}%/-{r['day3_max_drop']:.1f}%]")

    # 统计：有多少BUY信号在D1/D3达到了正向目标
    cursor.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN signal_type='BUY' AND day1_max_rise > 1 THEN 1 ELSE 0 END) as d1_win,
            SUM(CASE WHEN signal_type='BUY' AND day3_max_rise > 2 THEN 1 ELSE 0 END) as d3_win,
            SUM(CASE WHEN signal_type='BUY' THEN 1 ELSE 0 END) as buy_total,
            AVG(CASE WHEN signal_type='BUY' THEN day1_max_rise ELSE NULL END) as avg_d1_rise,
            AVG(CASE WHEN signal_type='BUY' THEN day1_max_drop ELSE NULL END) as avg_d1_drop,
            AVG(CASE WHEN signal_type='BUY' THEN day3_max_rise ELSE NULL END) as avg_d3_rise,
            AVG(CASE WHEN signal_type='BUY' THEN day3_max_drop ELSE NULL END) as avg_d3_drop
        FROM signal_performance
        WHERE tracking_status = 'completed'
        AND created_at >= datetime('now', '-14 days')
    """)
    stats = cursor.fetchone()
    if stats and stats['total'] > 0:
        print(f"\n  近14天追踪统计:")
        print(f"  总计: {stats['total']} | BUY信号: {stats['buy_total']}")
        if stats['buy_total'] and stats['buy_total'] > 0:
            print(f"  D1涨>1%胜率: {stats['d1_win']}/{stats['buy_total']} = "
                  f"{stats['d1_win']/stats['buy_total']*100:.0f}%")
            print(f"  D3涨>2%胜率: {stats['d3_win']}/{stats['buy_total']} = "
                  f"{stats['d3_win']/stats['buy_total']*100:.0f}%")
            print(f"  BUY平均: D1涨{stats['avg_d1_rise']:.2f}%/跌{stats['avg_d1_drop']:.2f}% "
                  f"D3涨{stats['avg_d3_rise']:.2f}%/跌{stats['avg_d3_drop']:.2f}%")

    # ==================== 5. 决策引擎日志分析 ====================
    print("\n" + "=" * 70)
    print("5. 门卫拦截统计（从signal_pipeline表）")
    print("=" * 70)
    
    cursor.execute("SELECT COUNT(*) FROM signal_pipeline")
    total_pipeline = cursor.fetchone()[0]
    print(f"signal_pipeline 总记录: {total_pipeline}")
    
    if total_pipeline > 0:
        cursor.execute("""
            SELECT final_action, COUNT(*) as cnt
            FROM signal_pipeline
            GROUP BY final_action
            ORDER BY cnt DESC
        """)
        for r in cursor.fetchall():
            print(f"  {r['final_action']}: {r['cnt']}")

    # ==================== 6. capital_flow_signals 资金信号 ====================
    print("\n" + "=" * 70)
    print("6. 资金流信号(capital_flow_signals)分析")
    print("=" * 70)

    cursor.execute("""
        SELECT stock_code, stock_name, signal_type, rule_name, price,
               confidence, created_at
        FROM capital_flow_signals
        WHERE created_at >= datetime('now', '-3 days')
        ORDER BY created_at DESC
        LIMIT 20
    """)
    cf_rows = cursor.fetchall()
    print(f"近3天资金信号: {len(cf_rows)}条\n")
    
    for r in cf_rows[:15]:
        print(f"  {r['created_at'][:16]} {r['stock_name']}({r['stock_code']}) "
              f"{r['signal_type']} rule={r['rule_name']} "
              f"price={r['price']:.3f} conf={r['confidence']}")

    conn.close()

if __name__ == "__main__":
    main()
