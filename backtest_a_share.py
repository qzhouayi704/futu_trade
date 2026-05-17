#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股回测脚本 - 验证港股趋势反转策略在A股的适用性

使用akshare获取A股历史数据，复用系统的：
1. 趋势反转策略（买入/卖出信号）
2. 6维度评分系统
3. 组合止损/止盈规则

回测标的：AI芯片/半导体板块代表股
"""

import sys
import os
import json
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.WARNING, format='%(message)s')

# ══════════════════════════════════════════════════════════════
# 第一部分：数据获取（akshare）
# ══════════════════════════════════════════════════════════════

def fetch_kline_data(symbol: str, start_date: str, end_date: str) -> List[Dict]:
    """使用腾讯财经API获取A股日K线（东方财富API不可用时的备选）"""
    import requests
    import time

    # 腾讯格式: sz300474 / sh688256
    prefix = "sh" if symbol.startswith(('6',)) else "sz"
    tencent_code = f"{prefix}{symbol}"

    # 腾讯API每次最多返回约640条，足够1年数据
    sd = start_date.replace('-', '')
    ed = end_date.replace('-', '')
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    params = {
        "param": f"{tencent_code},day,{sd[:4]}-{sd[4:6]}-{sd[6:]},{ed[:4]}-{ed[4:6]}-{ed[6:]},640,qfq",
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
    except Exception as e:
        print(f"获取 {symbol} 数据失败: {e}")
        return []

    # 腾讯返回格式: data -> {code} -> qfqday/day -> [[日期,开,收,高,低,成交量], ...]
    stock_data = data.get("data", {}).get(tencent_code, {})
    raw_klines = stock_data.get("qfqday") or stock_data.get("day")
    if not raw_klines:
        print(f"获取 {symbol} 无K线数据")
        return []

    klines = []
    for row in raw_klines:
        if len(row) < 6:
            continue
        klines.append({
            'time_key': row[0],
            'open': float(row[1]),
            'close': float(row[2]),
            'high': float(row[3]),
            'low': float(row[4]),
            'volume': float(row[5]) * 100 if float(row[5]) < 1e6 else float(row[5]),  # 腾讯可能是手/股
            'turnover': 0,
            'turnover_rate': 1.0,  # 腾讯不返回换手率，用默认值
        })

    time.sleep(0.3)  # 限速
    return klines


# ══════════════════════════════════════════════════════════════
# 第二部分：策略复刻（独立实现，不依赖系统import）
# ══════════════════════════════════════════════════════════════

@dataclass
class TrendAnalysis:
    up_days: int = 0
    down_days: int = 0
    flat_days: int = 0
    up_ratio: float = 0.0
    down_ratio: float = 0.0
    period_high: float = 0.0
    period_low: float = 0.0
    current_price: float = 0.0
    drop_from_high: float = 0.0
    rise_from_low: float = 0.0
    trend_direction: str = ""
    trend_strength: float = 0.0
    reversal_signal: float = 0.0
    is_buy_reversal: bool = False
    is_sell_reversal: bool = False
    volume_trend: str = ""
    avg_volume_ratio: float = 1.0
    reversal_volume_ratio: float = 1.0
    turnover_rate: float = 0.0


def analyze_trend(lookback_data, current_price, current_high, current_low, current_open):
    """复刻 analysis.py 的趋势分析"""
    trend = TrendAnalysis()
    trend.current_price = current_price
    if not lookback_data:
        return trend

    last_candle = lookback_data[-1]
    ref_price = last_candle.get('close', current_price)
    ref_open = last_candle.get('open', 0)

    for day in lookback_data:
        c, o = day.get('close', 0), day.get('open', 0)
        if c > o: trend.up_days += 1
        elif c < o: trend.down_days += 1
        else: trend.flat_days += 1

    total = len(lookback_data)
    trend.up_ratio = trend.up_days / total if total > 0 else 0
    trend.down_ratio = trend.down_days / total if total > 0 else 0

    highs = [d.get('high', 0) for d in lookback_data]
    lows = [d.get('low', 0) for d in lookback_data]
    trend.period_high = max(highs) if highs else 0
    trend.period_low = min(lows) if lows else 0

    if trend.period_high > 0:
        trend.drop_from_high = ((trend.period_high - ref_price) / trend.period_high) * 100
    if trend.period_low > 0:
        trend.rise_from_low = ((ref_price - trend.period_low) / trend.period_low) * 100

    if trend.down_ratio >= 0.6:
        trend.trend_direction = "DOWN"
        trend.trend_strength = trend.down_ratio
    elif trend.up_ratio >= 0.6:
        trend.trend_direction = "UP"
        trend.trend_strength = trend.up_ratio
    else:
        trend.trend_direction = "SIDEWAYS"
        trend.trend_strength = max(trend.up_ratio, trend.down_ratio)

    yesterday_is_up = ref_price > ref_open if ref_open > 0 else False
    if trend.trend_direction == "DOWN" and yesterday_is_up:
        trend.reversal_signal = trend.rise_from_low
        trend.is_buy_reversal = True
    elif trend.trend_direction == "UP" and not yesterday_is_up:
        trend.reversal_signal = trend.drop_from_high
        trend.is_sell_reversal = True

    # 量价分析
    volumes = [d.get('volume', 0) for d in lookback_data]
    if volumes and any(v > 0 for v in volumes):
        avg_vol = sum(volumes) / len(volumes)
        if avg_vol > 0:
            down_vols, up_vols = [], []
            for d in lookback_data:
                v = d.get('volume', 0)
                if d.get('close', 0) < d.get('open', 0): down_vols.append(v)
                elif d.get('close', 0) > d.get('open', 0): up_vols.append(v)
            avg_down = sum(down_vols) / len(down_vols) if down_vols else avg_vol
            last_up = up_vols[-1] if up_vols else 0
            trend.reversal_volume_ratio = last_up / avg_down if avg_down > 0 else 1.0
            recent_avg = sum(volumes[-2:]) / min(2, len(volumes[-2:]))
            trend.avg_volume_ratio = recent_avg / avg_vol if avg_vol > 0 else 1.0

    return trend


# ══════════════════════════════════════════════════════════════
# 第三部分：策略参数（复刻系统默认值）
# ══════════════════════════════════════════��═══════════════════

STRATEGY_PARAMS = {
    'lookback_days': 10,
    'min_drop_pct': 8.0,
    'min_rise_pct': 10.0,
    'min_reversal_pct': 2.0,
    'max_up_ratio_buy': 0.4,
    'min_up_ratio_sell': 0.6,
    'stop_loss_pct': -10.0,
    'stop_loss_days': 5,
    'trailing_activate_pct': 8.0,
    'trailing_drawdown_pct': 3.0,
    'max_hold_days': 15,
    'min_turnover_rate': 0.1,
}

# 6维度评分配置
SCORE_CONFIG = {
    'trend_5d': {'max': 30, 'tiers': [(10.0, 30), (5.0, 25), (2.0, 20), (0.0, 10)]},
    'kline_pos': {'max': 20, 'optimal': (0.3, 0.8), 'marginal': (0.2, 0.9)},
    'amplitude': {'max': 15, 'optimal': (8.0, 35.0), 'marginal': (5.0, 45.0)},
    'vol_ratio': {'max': 15, 'tiers': [(2.0, 15), (1.5, 10), (1.0, 5)]},
    'prev_change': {'max': 10, 'tiers': [(5.0, 10), (10.0, 5)]},
    'capital_flow': {'max': 10, 'tiers': [(0.3, 10), (0.0, 5)]},
}


def calc_score(klines, idx):
    """计算第idx天的6维度评分"""
    if idx < 5:
        return 0, False

    # 5日涨幅
    change_5d = ((klines[idx]['close'] - klines[idx-5]['close']) / klines[idx-5]['close']) * 100
    score = 0
    for threshold, pts in SCORE_CONFIG['trend_5d']['tiers']:
        if change_5d >= threshold:
            score += pts; break

    # K线20日位置
    if idx >= 20:
        h20 = max(d['high'] for d in klines[idx-20:idx+1])
        l20 = min(d['low'] for d in klines[idx-20:idx+1])
        kpos = (klines[idx]['close'] - l20) / (h20 - l20) if h20 > l20 else 0.5
        opt = SCORE_CONFIG['kline_pos']['optimal']
        mar = SCORE_CONFIG['kline_pos']['marginal']
        if opt[0] <= kpos <= opt[1]: score += 20
        elif mar[0] <= kpos <= mar[1]: score += 10

    # 日振幅
    amp = ((klines[idx]['high'] - klines[idx]['low']) / klines[idx]['low']) * 100 if klines[idx]['low'] > 0 else 0
    opt = SCORE_CONFIG['amplitude']['optimal']
    mar = SCORE_CONFIG['amplitude']['marginal']
    if opt[0] <= amp <= opt[1]: score += 15
    elif mar[0] <= amp <= mar[1]: score += 8

    # 量比
    if idx >= 5:
        avg_vol_5 = sum(d['volume'] for d in klines[idx-5:idx]) / 5
        vr = klines[idx]['volume'] / avg_vol_5 if avg_vol_5 > 0 else 1.0
        for threshold, pts in SCORE_CONFIG['vol_ratio']['tiers']:
            if vr >= threshold:
                score += pts; break

    # 前日涨幅（反向）
    prev_chg = ((klines[idx]['close'] - klines[idx-1]['close']) / klines[idx-1]['close']) * 100
    for threshold, pts in SCORE_CONFIG['prev_change']['tiers']:
        if abs(prev_chg) <= threshold:
            score += pts; break

    # 一票否决
    veto = False
    if abs(prev_chg) > 20: veto = True
    if amp > 45: veto = True

    return score, veto


# ══════════════════════════════════════════════════════════════
# 第四部分：回测引擎
# ══════════════════════════════════════════════════════════════

@dataclass
class Trade:
    stock: str
    buy_date: str
    buy_price: float
    sell_date: str = ""
    sell_price: float = 0.0
    return_pct: float = 0.0
    hold_days: int = 0
    exit_type: str = ""
    score: int = 0


def check_buy_signal(trend, params):
    """复刻策略的买入信号检测（6条件，核心2+3必须，总共≥4）"""
    met = 0
    c1 = trend.down_ratio >= (1 - params['max_up_ratio_buy'])
    if c1: met += 1
    c2 = trend.drop_from_high >= params['min_drop_pct']
    if c2: met += 1
    c3 = trend.rise_from_low >= params['min_reversal_pct']
    if c3: met += 1
    c4 = trend.is_buy_reversal
    if c4: met += 1
    c5 = trend.reversal_volume_ratio >= 1.2
    if c5: met += 1
    c6 = trend.turnover_rate >= params['min_turnover_rate']
    if c6: met += 1
    return met >= 4 and c2 and c3


def check_exit(buy_price, klines_since_buy, current_day, params):
    """复刻组合卖出检查"""
    current_price = current_day['close']
    current_high = current_day['high']
    ret_pct = ((current_price - buy_price) / buy_price) * 100
    days_held = len(klines_since_buy)

    # 峰值计算
    peak = buy_price
    for d in klines_since_buy:
        if d['high'] > peak: peak = d['high']
    if current_high > peak: peak = current_high
    peak_ret = ((peak - buy_price) / buy_price) * 100
    drawdown = ((peak - current_price) / peak) * 100 if peak > 0 else 0
    trailing_active = peak_ret >= params['trailing_activate_pct']

    # 1. 固定止损
    if ret_pct <= params['stop_loss_pct']:
        return True, ret_pct, 'stop_loss'

    # 2. T+5 趋势未延续
    if days_held >= params['stop_loss_days']:
        up_days = sum(1 for d in klines_since_buy if d['close'] > d['open'])
        if days_held == params['stop_loss_days'] and ret_pct < 0 and up_days < 1:
            return True, ret_pct, 'trend_fail'

    # 3. 追踪止盈
    if trailing_active and drawdown >= params['trailing_drawdown_pct']:
        return True, ret_pct, 'trailing'

    # 4. 高抛兜底
    if not trailing_active and days_held > params['stop_loss_days'] and klines_since_buy:
        yesterday_high = klines_since_buy[-1]['high']
        lookback = min(12, len(klines_since_buy))
        period_highs = [d['high'] for d in klines_since_buy[-lookback:]]
        if current_high < yesterday_high and yesterday_high == max(period_highs):
            return True, ret_pct, 'high_throw'

    # 5. 超时退出
    if days_held >= params['max_hold_days']:
        return True, ret_pct, 'timeout'

    return False, ret_pct, ''


def run_backtest(stock_code: str, stock_name: str, klines: List[Dict], params: dict) -> List[Trade]:
    """对单只股票执行回测"""
    trades = []
    lookback = params['lookback_days']
    in_position = False
    buy_price = 0.0
    buy_date = ""
    buy_idx = 0

    for i in range(lookback, len(klines)):
        day = klines[i]

        if in_position:
            klines_since = klines[buy_idx+1:i]
            should_exit, ret_pct, exit_type = check_exit(buy_price, klines_since, day, params)
            if should_exit:
                trades[-1].sell_date = day['time_key']
                trades[-1].sell_price = day['close']
                trades[-1].return_pct = ret_pct
                trades[-1].hold_days = i - buy_idx
                trades[-1].exit_type = exit_type
                in_position = False
        else:
            # 检查买入信号
            lookback_data = klines[i-lookback:i]
            trend = analyze_trend(lookback_data, day['close'], day['high'], day['low'], day['open'])
            trend.turnover_rate = day.get('turnover_rate', 1.0)

            if check_buy_signal(trend, params):
                score, veto = calc_score(klines, i)
                if not veto and score >= 60:
                    in_position = True
                    buy_price = day['close']
                    buy_date = day['time_key']
                    buy_idx = i
                    trades.append(Trade(
                        stock=f"{stock_name}({stock_code})",
                        buy_date=buy_date,
                        buy_price=buy_price,
                        score=score,
                    ))

    # 清理未平仓
    if in_position and trades:
        last = klines[-1]
        trades[-1].sell_date = last['time_key'] + "(未平)"
        trades[-1].sell_price = last['close']
        trades[-1].return_pct = ((last['close'] - buy_price) / buy_price) * 100
        trades[-1].hold_days = len(klines) - buy_idx
        trades[-1].exit_type = 'open'

    return trades


# ══════════════════════════════════════════════════════════════
# 第五部分：报告生成
# ══════════════════════════════════════════════════════════════

def print_report(all_trades: List[Trade], stock_list: List[tuple]):
    """输出回测报告"""
    print("\n" + "="*80)
    print("  A股回测报告 — 港股趋势反转策略适用性验证")
    print("="*80)

    if not all_trades:
        print("\n⚠️ 未产生任何交易信号")
        return

    # 总体统计
    closed = [t for t in all_trades if t.exit_type != 'open']
    wins = [t for t in closed if t.return_pct > 0]
    losses = [t for t in closed if t.return_pct <= 0]

    total_return = sum(t.return_pct for t in closed)
    avg_return = total_return / len(closed) if closed else 0
    win_rate = len(wins) / len(closed) * 100 if closed else 0
    avg_win = sum(t.return_pct for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t.return_pct for t in losses) / len(losses) if losses else 0
    avg_hold = sum(t.hold_days for t in closed) / len(closed) if closed else 0
    profit_factor = abs(sum(t.return_pct for t in wins) / sum(t.return_pct for t in losses)) if losses and sum(t.return_pct for t in losses) != 0 else float('inf')

    print(f"\n📊 总体统计")
    print(f"  回测标的数: {len(stock_list)}")
    print(f"  总交易次数: {len(closed)} (未平仓: {len(all_trades)-len(closed)})")
    print(f"  胜率: {win_rate:.1f}%")
    print(f"  盈利笔数: {len(wins)}  |  亏损笔数: {len(losses)}")
    print(f"  累计收益: {total_return:.2f}%")
    print(f"  平均收益: {avg_return:.2f}%")
    print(f"  平均盈利: +{avg_win:.2f}%  |  平均亏损: {avg_loss:.2f}%")
    print(f"  盈亏比: {profit_factor:.2f}")
    print(f"  平均持仓天数: {avg_hold:.1f}")

    # 退出类型分布
    exit_types = {}
    for t in closed:
        exit_types[t.exit_type] = exit_types.get(t.exit_type, 0) + 1
    type_names = {
        'stop_loss': '固定止损', 'trend_fail': 'T+5趋势未延续',
        'trailing': '追踪止盈', 'high_throw': '高抛兜底', 'timeout': '超时退出',
    }
    print(f"\n📈 退出类型分布")
    for et, cnt in sorted(exit_types.items(), key=lambda x: -x[1]):
        name = type_names.get(et, et)
        et_trades = [t for t in closed if t.exit_type == et]
        et_avg = sum(t.return_pct for t in et_trades) / len(et_trades)
        print(f"  {name}: {cnt}笔 (平均收益: {et_avg:+.2f}%)")

    # 评分分组统计
    print(f"\n🎯 评分分组胜率（对比港股回测基准）")
    print(f"  {'分数段':<12} {'A股笔数':<8} {'A股胜率':<10} {'港股基准胜率':<12} {'差异'}")
    score_groups = [(80, 100, '80-100分', '58%'), (60, 79, '60-79分', '47%'), (0, 59, '<60分', '33%')]
    for lo, hi, label, hk_base in score_groups:
        group = [t for t in closed if lo <= t.score <= hi]
        if group:
            g_wins = len([t for t in group if t.return_pct > 0])
            g_wr = g_wins / len(group) * 100
            hk_val = float(hk_base.strip('%'))
            diff = g_wr - hk_val
            marker = "✅" if diff >= 0 else "⚠️"
            print(f"  {label:<12} {len(group):<8} {g_wr:.1f}%{'':>4} {hk_base:<12} {diff:+.1f}% {marker}")
        else:
            print(f"  {label:<12} {'0':<8} {'N/A':<10} {hk_base:<12} {'N/A'}")

    # 个股明细
    print(f"\n📋 交易明细")
    print(f"  {'标的':<20} {'买入日期':<12} {'卖出日期':<14} {'评分':<6} {'收益':<10} {'持仓':<6} {'退出'}")
    print(f"  {'-'*90}")
    for t in all_trades:
        ret_str = f"{t.return_pct:+.2f}%" if t.return_pct else "N/A"
        exit_name = type_names.get(t.exit_type, t.exit_type)
        marker = "🟢" if t.return_pct > 0 else "🔴" if t.return_pct < 0 else "⚪"
        print(f"  {marker} {t.stock:<18} {t.buy_date:<12} {t.sell_date:<14} {t.score:<6} {ret_str:<10} {t.hold_days}天{'':>3} {exit_name}")

    # 结论
    print(f"\n{'='*80}")
    print(f"  📌 结论")
    if win_rate >= 47:
        print(f"  ✅ 策略在A股表现良好，胜率{win_rate:.1f}% ≥ 港股基准47%")
    elif win_rate >= 40:
        print(f"  ⚠️ 策略在A股表现一般，胜率{win_rate:.1f}%，低于港股基准47%，需调参")
    else:
        print(f"  ❌ 策略在A股表现不佳，胜率{win_rate:.1f}%，不适合直接套用")

    if avg_hold > 10:
        print(f"  ⚠️ 平均持仓{avg_hold:.1f}天偏长，A股T+1限制下资金效率低")
    if profit_factor < 1.0:
        print(f"  ❌ 盈亏比{profit_factor:.2f}<1，亏损大于盈利，策略需优化")
    elif profit_factor >= 1.5:
        print(f"  ✅ 盈亏比{profit_factor:.2f}健康")

    print(f"\n  💡 A股 vs 港股关键差异：")
    print(f"     - A股T+1，无法当日止损 → 建议收紧止损阈值")
    print(f"     - A股涨跌停板±10%/±20% → 振幅和前日涨幅阈值需调整")
    print(f"     - A股散户占比高 → 量价信号可能更有效")
    print(f"{'='*80}\n")


# ══════════════════════════════════════════════════════════════
# 第六部分：主入口
# ══════════════════════════════════════════════════════════════

# 回测标的：AI芯片/半导体 + 几只典型A股
STOCK_LIST = [
    ("300474", "景嘉微"),
    ("688256", "寒武纪"),
    ("688262", "国芯科技"),
    ("002049", "紫光国微"),
    ("688521", "芯原股份"),
    ("603501", "韦尔股份"),
    ("688008", "澜起科技"),
    ("002371", "北方华创"),
    ("300661", "圣邦股份"),
    ("688012", "中微公司"),
]

# 回测参数（可以对比港股原版 vs A股调参版）
PARAM_SETS = {
    '港股原版': STRATEGY_PARAMS.copy(),
    'A股调参版': {
        **STRATEGY_PARAMS,
        'stop_loss_pct': -8.0,       # 收紧止损（T+1无法当日止损）
        'min_drop_pct': 6.0,         # 降低跌幅���求（涨跌停限制）
        'trailing_activate_pct': 6.0, # 降低追踪止盈激活（A股波动小）
        'trailing_drawdown_pct': 2.5, # 收紧回撤（A股波动小）
        'max_hold_days': 10,          # 缩短持仓（A股T+1资金效率）
    },
}


def main():
    # 回测区间：最近1年
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=365)).strftime('%Y%m%d')

    print(f"🚀 开始A股回测...")
    print(f"   区间: {start_date} ~ {end_date}")
    print(f"   标的: {len(STOCK_LIST)}只")
    print(f"   参数组: {list(PARAM_SETS.keys())}")

    for param_name, params in PARAM_SETS.items():
        print(f"\n{'━'*80}")
        print(f"  参数组: {param_name}")
        print(f"{'━'*80}")

        all_trades = []
        for code, name in STOCK_LIST:
            print(f"  获取数据: {name}({code})...", end="", flush=True)
            klines = fetch_kline_data(code, start_date, end_date)
            if not klines:
                print(" ❌ 无数据")
                continue
            print(f" ✓ {len(klines)}根K线", end="")

            trades = run_backtest(code, name, klines, params)
            all_trades.extend(trades)
            print(f"  → {len(trades)}笔交易")

        print_report(all_trades, STOCK_LIST)


if __name__ == '__main__':
    main()
