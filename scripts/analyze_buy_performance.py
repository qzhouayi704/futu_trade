#!/usr/bin/env python3
"""分析买入后的价格表现：买入后最大浮盈 vs 实际卖出价

核心目标：验证"买对了但没交好"的假设，量化利润流失原因
"""
import json
from collections import defaultdict
from datetime import datetime, timedelta

IN_PATH = "scripts/futu_real_trades.json"
OUT_PATH = "scripts/buy_performance_analysis.json"

with open(IN_PATH, 'r', encoding='utf-8') as f:
    data = json.load(f)

# 整理所有成交记录
all_deals = []
for key in ['today_deals', 'history_deals']:
    if key in data and isinstance(data[key], list):
        all_deals.extend(data[key])

# 按股票和日期分组
stock_day_deals = defaultdict(list)
for d in all_deals:
    code = d.get('code', '')
    time_str = d.get('create_time', '')
    if not code or not time_str:
        continue
    day = time_str[:10]
    stock_day_deals[(code, day)].append(d)

# 分析每只股票每天的买卖配对
result = {
    'summary': {},
    'per_stock': {},
    'trade_patterns': [],
    'daily_details': [],
}

total_potential = 0  # 理论最大利���
total_actual = 0     # 实际利润
total_missed = 0     # 流失利润
trade_count = 0
win_count = 0
loss_count = 0

per_stock_stats = defaultdict(lambda: {
    'potential': 0, 'actual': 0, 'missed': 0,
    'buy_count': 0, 'win_count': 0, 'loss_count': 0,
    'avg_hold_seconds': 0, 'hold_times': [],
    'patterns': [],
})

for (code, day), deals in sorted(stock_day_deals.items()):
    deals_sorted = sorted(deals, key=lambda x: x.get('create_time', ''))
    
    buys = [d for d in deals_sorted if d.get('trd_side') == 'BUY']
    sells = [d for d in deals_sorted if d.get('trd_side') == 'SELL']
    
    if not buys:
        continue
    
    # 获取当天所有成交价格序列（用作日内价格参考）
    all_prices = []
    for d in deals_sorted:
        try:
            t = datetime.strptime(d['create_time'][:19], '%Y-%m-%d %H:%M:%S')
            p = float(d['price'])
            all_prices.append((t, p, d['trd_side']))
        except:
            pass
    
    if not all_prices:
        continue
    
    day_high = max(p for _, p, _ in all_prices)
    day_low = min(p for _, p, _ in all_prices)
    
    # FIFO配对：每笔买入配对到下一笔卖出
    sell_queue = list(sells)  # 复制
    sell_idx = 0
    
    for buy in buys:
        buy_price = float(buy['price'])
        buy_qty = float(buy['qty'])
        buy_time_str = buy['create_time'][:19]
        try:
            buy_time = datetime.strptime(buy_time_str, '%Y-%m-%d %H:%M:%S')
        except:
            continue
        
        # 找到买入之后的最高价（从成交记录推算）
        prices_after_buy = [p for t, p, _ in all_prices if t >= buy_time]
        max_price_after = max(prices_after_buy) if prices_after_buy else buy_price
        min_price_after = min(prices_after_buy) if prices_after_buy else buy_price
        
        # 配对卖出（FIFO：找买入之后最近的卖出）
        matched_sell = None
        for i in range(sell_idx, len(sell_queue)):
            s = sell_queue[i]
            try:
                sell_time = datetime.strptime(s['create_time'][:19], '%Y-%m-%d %H:%M:%S')
            except:
                continue
            if sell_time >= buy_time:
                matched_sell = s
                sell_idx = i + 1
                break
        
        if matched_sell:
            sell_price = float(matched_sell['price'])
            sell_qty = float(matched_sell['qty'])
            sell_time_str = matched_sell['create_time'][:19]
            try:
                sell_time = datetime.strptime(sell_time_str, '%Y-%m-%d %H:%M:%S')
            except:
                sell_time = buy_time
            
            hold_seconds = (sell_time - buy_time).total_seconds()
            
            # 计算
            actual_pnl = (sell_price - buy_price) * min(buy_qty, sell_qty)
            potential_pnl = (max_price_after - buy_price) * min(buy_qty, sell_qty)
            missed_pnl = potential_pnl - actual_pnl
            actual_pct = (sell_price - buy_price) / buy_price * 100
            potential_pct = (max_price_after - buy_price) / buy_price * 100
            max_drawdown_pct = (min_price_after - buy_price) / buy_price * 100
            
            pattern = {
                'code': code,
                'stock_name': buy.get('stock_name', code),
                'date': day,
                'buy_price': buy_price,
                'buy_time': buy_time_str,
                'sell_price': sell_price,
                'sell_time': sell_time_str,
                'max_price_after_buy': round(max_price_after, 3),
                'min_price_after_buy': round(min_price_after, 3),
                'hold_seconds': hold_seconds,
                'hold_minutes': round(hold_seconds / 60, 1),
                'actual_pnl': round(actual_pnl, 2),
                'actual_pct': round(actual_pct, 2),
                'potential_pnl': round(potential_pnl, 2),
                'potential_pct': round(potential_pct, 2),
                'missed_pnl': round(missed_pnl, 2),
                'max_drawdown_pct': round(max_drawdown_pct, 2),
                'capture_ratio': round(actual_pnl / potential_pnl * 100, 1) if potential_pnl > 0 else 0,
                'was_profitable_entry': potential_pct > 0,
                'result': 'WIN' if actual_pnl > 0 else 'LOSS',
            }
            
            total_potential += potential_pnl
            total_actual += actual_pnl
            total_missed += missed_pnl
            trade_count += 1
            if actual_pnl > 0:
                win_count += 1
            else:
                loss_count += 1
            
            s = per_stock_stats[code]
            s['potential'] += potential_pnl
            s['actual'] += actual_pnl
            s['missed'] += missed_pnl
            s['buy_count'] += 1
            s['hold_times'].append(hold_seconds)
            s['patterns'].append(pattern)
            if actual_pnl > 0:
                s['win_count'] += 1
            else:
                s['loss_count'] += 1
            
            result['trade_patterns'].append(pattern)

