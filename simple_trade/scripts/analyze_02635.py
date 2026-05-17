#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
诊断脚本：分析 HK.02635 的资金流向与股价走势背离问题
- 检查最近的资金分布（主力流入/流出）
- 检查最近的日线K线数据（涨跌）
- 交叉对比分析
"""
import io
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from futu import OpenQuoteContext, RET_OK, PeriodType, KLType, SubType
from datetime import date, timedelta
import pandas as pd

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 200)
pd.set_option('display.float_format', '{:.2f}'.format)

STOCK_CODE = 'HK.02635'

# Fix Windows GBK encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

def analyze():
    ctx = OpenQuoteContext(host='127.0.0.1', port=11111)

    try:
        end_date = date.today().strftime('%Y-%m-%d')
        start_date = (date.today() - timedelta(days=60)).strftime('%Y-%m-%d')

        print(f"{'='*80}")
        print(f"  HK.02635 资金流向 vs 股价 诊断分析")
        print(f"  分析日期: {date.today()}")
        print(f"{'='*80}")

        # === 1. 日线K线数据 ===
        print(f"\n{'='*80}")
        print(f"[1] 日线K线数据 (最近20天)")
        print(f"{'='*80}")
        ret_kl, kl_data, _ = ctx.request_history_kline(
            STOCK_CODE,
            start=start_date,
            end=end_date,
            ktype=KLType.K_DAY,
            max_count=20
        )
        if ret_kl == RET_OK and kl_data is not None:
            kl_cols = ['time_key', 'open', 'close', 'high', 'low', 'volume', 'turnover', 'change_rate']
            available = [c for c in kl_cols if c in kl_data.columns]
            kl_display = kl_data[available].copy()
            kl_display['turnover'] = kl_display['turnover'] / 1e8
            kl_display.rename(columns={
                'time_key': '日期', 'open': '开盘', 'close': '收盘',
                'high': '最高', 'low': '最低', 'volume': '成交量',
                'turnover': '成交额(亿)', 'change_rate': '涨跌幅%'
            }, inplace=True)
            print(kl_display.to_string(index=False))

            # 今天的涨跌
            if len(kl_data) >= 2:
                today_row = kl_data.iloc[-1]
                yesterday_row = kl_data.iloc[-2]
                print(f"\n--- 今日行情 ---")
                print(f"  今日: {today_row['time_key']}, 收盘 {today_row['close']:.3f}, 涨跌幅 {today_row['change_rate']:.2f}%")
                print(f"  昨日: {yesterday_row['time_key']}, 收盘 {yesterday_row['close']:.3f}, 涨跌幅 {yesterday_row['change_rate']:.2f}%")
        else:
            print(f"获取K线失败: {kl_data}")

        # === 2. 日线资金流向 ===
        print(f"\n{'='*80}")
        print(f"[2] 每日资金流向 (get_capital_flow DAY)")
        print(f"{'='*80}")
        ret_flow, flow_data = ctx.get_capital_flow(
            STOCK_CODE, period_type=PeriodType.DAY,
            start=start_date, end=end_date
        )
        if ret_flow == RET_OK and flow_data is not None:
            cols = ['capital_flow_item_time', 'in_flow', 'main_in_flow',
                    'super_in_flow', 'big_in_flow', 'mid_in_flow', 'sml_in_flow']
            available_cols = [c for c in cols if c in flow_data.columns]
            display_df = flow_data[available_cols].tail(20).copy()

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

            # 统计
            if 'main_in_flow' in flow_data.columns:
                recent = flow_data.tail(10)
                print(f"\n--- 最近10天主力净流入统计 ---")
                for _, row in recent.iterrows():
                    d = row['capital_flow_item_time']
                    main = row['main_in_flow'] / 1e8
                    total = row['in_flow'] / 1e8
                    direction = "[+]流入" if main > 0 else "[-]流出"
                    print(f"  {d}: 主力{direction} {abs(main):.4f}亿, 整体净流入 {total:.4f}亿")
        else:
            print(f"获取失败: {flow_data}")

        # === 3. 当日资金分布 ===
        print(f"\n{'='*80}")
        print(f"[3] 当日资金分布 (get_capital_distribution)")
        print(f"{'='*80}")
        ret2, data2 = ctx.get_capital_distribution(STOCK_CODE)
        if ret2 == RET_OK and data2 is not None:
            latest = data2.iloc[-1]
            super_in = float(latest.get('capital_in_super', 0))
            super_out = float(latest.get('capital_out_super', 0))
            big_in = float(latest.get('capital_in_big', 0))
            big_out = float(latest.get('capital_out_big', 0))
            mid_in = float(latest.get('capital_in_mid', 0))
            mid_out = float(latest.get('capital_out_mid', 0))
            small_in = float(latest.get('capital_in_small', 0))
            small_out = float(latest.get('capital_out_small', 0))

            main_in = super_in + big_in
            main_out = super_out + big_out

            print(f"超大单: 流入 {super_in/1e8:.4f}亿, 流出 {super_out/1e8:.4f}亿, 净={(super_in-super_out)/1e8:.4f}亿")
            print(f"大  单: 流入 {big_in/1e8:.4f}亿, 流出 {big_out/1e8:.4f}亿, 净={(big_in-big_out)/1e8:.4f}亿")
            print(f"中  单: 流入 {mid_in/1e8:.4f}亿, 流出 {mid_out/1e8:.4f}亿, 净={(mid_in-mid_out)/1e8:.4f}亿")
            print(f"小  单: 流入 {small_in/1e8:.4f}亿, 流出 {small_out/1e8:.4f}亿, 净={(small_in-small_out)/1e8:.4f}亿")
            print(f"\n主力(超大+大单)流入: {main_in/1e8:.4f}亿")
            print(f"主力(超大+大单)流出: {main_out/1e8:.4f}亿")
            print(f"主力净流入: {(main_in-main_out)/1e8:.4f}亿")
            print(f"主力买入占比: {main_in/(main_in+main_out)*100:.1f}%" if (main_in+main_out) > 0 else "N/A")
        else:
            print(f"获取失败: {data2}")

        # === 4. 综合分析 ===
        print(f"\n{'='*80}")
        print(f"[4] 综合分析: 资金流向 vs 股价背离")
        print(f"{'='*80}")

        if ret_kl == RET_OK and kl_data is not None and ret_flow == RET_OK and flow_data is not None:
            # 合并K线和资金流向数据
            kl_data['date_key'] = kl_data['time_key'].str[:10]
            flow_data['date_key'] = flow_data['capital_flow_item_time'].str[:10]

            merged = pd.merge(
                kl_data[['date_key', 'close', 'change_rate', 'volume', 'turnover']],
                flow_data[['date_key', 'in_flow', 'main_in_flow']],
                on='date_key', how='inner'
            ).tail(15)

            print(f"\n--- 最近15天 资金 vs 股价 交叉对比 ---")
            for _, row in merged.iterrows():
                d = row['date_key']
                chg = row['change_rate']
                main_flow = row['main_in_flow'] / 1e8
                price_dir = "[涨]" if chg > 0 else ("[跌]" if chg < 0 else "[平]")
                flow_dir = "[+主力入]" if main_flow > 0 else "[-主力出]"
                diverge = ""
                if chg < -1 and main_flow > 0:
                    diverge = " !! 【背离：主力买+股价跌】"
                elif chg > 1 and main_flow < 0:
                    diverge = " !! 【背离：主力卖+股价涨】"
                print(f"  {d}: {price_dir} {chg:+.2f}% | {flow_dir} {main_flow:+.4f}亿{diverge}")

            # 检测是否存在主力"对倒"或"出货"迹象
            print(f"\n--- 背离原因分析 ---")
            if len(merged) >= 2:
                last_row = merged.iloc[-1]
                prev_row = merged.iloc[-2]

                if prev_row['main_in_flow'] > 0 and last_row['change_rate'] < -2:
                    print("  🔍 昨日主力净买入 + 今日大跌，可能原因：")
                    print("     1. 主力对倒做量：大单买卖对敲，制造主力买入假象，实际在派发筹码")
                    print("     2. 拉高出货尾声：主力前期吸筹拉升后，在高位通过大单买入吸引跟风盘，隔日反手卖出")
                    print("     3. 突发利空：盘后出现公司层面或行业/宏观利空消息，导致次日抛压")
                    print("     4. 资金流数据滞后：数据统计的是成交撮合，主力可能在尾盘集中买入拉起指标但隔日早盘即卖出")
                    print("     5. 板块联动下跌：即使个股主力做多，若板块整体承压，也会被拖累")

                    # 检查成交量变化
                    if last_row['volume'] > prev_row['volume'] * 1.3:
                        print(f"\n  !! 今日成交量较昨日放大 {(last_row['volume']/prev_row['volume']-1)*100:.0f}%，放量下跌，可能是主力出货信号！")
                    elif last_row['volume'] < prev_row['volume'] * 0.7:
                        print(f"\n  ✅ 今日成交量较昨日缩小 {(1-last_row['volume']/prev_row['volume'])*100:.0f}%，缩量下跌，恐慌情绪主导")

                    # 检查换手率
                    if last_row['turnover'] > 0 and prev_row['turnover'] > 0:
                        print(f"\n  成交额对比: 昨日 {prev_row['turnover']/1e8:.2f}亿 → 今日 {last_row['turnover']/1e8:.2f}亿")

    finally:
        ctx.close()
        print(f"\n连接已关闭")


if __name__ == '__main__':
    analyze()
