#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
开盘类型回测分析

将个股开盘涨跌幅分为三类：
- 高开 (gap_up):   open_price > prev_close * (1 + threshold)
- 平开 (flat):     |open_price - prev_close| / prev_close <= threshold
- 低开 (gap_down): open_price < prev_close * (1 - threshold)

对每种开盘类型分别测试：
1. 主锚点(prev_close)策略的表现
2. 开盘价锚点策略的表现
3. 不同参数组合下的最优结果

这样可以看出：高开时用开盘价锚点是否比主锚点好，
低开时是否应该用更大的买入跌幅等。
"""

import sys
import os
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from datetime import datetime
from simple_trade.database.core.db_manager import DatabaseManager
from simple_trade.config.config import Config
from simple_trade.backtest.core.loaders.backtest_only_loader import BacktestOnlyDataLoader
from simple_trade.backtest.core.fee_calculator import FeeCalculator
from simple_trade.backtest.strategies.price_position_strategy import (
    PricePositionStrategy, TARGET_STOCKS, ZONE_NAMES,
)

# 开盘类型阈值
GAP_THRESHOLD = 0.5  # ±0.5% 以内算平开


def classify_open_type(open_price, prev_close, threshold=GAP_THRESHOLD):
    """分类开盘类型"""
    if prev_close <= 0:
        return 'flat'
    gap_pct = (open_price - prev_close) / prev_close * 100
    if gap_pct > threshold:
        return 'gap_up'
    elif gap_pct < -threshold:
        return 'gap_down'
    else:
        return 'flat'


def simulate_with_anchor(metric, buy_dip_pct, sell_rise_pct, stop_loss_pct,
                         anchor='prev_close', fee_calculator=None, trade_amount=60000.0):
    """
    对单条 metric 模拟交易，指定锚点类型

    anchor='prev_close': 买入价 = prev_close * (1 - buy_dip/100)
    anchor='open_price': 买入价 = open_price * (1 - buy_dip/100)
    """
    prev_close = metric['prev_close']
    open_price = metric.get('open_price', 0)

    if anchor == 'open_price' and open_price > 0:
        base_price = open_price
    else:
        base_price = prev_close

    buy_price = base_price * (1 - buy_dip_pct / 100)
    sell_target = base_price * (1 + sell_rise_pct / 100)
    stop_price = buy_price * (1 - stop_loss_pct / 100)

    # 是否触发买入
    if metric['low_price'] > buy_price:
        return None  # 未触发

    # 退出判断
    if metric['low_price'] <= stop_price:
        sell_price = stop_price
        exit_type = 'stop_loss'
    elif metric['high_price'] >= sell_target:
        sell_price = sell_target
        exit_type = 'profit'
    else:
        sell_price = metric['close_price']
        exit_type = 'close'

    profit_pct = (sell_price - buy_price) / buy_price * 100

    # 费用
    buy_fee = 0.0
    sell_fee = 0.0
    net_profit_pct = profit_pct
    if fee_calculator is not None and trade_amount > 0:
        buy_fee_detail = fee_calculator.calculate_hk_fee(trade_amount, is_buy=True)
        sell_amount = trade_amount * (1 + profit_pct / 100)
        sell_fee_detail = fee_calculator.calculate_hk_fee(sell_amount, is_buy=False)
        buy_fee = buy_fee_detail.total
        sell_fee = sell_fee_detail.total
        total_fee = buy_fee + sell_fee
        net_profit_pct = ((sell_amount - trade_amount - total_fee) / trade_amount) * 100

    return {
        'profit_pct': round(profit_pct, 4),
        'net_profit_pct': round(net_profit_pct, 4),
        'exit_type': exit_type,
        'anchor': anchor,
        'buy_price': round(buy_price, 3),
        'sell_price': round(sell_price, 3),
    }


def main():
    config = Config()
    db_manager = DatabaseManager(config.database_path)
    data_loader = BacktestOnlyDataLoader(
        db_manager, market='HK',
        use_stock_pool_only=False,
        only_stocks_with_kline=False,
        min_kline_days=15
    )
    fee_calculator = FeeCalculator()
    strategy = PricePositionStrategy()

    start_dt = datetime(2025, 2, 6)
    end_dt = datetime(2026, 2, 6)

    print(f"回测时间: {start_dt.date()} ~ {end_dt.date()}")
    print(f"开盘类型阈值: ±{GAP_THRESHOLD}%")
    print(f"目标股票: {len(TARGET_STOCKS)} 只\n")

    # 收集所有股票的 metrics
    all_metrics = []
    all_trade_params = {}

    for stock_code in TARGET_STOCKS:
        kline_df = data_loader.load_kline_data(stock_code, start_dt, end_dt)
        if kline_df is None or kline_df.empty:
            continue

        kline_list = kline_df.to_dict('records')
        for k in kline_list:
            k['stock_code'] = stock_code

        metrics = strategy.calculate_daily_metrics(kline_list)
        if not metrics:
            continue

        # 为每条 metric 添加开盘类型
        for m in metrics:
            m['open_type'] = classify_open_type(m['open_price'], m['prev_close'])
            m['open_gap_pct'] = round((m['open_price'] - m['prev_close']) / m['prev_close'] * 100, 4) if m['prev_close'] > 0 else 0

        # 网格搜索最优参数
        zone_stats = strategy.compute_zone_statistics(metrics)
        grid_results = strategy.optimize_params_grid(
            metrics, zone_stats,
            fee_calculator=fee_calculator,
            trade_amount=60000.0,
        )

        trade_params = {}
        for zn in ZONE_NAMES:
            gr = grid_results.get(zn, {})
            best = gr.get('best_params', {})
            if best.get('buy_dip_pct', 0) > 0:
                trade_params[zn] = best
            else:
                trade_params[zn] = {'buy_dip_pct': 0, 'sell_rise_pct': 0, 'stop_loss_pct': 3.0}

        all_trade_params[stock_code] = trade_params
        all_metrics.extend(metrics)
        print(f"  {stock_code}: {len(metrics)} 天")

    print(f"\n总指标数据: {len(all_metrics)} 条")

    # ===== 统计开盘类型分布 =====
    gap_up = [m for m in all_metrics if m['open_type'] == 'gap_up']
    flat = [m for m in all_metrics if m['open_type'] == 'flat']
    gap_down = [m for m in all_metrics if m['open_type'] == 'gap_down']

    print(f"\n{'='*70}")
    print(f"一、开盘类型分布")
    print(f"{'='*70}")
    print(f"  高开(>{GAP_THRESHOLD}%):  {len(gap_up):5d} ({len(gap_up)/len(all_metrics)*100:.1f}%)")
    print(f"  平开(±{GAP_THRESHOLD}%):  {len(flat):5d} ({len(flat)/len(all_metrics)*100:.1f}%)")
    print(f"  低开(<-{GAP_THRESHOLD}%): {len(gap_down):5d} ({len(gap_down)/len(all_metrics)*100:.1f}%)")

    # ===== 对每种开盘类型，测试两种锚点 =====
    print(f"\n{'='*70}")
    print(f"二、各开盘类型下两种锚点的表现（使用各股票最优参数）")
    print(f"{'='*70}")

    for open_type, label, type_metrics in [
        ('gap_up', '高开', gap_up),
        ('flat', '平开', flat),
        ('gap_down', '低开', gap_down),
    ]:
        if not type_metrics:
            continue

        print(f"\n  --- {label} ({len(type_metrics)} 天) ---")

        for anchor in ['prev_close', 'open_price']:
            trades = []
            for m in type_metrics:
                stock_code = m['stock_code']
                params = all_trade_params.get(stock_code, {}).get(m['zone'], {})
                if params.get('buy_dip_pct', 0) <= 0:
                    continue

                result = simulate_with_anchor(
                    m, params['buy_dip_pct'], params['sell_rise_pct'], params['stop_loss_pct'],
                    anchor=anchor, fee_calculator=fee_calculator,
                )
                if result:
                    trades.append(result)

            if trades:
                total = len(trades)
                win = len([t for t in trades if t['net_profit_pct'] > 0])
                avg_net = sum(t['net_profit_pct'] for t in trades) / total
                sl = len([t for t in trades if t['exit_type'] == 'stop_loss'])
                profit_exits = len([t for t in trades if t['exit_type'] == 'profit'])
                anchor_label = '主锚点(prev_close)' if anchor == 'prev_close' else '开盘价锚点(open_price)'
                print(f"    {anchor_label}:")
                print(f"      触发: {total}, 胜率: {win/total*100:.1f}%, 净盈亏: {avg_net:.4f}%, 止盈: {profit_exits}({profit_exits/total*100:.1f}%), 止损: {sl}({sl/total*100:.1f}%)")
            else:
                anchor_label = '主锚点(prev_close)' if anchor == 'prev_close' else '开盘价锚点(open_price)'
                print(f"    {anchor_label}: 无触发交易")

    # ===== 高开日：网格搜索开盘价锚点最优参数 =====
    print(f"\n{'='*70}")
    print(f"三、高开日开盘价锚点参数网格搜索")
    print(f"{'='*70}")

    buy_range = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0]
    sell_range = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0]
    sl_range = [1.0, 1.5, 2.0, 2.5, 3.0]

    best_result = None
    best_params = None

    for buy_dip in buy_range:
        for sell_rise in sell_range:
            for sl in sl_range:
                trades = []
                for m in gap_up:
                    result = simulate_with_anchor(
                        m, buy_dip, sell_rise, sl,
                        anchor='open_price', fee_calculator=fee_calculator,
                    )
                    if result:
                        trades.append(result)

                if len(trades) < 10:
                    continue

                avg_net = sum(t['net_profit_pct'] for t in trades) / len(trades)
                win_rate = len([t for t in trades if t['net_profit_pct'] > 0]) / len(trades) * 100

                if best_result is None or avg_net > best_result:
                    best_result = avg_net
                    best_params = {
                        'buy_dip': buy_dip, 'sell_rise': sell_rise, 'sl': sl,
                        'trades': len(trades), 'avg_net': avg_net, 'win_rate': win_rate,
                    }

    if best_params:
        print(f"  最优参数: 买入回调={best_params['buy_dip']:.2f}%, 卖出涨幅={best_params['sell_rise']:.2f}%, 止损={best_params['sl']:.1f}%")
        print(f"  交易数: {best_params['trades']}, 净盈亏: {best_params['avg_net']:.4f}%, 胜率: {best_params['win_rate']:.1f}%")

    # ===== 按高开幅度细分 =====
    print(f"\n{'='*70}")
    print(f"四、高开幅度细分（开盘价锚点，使用最优参数）")
    print(f"{'='*70}")

    gap_ranges = [
        (0.5, 1.0, '高开0.5~1%'),
        (1.0, 2.0, '高开1~2%'),
        (2.0, 3.0, '高开2~3%'),
        (3.0, 100.0, '高开>3%'),
    ]

    if best_params:
        for low, high, label in gap_ranges:
            sub = [m for m in gap_up if low <= m['open_gap_pct'] < high]
            if not sub:
                print(f"  {label}: 无数据")
                continue

            trades = []
            for m in sub:
                result = simulate_with_anchor(
                    m, best_params['buy_dip'], best_params['sell_rise'], best_params['sl'],
                    anchor='open_price', fee_calculator=fee_calculator,
                )
                if result:
                    trades.append(result)

            if trades:
                total = len(trades)
                win = len([t for t in trades if t['net_profit_pct'] > 0])
                avg_net = sum(t['net_profit_pct'] for t in trades) / total
                print(f"  {label} ({len(sub)}天): 触发{total}, 胜率{win/total*100:.1f}%, 净盈亏{avg_net:.4f}%")
            else:
                print(f"  {label} ({len(sub)}天): 无触发")

    # ===== 低开日分析 =====
    print(f"\n{'='*70}")
    print(f"五、低开日主锚点参数网格搜索（是否需要更大的买入跌幅）")
    print(f"{'='*70}")

    best_gd_result = None
    best_gd_params = None

    for buy_dip in buy_range:
        for sell_rise in sell_range:
            for sl in sl_range:
                trades = []
                for m in gap_down:
                    result = simulate_with_anchor(
                        m, buy_dip, sell_rise, sl,
                        anchor='prev_close', fee_calculator=fee_calculator,
                    )
                    if result:
                        trades.append(result)

                if len(trades) < 10:
                    continue

                avg_net = sum(t['net_profit_pct'] for t in trades) / len(trades)
                win_rate = len([t for t in trades if t['net_profit_pct'] > 0]) / len(trades) * 100

                if best_gd_result is None or avg_net > best_gd_result:
                    best_gd_result = avg_net
                    best_gd_params = {
                        'buy_dip': buy_dip, 'sell_rise': sell_rise, 'sl': sl,
                        'trades': len(trades), 'avg_net': avg_net, 'win_rate': win_rate,
                    }

    if best_gd_params:
        print(f"  低开日最优: 买入跌幅={best_gd_params['buy_dip']:.2f}%, 卖出涨幅={best_gd_params['sell_rise']:.2f}%, 止损={best_gd_params['sl']:.1f}%")
        print(f"  交易数: {best_gd_params['trades']}, 净盈亏: {best_gd_params['avg_net']:.4f}%, 胜率: {best_gd_params['win_rate']:.1f}%")

    # ===== 总结 =====
    print(f"\n{'='*70}")
    print(f"六、总结：建议的开盘类型策略")
    print(f"{'='*70}")
    print(f"  高开(>{GAP_THRESHOLD}%): 用开盘价锚点", end="")
    if best_params:
        print(f" — 买入回调{best_params['buy_dip']:.1f}%, 卖出{best_params['sell_rise']:.1f}%, 止损{best_params['sl']:.1f}%")
    else:
        print(" — 无正收益参数")
    print(f"  平开(±{GAP_THRESHOLD}%): 用主锚点(prev_close) — 保持现有策略")
    print(f"  低开(<-{GAP_THRESHOLD}%): 用主锚点(prev_close)", end="")
    if best_gd_params:
        print(f" — 买入跌幅{best_gd_params['buy_dip']:.1f}%, 卖出{best_gd_params['sell_rise']:.1f}%, 止损{best_gd_params['sl']:.1f}%")
    else:
        print(" — 无正收益参数")


if __name__ == '__main__':
    main()
