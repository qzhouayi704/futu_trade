#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
诊断脚本：检查 HK.01024 的历史资金流向数据
用于验证数据准确性
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from futu import OpenQuoteContext, RET_OK, PeriodType
from datetime import date, timedelta
import pandas as pd

# 设置显示选项
pd.set_option('display.max_columns', None)
pd.set_option('display.width', 200)
pd.set_option('display.float_format', '{:.2f}'.format)

STOCK_CODE = 'HK.01024'

def check_capital_flow():
    """检查 get_capital_flow (DAY) 接口返回的历史资金流向"""
    ctx = OpenQuoteContext(host='127.0.0.1', port=11111)

    try:
        end_date = date.today().strftime('%Y-%m-%d')
        start_date = (date.today() - timedelta(days=90)).strftime('%Y-%m-%d')

        print(f"=" * 80)
        print(f"检查 {STOCK_CODE} 资金流向数据")
        print(f"时间范围: {start_date} ~ {end_date}")
        print(f"=" * 80)

        # === 1. get_capital_flow (DAY) - 每日净流入 ===
        print(f"\n{'='*80}")
        print(f"[1] get_capital_flow (DAY模式) - 各级别净流入")
        print(f"{'='*80}")
        ret, data = ctx.get_capital_flow(
            STOCK_CODE, period_type=PeriodType.DAY,
            start=start_date, end=end_date
        )

        if ret == RET_OK and data is not None:
            print(f"返回列名: {list(data.columns)}")
            print(f"返回行数: {len(data)}")
            print(f"\n--- 最近20天数据 ---")

            # 选择关键列显示
            cols = ['capital_flow_item_time', 'in_flow', 'main_in_flow',
                    'super_in_flow', 'big_in_flow', 'mid_in_flow', 'sml_in_flow']
            available_cols = [c for c in cols if c in data.columns]
            display_df = data[available_cols].tail(20).copy()

            # 转换为亿元显示
            for col in available_cols:
                if col != 'capital_flow_item_time':
                    display_df[col] = display_df[col] / 1e8

            display_df.columns = [c.replace('capital_flow_item_time', '日期')
                                    .replace('in_flow', '整体净流入(亿)')
                                    .replace('main_in_flow', '主力净流入(亿)')
                                    .replace('super_in_flow', '超大单净(亿)')
                                    .replace('big_in_flow', '大单净(亿)')
                                    .replace('mid_in_flow', '中单净(亿)')
                                    .replace('sml_in_flow', '小单净(亿)')
                                   for c in display_df.columns]
            print(display_df.to_string(index=False))

            # 统计正负天数
            if 'in_flow' in data.columns:
                positive_days = (data['in_flow'] > 0).sum()
                negative_days = (data['in_flow'] < 0).sum()
                zero_days = (data['in_flow'] == 0).sum()
                total = len(data)
                print(f"\n--- 整体净流入统计 ---")
                print(f"总天数: {total}")
                print(f"净流入天数: {positive_days} ({positive_days/total*100:.1f}%)")
                print(f"净流出天数: {negative_days} ({negative_days/total*100:.1f}%)")
                print(f"持平天数:   {zero_days}")
                print(f"累计净流入: {data['in_flow'].sum()/1e8:.2f} 亿")
                print(f"日均净流入: {data['in_flow'].mean()/1e8:.4f} 亿")

            if 'main_in_flow' in data.columns:
                positive_days = (data['main_in_flow'] > 0).sum()
                negative_days = (data['main_in_flow'] < 0).sum()
                total = len(data)
                print(f"\n--- 主力净流入统计 ---")
                print(f"净流入天数: {positive_days} ({positive_days/total*100:.1f}%)")
                print(f"净流出天数: {negative_days} ({negative_days/total*100:.1f}%)")
                print(f"累计主力净流入: {data['main_in_flow'].sum()/1e8:.2f} 亿")
        else:
            print(f"获取失败: {data}")

        # === 2. get_capital_distribution - 当日流入/流出分开 ===
        print(f"\n{'='*80}")
        print(f"[2] get_capital_distribution - 当日各级别流入/流出分开")
        print(f"{'='*80}")
        ret2, data2 = ctx.get_capital_distribution(STOCK_CODE)
        if ret2 == RET_OK and data2 is not None:
            print(f"返回列名: {list(data2.columns)}")
            latest = data2.iloc[-1]
            print(f"\n--- 当日数据 ---")

            super_in = float(latest.get('capital_in_super', 0))
            super_out = float(latest.get('capital_out_super', 0))
            big_in = float(latest.get('capital_in_big', 0))
            big_out = float(latest.get('capital_out_big', 0))
            mid_in = float(latest.get('capital_in_mid', 0))
            mid_out = float(latest.get('capital_out_mid', 0))
            small_in = float(latest.get('capital_in_small', 0))
            small_out = float(latest.get('capital_out_small', 0))

            print(f"超大单: 流入 {super_in/1e8:.4f}亿, 流出 {super_out/1e8:.4f}亿, 净={( super_in-super_out)/1e8:.4f}亿")
            print(f"大  单: 流入 {big_in/1e8:.4f}亿, 流出 {big_out/1e8:.4f}亿, 净={(big_in-big_out)/1e8:.4f}亿")
            print(f"中  单: 流入 {mid_in/1e8:.4f}亿, 流出 {mid_out/1e8:.4f}亿, 净={(mid_in-mid_out)/1e8:.4f}亿")
            print(f"小  单: 流入 {small_in/1e8:.4f}亿, 流出 {small_out/1e8:.4f}亿, 净={(small_in-small_out)/1e8:.4f}亿")

            total_in = super_in + big_in + mid_in + small_in
            total_out = super_out + big_out + mid_out + small_out
            print(f"\n总流入: {total_in/1e8:.4f}亿")
            print(f"总流出: {total_out/1e8:.4f}亿")
            print(f"净流入: {(total_in-total_out)/1e8:.4f}亿")

            main_in = super_in + big_in
            main_out = super_out + big_out
            print(f"\n主力(超大+大单)流入: {main_in/1e8:.4f}亿")
            print(f"主力(超大+大单)流出: {main_out/1e8:.4f}亿")
            print(f"主力净流入: {(main_in-main_out)/1e8:.4f}亿")
        else:
            print(f"获取失败: {data2}")

        # === 3. 对比验证 ===
        print(f"\n{'='*80}")
        print(f"[3] 数据质量分析")
        print(f"{'='*80}")

        if ret == RET_OK and data is not None and 'in_flow' in data.columns:
            # 检查是否有异常大/小的值
            max_flow = data['in_flow'].max()
            min_flow = data['in_flow'].min()
            std_flow = data['in_flow'].std()
            mean_flow = data['in_flow'].mean()
            print(f"整体净流入 - 最大值: {max_flow/1e8:.4f}亿, 最小值: {min_flow/1e8:.4f}亿")
            print(f"  标准差: {std_flow/1e8:.4f}亿, 均值: {mean_flow/1e8:.4f}亿")

            # 检查是否有全为0的字段
            for col in ['super_in_flow', 'big_in_flow', 'mid_in_flow', 'sml_in_flow']:
                if col in data.columns:
                    all_zero = (data[col] == 0).all()
                    all_positive = (data[col] >= 0).all()
                    if all_zero:
                        print(f"  ⚠️  {col} 全部为0 - 数据可能缺失!")
                    elif all_positive:
                        print(f"  ⚠️  {col} 全部>=0 - 净值应有正有负，可能是数据问题!")
                    else:
                        neg_pct = (data[col] < 0).sum() / len(data) * 100
                        print(f"  ✅ {col}: {neg_pct:.1f}% 天数为负值 (正常)")

    finally:
        ctx.close()
        print(f"\n连接已关闭")


if __name__ == '__main__':
    check_capital_flow()
