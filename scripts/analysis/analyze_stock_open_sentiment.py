#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析：用12只科网股的开盘涨跌幅集合作为市场情绪判断

思路：开盘时就能拿到所有股票的开盘价，计算相对前收盘价的涨跌幅，
取中位数/均值作为"开盘情绪指标"，判断当天是否强势。

分析内容：
1. 科网股开盘涨跌幅中位数 vs ETF收盘涨跌幅的相关性
2. 用开盘中位数>X%作为bullish判断的准确率
3. 不同阈值下的覆盖率和假阳性率
4. 对比ETF开盘 vs 科网股开盘集合的判断效果
"""

import sys
import os
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from datetime import datetime
from simple_trade.database.core.db_manager import DatabaseManager
from simple_trade.config.config import Config
from simple_trade.backtest.core.loaders.backtest_only_loader import BacktestOnlyDataLoader
from simple_trade.backtest.strategies.price_position_strategy import TARGET_STOCKS


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

    # ===== 加载ETF数据 =====
    print("加载 HK.03032 K线数据...")
    etf_df = data_loader.load_kline_data('HK.03032', start_dt, end_dt)
    etf_records = etf_df.to_dict('records') if etf_df is not None and not etf_df.empty else []

    etf_daily = {}
    for i in range(1, len(etf_records)):
        prev = etf_records[i - 1]
        curr = etf_records[i]
        pc = prev.get('close_price', 0)
        if pc <= 0:
            continue
        date_str = curr.get('time_key', '')[:10]
        etf_daily[date_str] = {
            'open_pct': (curr['open_price'] - pc) / pc * 100,
            'close_pct': (curr['close_price'] - pc) / pc * 100,
        }

    # ===== 加载所有科网股数据 =====
    print(f"加载 {len(TARGET_STOCKS)} 只科网股K线数据...")
    stock_daily = {}  # {date: {stock_code: {open_pct, close_pct}}}

    for stock_code in TARGET_STOCKS:
        df = data_loader.load_kline_data(stock_code, start_dt, end_dt)
        if df is None or df.empty:
            print(f"  {stock_code}: 无数据")
            continue

        records = df.to_dict('records')
        count = 0
        for i in range(1, len(records)):
            prev = records[i - 1]
            curr = records[i]
            pc = prev.get('close_price', 0)
            op = curr.get('open_price', 0)
            cp = curr.get('close_price', 0)
            if pc <= 0 or op <= 0:
                continue

            date_str = curr.get('time_key', '')[:10]
            if date_str not in stock_daily:
                stock_daily[date_str] = {}

            stock_daily[date_str][stock_code] = {
                'open_pct': (op - pc) / pc * 100,
                'close_pct': (cp - pc) / pc * 100 if cp > 0 else 0,
            }
            count += 1
        print(f"  {stock_code}: {count} 天")

    # ===== 计算每天的科网股开盘情绪指标 =====
    print(f"\n计算每日开盘情绪指标...")
    daily_sentiment = []

    for date_str in sorted(stock_daily.keys()):
        stocks = stock_daily[date_str]
        if len(stocks) < 5:  # 至少5只股票有数据
            continue

        open_pcts = [s['open_pct'] for s in stocks.values()]
        close_pcts = [s['close_pct'] for s in stocks.values()]

        open_median = np.median(open_pcts)
        open_mean = np.mean(open_pcts)
        open_positive_ratio = sum(1 for p in open_pcts if p > 0) / len(open_pcts) * 100
        close_median = np.median(close_pcts)

        etf_info = etf_daily.get(date_str, {})
        etf_close_pct = etf_info.get('close_pct', None)
        etf_open_pct = etf_info.get('open_pct', None)

        # 真实bullish标准：ETF收盘>1%
        is_bullish = etf_close_pct is not None and etf_close_pct > 1.0

        daily_sentiment.append({
            'date': date_str,
            'stock_count': len(stocks),
            'open_median': round(open_median, 4),
            'open_mean': round(open_mean, 4),
            'open_positive_ratio': round(open_positive_ratio, 1),
            'close_median': round(close_median, 4),
            'etf_close_pct': round(etf_close_pct, 4) if etf_close_pct is not None else None,
            'etf_open_pct': round(etf_open_pct, 4) if etf_open_pct is not None else None,
            'is_bullish': is_bullish,
        })

    total_days = len(daily_sentiment)
    bullish_days = [d for d in daily_sentiment if d['is_bullish']]
    print(f"有效交易日: {total_days}, bullish天: {len(bullish_days)}\n")

    # ===== 1. bullish天的科网股开盘情绪分布 =====
    print(f"{'='*70}")
    print(f"一、bullish天（ETF收盘>1%）的科网股开盘情绪")
    print(f"{'='*70}")

    if bullish_days:
        medians = [d['open_median'] for d in bullish_days]
        means = [d['open_mean'] for d in bullish_days]
        ratios = [d['open_positive_ratio'] for d in bullish_days]

        print(f"  科网股开盘涨跌幅中位数:")
        print(f"    均值: {np.mean(medians):.4f}%")
        print(f"    最小: {min(medians):.4f}%")
        print(f"    最大: {max(medians):.4f}%")
        print(f"    P25:  {np.percentile(medians, 25):.4f}%")
        print(f"    P75:  {np.percentile(medians, 75):.4f}%")

        print(f"\n  科网股高开比例:")
        print(f"    均值: {np.mean(ratios):.1f}%")
        print(f"    最小: {min(ratios):.1f}%")

        # 分段
        med_gt_1 = [d for d in bullish_days if d['open_median'] > 1.0]
        med_05_1 = [d for d in bullish_days if 0.5 < d['open_median'] <= 1.0]
        med_0_05 = [d for d in bullish_days if 0 < d['open_median'] <= 0.5]
        med_neg = [d for d in bullish_days if d['open_median'] <= 0]

        n = len(bullish_days)
        print(f"\n  开盘中位数分段:")
        print(f"    > 1%:     {len(med_gt_1):3d} 天 ({len(med_gt_1)/n*100:.1f}%)")
        print(f"    0.5~1%:   {len(med_05_1):3d} 天 ({len(med_05_1)/n*100:.1f}%)")
        print(f"    0~0.5%:   {len(med_0_05):3d} 天 ({len(med_0_05)/n*100:.1f}%)")
        print(f"    <= 0%:    {len(med_neg):3d} 天 ({len(med_neg)/n*100:.1f}%)")

    # ===== 2. 不同阈值的判断效果 =====
    print(f"\n{'='*70}")
    print(f"二、不同阈值下的判断效果（科网股开盘中位数 vs ETF收盘>1%）")
    print(f"{'='*70}")

    thresholds = [0.0, 0.2, 0.3, 0.5, 0.7, 1.0]
    print(f"\n  {'阈值':>6} | {'预测bullish':>10} | {'真阳性':>8} | {'假阳性':>8} | {'准确率':>8} | {'覆盖率':>8} | {'F1':>6}")
    print(f"  {'-'*70}")

    for th in thresholds:
        predicted_bullish = [d for d in daily_sentiment if d['open_median'] > th]
        true_positive = [d for d in predicted_bullish if d['is_bullish']]
        false_positive = [d for d in predicted_bullish if not d['is_bullish']]

        precision = len(true_positive) / len(predicted_bullish) * 100 if predicted_bullish else 0
        recall = len(true_positive) / len(bullish_days) * 100 if bullish_days else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

        print(f"  >{th:>4.1f}% | {len(predicted_bullish):>10} | {len(true_positive):>8} | {len(false_positive):>8} | {precision:>7.1f}% | {recall:>7.1f}% | {f1:>5.1f}")

    # ===== 3. 用高开比例作为指标 =====
    print(f"\n{'='*70}")
    print(f"三、用高开比例（>0%的股票占比）作为判断指标")
    print(f"{'='*70}")

    ratio_thresholds = [50, 60, 70, 75, 80, 90]
    print(f"\n  {'阈值':>6} | {'预测bullish':>10} | {'真阳性':>8} | {'假阳性':>8} | {'准确率':>8} | {'覆盖率':>8} | {'F1':>6}")
    print(f"  {'-'*70}")

    for rth in ratio_thresholds:
        predicted = [d for d in daily_sentiment if d['open_positive_ratio'] >= rth]
        tp = [d for d in predicted if d['is_bullish']]
        fp = [d for d in predicted if not d['is_bullish']]

        prec = len(tp) / len(predicted) * 100 if predicted else 0
        rec = len(tp) / len(bullish_days) * 100 if bullish_days else 0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0

        print(f"  >={rth:>3}% | {len(predicted):>10} | {len(tp):>8} | {len(fp):>8} | {prec:>7.1f}% | {rec:>7.1f}% | {f1:>5.1f}")

    # ===== 4. 组合指标：中位数 + 高开比例 =====
    print(f"\n{'='*70}")
    print(f"四、组合指标：开盘中位数>X% 且 高开比例>=Y%")
    print(f"{'='*70}")

    combos = [
        (0.3, 60), (0.3, 70), (0.5, 60), (0.5, 70), (0.5, 75),
        (0.7, 70), (0.7, 75), (1.0, 70), (1.0, 75),
    ]
    print(f"\n  {'中位数':>6} {'高开比':>6} | {'预测':>6} | {'真阳':>6} | {'假阳':>6} | {'准确率':>8} | {'覆盖率':>8} | {'F1':>6}")
    print(f"  {'-'*70}")

    for med_th, ratio_th in combos:
        predicted = [d for d in daily_sentiment if d['open_median'] > med_th and d['open_positive_ratio'] >= ratio_th]
        tp = [d for d in predicted if d['is_bullish']]
        fp = [d for d in predicted if not d['is_bullish']]

        prec = len(tp) / len(predicted) * 100 if predicted else 0
        rec = len(tp) / len(bullish_days) * 100 if bullish_days else 0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0

        print(f"  >{med_th:>4.1f}% >={ratio_th:>3}% | {len(predicted):>6} | {len(tp):>6} | {len(fp):>6} | {prec:>7.1f}% | {rec:>7.1f}% | {f1:>5.1f}")

    # ===== 5. 对比ETF开盘 vs 科网股开盘集合 =====
    print(f"\n{'='*70}")
    print(f"五、对比：ETF开盘涨跌幅 vs 科网股开盘中位数（阈值>0.5%）")
    print(f"{'='*70}")

    etf_pred = [d for d in daily_sentiment if d['etf_open_pct'] is not None and d['etf_open_pct'] > 0.5]
    stock_pred = [d for d in daily_sentiment if d['open_median'] > 0.5]

    etf_tp = [d for d in etf_pred if d['is_bullish']]
    stock_tp = [d for d in stock_pred if d['is_bullish']]

    print(f"\n  ETF开盘>0.5%:")
    print(f"    预测天数: {len(etf_pred)}, 真阳性: {len(etf_tp)}, 准确率: {len(etf_tp)/len(etf_pred)*100:.1f}%, 覆盖率: {len(etf_tp)/len(bullish_days)*100:.1f}%")
    print(f"\n  科网股开盘中位数>0.5%:")
    print(f"    预测天数: {len(stock_pred)}, 真阳性: {len(stock_tp)}, 准确率: {len(stock_tp)/len(stock_pred)*100:.1f}%, 覆盖率: {len(stock_tp)/len(bullish_days)*100:.1f}%")

    # ===== 6. 详细列表 =====
    print(f"\n{'='*70}")
    print(f"六、bullish天详细数据（按开盘中位数排序）")
    print(f"{'='*70}")
    print(f"  {'日期':<12} {'开盘中位数':>10} {'开盘均值':>10} {'高开比例':>10} {'ETF开盘':>10} {'ETF收盘':>10}")
    print(f"  {'-'*64}")
    for d in sorted(bullish_days, key=lambda x: x['open_median'], reverse=True):
        etf_o = f"{d['etf_open_pct']:.4f}" if d['etf_open_pct'] is not None else "N/A"
        etf_c = f"{d['etf_close_pct']:.4f}" if d['etf_close_pct'] is not None else "N/A"
        print(f"  {d['date']:<12} {d['open_median']:>10.4f} {d['open_mean']:>10.4f} {d['open_positive_ratio']:>9.1f}% {etf_o:>10} {etf_c:>10}")


if __name__ == '__main__':
    main()
