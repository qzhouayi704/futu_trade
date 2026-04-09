#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析恒生科技ETF（HK.03032）在 bullish 天的开盘涨跌幅

核心问题：回测用当天收盘涨跌幅判断 bullish（>1%），但实盘开盘时不知道当天最终涨跌幅。
本脚本分析：
1. 最终被判定为 bullish 的天，开盘时涨跌幅是多少？
2. 开盘涨跌幅 > 1% 的天，最终收盘也 > 1% 的概率有多大？
3. 开盘高开（>0.5%）但收盘不到 1% 的天有多少？（假阳性）
4. 开盘平开/低开但收盘 > 1% 的天有多少？（漏判）
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from datetime import datetime
from simple_trade.database.core.db_manager import DatabaseManager
from simple_trade.config.config import Config
from simple_trade.backtest.core.loaders.backtest_only_loader import BacktestOnlyDataLoader


def main():
    config = Config()
    db_manager = DatabaseManager(config.database_path)
    data_loader = BacktestOnlyDataLoader(
        db_manager, market='HK',
        use_stock_pool_only=False,
        only_stocks_with_kline=False,
        min_kline_days=5
    )

    start_dt = datetime(2025, 2, 6)
    end_dt = datetime(2026, 2, 6)

    print(f"加载 HK.03032 K线数据: {start_dt.date()} ~ {end_dt.date()}")
    df = data_loader.load_kline_data('HK.03032', start_dt, end_dt)

    if df is None or df.empty:
        print("无数据!")
        return

    records = df.to_dict('records')
    print(f"共 {len(records)} 条K线数据\n")

    # 计算每天的开盘涨跌幅和收盘涨跌幅
    days = []
    for i in range(1, len(records)):
        prev = records[i - 1]
        curr = records[i]
        prev_close = prev.get('close_price', 0)
        if prev_close <= 0:
            continue

        open_price = curr.get('open_price', 0)
        close_price = curr.get('close_price', 0)
        high_price = curr.get('high_price', 0)
        low_price = curr.get('low_price', 0)

        if open_price <= 0 or close_price <= 0:
            continue

        open_pct = (open_price - prev_close) / prev_close * 100
        close_pct = (close_price - prev_close) / prev_close * 100
        high_pct = (high_price - prev_close) / prev_close * 100
        low_pct = (low_price - prev_close) / prev_close * 100

        date_str = curr.get('time_key', '')[:10]
        days.append({
            'date': date_str,
            'prev_close': prev_close,
            'open_price': open_price,
            'close_price': close_price,
            'open_pct': round(open_pct, 4),
            'close_pct': round(close_pct, 4),
            'high_pct': round(high_pct, 4),
            'low_pct': round(low_pct, 4),
        })

    total_days = len(days)
    print(f"有效交易日: {total_days}\n")

    # ===== 1. 收盘 bullish（>1%）天的开盘涨跌幅分布 =====
    bullish_days = [d for d in days if d['close_pct'] > 1.0]
    print(f"{'='*70}")
    print(f"一、收盘涨幅 > 1% 的天数（bullish）: {len(bullish_days)} / {total_days} ({len(bullish_days)/total_days*100:.1f}%)")
    print(f"{'='*70}")

    if bullish_days:
        open_pcts = [d['open_pct'] for d in bullish_days]
        print(f"  开盘涨跌幅统计:")
        print(f"    均值: {sum(open_pcts)/len(open_pcts):.4f}%")
        print(f"    最小: {min(open_pcts):.4f}%")
        print(f"    最大: {max(open_pcts):.4f}%")

        # 分段统计
        open_gt_1 = [d for d in bullish_days if d['open_pct'] > 1.0]
        open_05_1 = [d for d in bullish_days if 0.5 < d['open_pct'] <= 1.0]
        open_0_05 = [d for d in bullish_days if 0 < d['open_pct'] <= 0.5]
        open_neg = [d for d in bullish_days if d['open_pct'] <= 0]

        print(f"\n  开盘涨跌幅分段:")
        print(f"    开盘 > 1%:     {len(open_gt_1):3d} 天 ({len(open_gt_1)/len(bullish_days)*100:.1f}%) — 开盘就已经 bullish")
        print(f"    开盘 0.5~1%:   {len(open_05_1):3d} 天 ({len(open_05_1)/len(bullish_days)*100:.1f}%) — 开盘偏强但未达阈值")
        print(f"    开盘 0~0.5%:   {len(open_0_05):3d} 天 ({len(open_0_05)/len(bullish_days)*100:.1f}%) — 开盘平开")
        print(f"    开盘 <= 0%:    {len(open_neg):3d} 天 ({len(open_neg)/len(bullish_days)*100:.1f}%) — 开盘低开但收盘翻红")

        print(f"\n  详细列表（收盘>1%的天）:")
        print(f"  {'日期':<12} {'开盘涨跌%':>10} {'收盘涨跌%':>10} {'最高涨%':>10} {'最低跌%':>10}")
        print(f"  {'-'*54}")
        for d in sorted(bullish_days, key=lambda x: x['open_pct'], reverse=True):
            print(f"  {d['date']:<12} {d['open_pct']:>10.4f} {d['close_pct']:>10.4f} {d['high_pct']:>10.4f} {d['low_pct']:>10.4f}")

    # ===== 2. 开盘 > 1% 的天，收盘也 > 1% 的概率 =====
    open_bullish = [d for d in days if d['open_pct'] > 1.0]
    print(f"\n{'='*70}")
    print(f"二、开盘涨幅 > 1% 的天数: {len(open_bullish)} / {total_days}")
    print(f"{'='*70}")
    if open_bullish:
        close_also_bullish = [d for d in open_bullish if d['close_pct'] > 1.0]
        close_positive = [d for d in open_bullish if d['close_pct'] > 0]
        close_negative = [d for d in open_bullish if d['close_pct'] <= 0]
        print(f"  收盘也 > 1%: {len(close_also_bullish)} ({len(close_also_bullish)/len(open_bullish)*100:.1f}%)")
        print(f"  收盘 > 0%:   {len(close_positive)} ({len(close_positive)/len(open_bullish)*100:.1f}%)")
        print(f"  收盘 <= 0%:  {len(close_negative)} ({len(close_negative)/len(open_bullish)*100:.1f}%)")

    # ===== 3. 开盘 > 0.5% 作为替代阈值 =====
    open_half = [d for d in days if d['open_pct'] > 0.5]
    print(f"\n{'='*70}")
    print(f"三、开盘涨幅 > 0.5% 的天数: {len(open_half)} / {total_days}")
    print(f"{'='*70}")
    if open_half:
        close_bullish_from_half = [d for d in open_half if d['close_pct'] > 1.0]
        close_positive_from_half = [d for d in open_half if d['close_pct'] > 0]
        print(f"  收盘 > 1%: {len(close_bullish_from_half)} ({len(close_bullish_from_half)/len(open_half)*100:.1f}%) — 真阳性")
        print(f"  收盘 > 0%: {len(close_positive_from_half)} ({len(close_positive_from_half)/len(open_half)*100:.1f}%)")
        false_positive = len(open_half) - len(close_bullish_from_half)
        print(f"  收盘 <= 1%: {false_positive} ({false_positive/len(open_half)*100:.1f}%) — 假阳性")

    # ===== 4. 个股高开分析 =====
    from simple_trade.backtest.strategies.price_position_strategy import TARGET_STOCKS

    print(f"\n{'='*70}")
    print(f"四、个股在 bullish 天的高开情况")
    print(f"{'='*70}")

    for stock_code in TARGET_STOCKS[:3]:  # 先看3只
        stock_df = data_loader.load_kline_data(stock_code, start_dt, end_dt)
        if stock_df is None or stock_df.empty:
            continue

        stock_records = stock_df.to_dict('records')
        stock_days = {}
        for i in range(1, len(stock_records)):
            prev = stock_records[i - 1]
            curr = stock_records[i]
            pc = prev.get('close_price', 0)
            if pc <= 0:
                continue
            op = curr.get('open_price', 0)
            if op <= 0:
                continue
            date_str = curr.get('time_key', '')[:10]
            stock_days[date_str] = {
                'open_pct': (op - pc) / pc * 100,
                'prev_close': pc,
                'open_price': op,
            }

        # 在 ETF bullish 天，个股的开盘情况
        bullish_dates = [d['date'] for d in bullish_days]
        stock_on_bullish = []
        for date in bullish_dates:
            if date in stock_days:
                stock_on_bullish.append(stock_days[date])

        if stock_on_bullish:
            open_pcts = [d['open_pct'] for d in stock_on_bullish]
            gap_up = [d for d in stock_on_bullish if d['open_pct'] > 0]
            gap_up_1 = [d for d in stock_on_bullish if d['open_pct'] > 1.0]
            print(f"\n  {stock_code}: bullish天共{len(stock_on_bullish)}天")
            print(f"    开盘涨跌幅均值: {sum(open_pcts)/len(open_pcts):.4f}%")
            print(f"    高开(>0%): {len(gap_up)} ({len(gap_up)/len(stock_on_bullish)*100:.1f}%)")
            print(f"    高开>1%:   {len(gap_up_1)} ({len(gap_up_1)/len(stock_on_bullish)*100:.1f}%)")

    # ===== 5. 实盘可行性总结 =====
    print(f"\n{'='*70}")
    print(f"五、实盘可行性分析总结")
    print(f"{'='*70}")

    if bullish_days:
        open_gt_1_pct = len(open_gt_1) / len(bullish_days) * 100
        print(f"  bullish天中，开盘就>1%的比例: {open_gt_1_pct:.1f}%")
        if open_gt_1_pct > 50:
            print(f"  → 多数bullish天开盘就已经强势，可以用开盘涨跌幅作为实盘判断依据")
        else:
            print(f"  → 多数bullish天开盘时还不明显，用收盘涨跌幅判断存在前瞻偏差")
            print(f"  → 建议：改用开盘涨跌幅（如>0.5%）作为实盘触发条件")


if __name__ == '__main__':
    main()