# 汇总
profitable_entries = sum(1 for p in result['trade_patterns'] if p['was_profitable_entry'])

result['summary'] = {
    'total_trades': trade_count,
    'win_count': win_count,
    'loss_count': loss_count,
    'win_rate': round(win_count / trade_count * 100, 1) if trade_count > 0 else 0,
    'profitable_entries': profitable_entries,
    'profitable_entry_rate': round(profitable_entries / trade_count * 100, 1) if trade_count > 0 else 0,
    'total_actual_pnl': round(total_actual, 2),
    'total_potential_pnl': round(total_potential, 2),
    'total_missed_pnl': round(total_missed, 2),
    'overall_capture_ratio': round(total_actual / total_potential * 100, 1) if total_potential > 0 else 0,
    'avg_hold_minutes': round(
        sum(p['hold_seconds'] for p in result['trade_patterns']) / len(result['trade_patterns']) / 60, 1
    ) if result['trade_patterns'] else 0,
}

# 每只股票汇总
for code, s in per_stock_stats.items():
    avg_hold = sum(s['hold_times']) / len(s['hold_times']) / 60 if s['hold_times'] else 0
    name = s['patterns'][0]['stock_name'] if s['patterns'] else code
    result['per_stock'][code] = {
        'name': name,
        'buy_count': s['buy_count'],
        'win_count': s['win_count'],
        'loss_count': s['loss_count'],
        'win_rate': round(s['win_count'] / s['buy_count'] * 100, 1) if s['buy_count'] > 0 else 0,
        'actual_pnl': round(s['actual'], 2),
        'potential_pnl': round(s['potential'], 2),
        'missed_pnl': round(s['missed'], 2),
        'capture_ratio': round(s['actual'] / s['potential'] * 100, 1) if s['potential'] > 0 else 0,
        'avg_hold_minutes': round(avg_hold, 1),
    }

# 分析亏损模式
loss_patterns = [p for p in result['trade_patterns'] if p['result'] == 'LOSS']
if loss_patterns:
    # 分类亏损原因
    too_early_exit = [p for p in loss_patterns if p['was_profitable_entry'] and p['actual_pnl'] < 0]
    wrong_direction = [p for p in loss_patterns if not p['was_profitable_entry']]
    panic_sell = [p for p in loss_patterns if p['hold_seconds'] < 120]  # 2分钟内卖出
    
    result['loss_analysis'] = {
        'total_losses': len(loss_patterns),
        'too_early_exit': len(too_early_exit),
        'too_early_exit_pct': round(len(too_early_exit) / len(loss_patterns) * 100, 1),
        'wrong_direction': len(wrong_direction),
        'wrong_direction_pct': round(len(wrong_direction) / len(loss_patterns) * 100, 1),
        'panic_sell_under_2min': len(panic_sell),
        'panic_sell_pct': round(len(panic_sell) / len(loss_patterns) * 100, 1),
        'avg_loss_hold_minutes': round(
            sum(p['hold_seconds'] for p in loss_patterns) / len(loss_patterns) / 60, 1
        ),
    }

# 按持仓时间分组
hold_buckets = {'0-2min': [], '2-5min': [], '5-15min': [], '15-60min': [], '60min+': []}
for p in result['trade_patterns']:
    m = p['hold_minutes']
    if m < 2:
        hold_buckets['0-2min'].append(p)
    elif m < 5:
        hold_buckets['2-5min'].append(p)
    elif m < 15:
        hold_buckets['5-15min'].append(p)
    elif m < 60:
        hold_buckets['15-60min'].append(p)
    else:
        hold_buckets['60min+'].append(p)

result['hold_time_analysis'] = {}
for bucket, trades in hold_buckets.items():
    if trades:
        wins = sum(1 for t in trades if t['actual_pnl'] > 0)
        result['hold_time_analysis'][bucket] = {
            'count': len(trades),
            'win_rate': round(wins / len(trades) * 100, 1),
            'avg_actual_pct': round(sum(t['actual_pct'] for t in trades) / len(trades), 2),
            'avg_potential_pct': round(sum(t['potential_pct'] for t in trades) / len(trades), 2),
            'avg_capture_ratio': round(sum(t['capture_ratio'] for t in trades) / len(trades), 1),
        }

with open(OUT_PATH, 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"Analysis complete. {trade_count} trades analyzed.")
print(f"Output: {OUT_PATH}")
