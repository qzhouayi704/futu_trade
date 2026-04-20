#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对比 HK.01024 资金流向 vs 价格走势
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from futu import OpenQuoteContext, RET_OK, PeriodType, KLType, KL_FIELD, AuType
from datetime import date, timedelta
import pandas as pd

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 200)
pd.set_option('display.float_format', '{:.2f}'.format)

STOCK_CODE = 'HK.01024'

def check():
    ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
    try:
        end_date = date.today().strftime('%Y-%m-%d')
        start_date = (date.today() - timedelta(days=90)).strftime('%Y-%m-%d')

        # 1. K线数据
        ret1, data1, _ = ctx.request_history_kline(
            STOCK_CODE, start=start_date, end=end_date,
            ktype=KLType.K_DAY, autype=AuType.QFQ,
            fields=[KL_FIELD.ALL], max_count=200
        )

        # 2. 资金流向
        ret2, data2 = ctx.get_capital_flow(
            STOCK_CODE, period_type=PeriodType.DAY,
            start=start_date, end=end_date
        )

        if ret1 != RET_OK:
            print(f"K线获取失败: {data1}")
            return
        if ret2 != RET_OK:
            print(f"资金流向获取失败: {data2}")
            return

        # 合并数据
        data1['date_key'] = pd.to_datetime(data1['time_key']).dt.date
        data2['date_key'] = pd.to_datetime(data2['capital_flow_item_time']).dt.date

        merged = pd.merge(
            data1[['date_key', 'open', 'close', 'high', 'low', 'volume', 'turnover', 'change_rate']],
            data2[['date_key', 'in_flow', 'main_in_flow', 'super_in_flow', 'big_in_flow']],
            on='date_key', how='inner'
        )

        print(f"{'='*100}")
        print(f"HK.01024 价格 vs 资金流向 对比 ({start_date} ~ {end_date})")
        print(f"{'='*100}")

        # 基本价格统计
        first_close = merged['close'].iloc[0]
        last_close = merged['close'].iloc[-1]
        price_change_pct = (last_close - first_close) / first_close * 100
        total_inflow = merged['in_flow'].sum() / 1e8
        total_main_inflow = merged['main_in_flow'].sum() / 1e8

        print(f"\n--- 期间汇总 ---")
        print(f"起始收盘价: {first_close:.2f}")
        print(f"最新收盘价: {last_close:.2f}")
        print(f"期间涨跌幅: {price_change_pct:+.2f}%")
        print(f"期间最高价: {merged['high'].max():.2f}")
        print(f"期间最低价: {merged['low'].min():.2f}")
        print(f"累计整体净流入: {total_inflow:.2f} Yi")
        print(f"累计主力净流入: {total_main_inflow:.2f} Yi")
        print(f"日均成交额: {merged['turnover'].mean()/1e8:.2f} Yi")

        # 关键分析：资金流入但价格不涨的可能原因
        print(f"\n--- 分析：资金流入 vs 价格涨跌 ---")

        # 按周汇总
        merged['week'] = pd.to_datetime(merged['date_key']).dt.isocalendar().week
        weekly = merged.groupby('week').agg({
            'close': ['first', 'last'],
            'in_flow': 'sum',
            'main_in_flow': 'sum',
            'turnover': 'sum',
            'volume': 'sum'
        }).reset_index()
        weekly.columns = ['week', 'open_price', 'close_price', 'net_inflow', 'main_inflow', 'turnover', 'volume']
        weekly['price_chg_pct'] = (weekly['close_price'] - weekly['open_price']) / weekly['open_price'] * 100
        weekly['net_inflow'] = weekly['net_inflow'] / 1e8
        weekly['main_inflow'] = weekly['main_inflow'] / 1e8
        weekly['turnover'] = weekly['turnover'] / 1e8

        print(f"\n--- 按周汇总 ---")
        print(f"{'Week':>6} {'ClosePrice':>10} {'PriceChg%':>10} {'NetInflow(Yi)':>14} {'MainInflow(Yi)':>15} {'Turnover(Yi)':>13}")
        for _, row in weekly.iterrows():
            print(f"{int(row['week']):>6} {row['close_price']:>10.2f} {row['price_chg_pct']:>+10.2f} {row['net_inflow']:>14.2f} {row['main_inflow']:>15.2f} {row['turnover']:>13.2f}")

        # 资金效率分析
        print(f"\n--- 资金效率分析 ---")
        total_turnover = merged['turnover'].sum() / 1e8
        print(f"期间总成交额: {total_turnover:.2f} Yi")
        print(f"净流入占总成交额比: {total_inflow/total_turnover*100:.2f}%")
        print(f"主力净流入占总成交额比: {total_main_inflow/total_turnover*100:.2f}%")
        print(f"==> 净流入/成交额比例越低，说明资金对倒/换手越严重，推动力越弱")

        # 大单 vs 散户对冲分析
        merged['retail_flow'] = (merged['in_flow'] - merged['main_in_flow']) / 1e8
        merged['main_flow_yi'] = merged['main_in_flow'] / 1e8
        total_retail = merged['retail_flow'].sum()
        print(f"\n--- 主力 vs 散户 ---")
        print(f"主力累计净流入: {total_main_inflow:.2f} Yi")
        print(f"散户(中小单)累计净流入: {total_retail:.2f} Yi")
        if total_main_inflow > 0 and total_retail < 0:
            print(f"==> 典型吸筹模式: 主力买入，散户卖出")
        elif total_main_inflow > 0 and total_retail > 0:
            print(f"==> 共识买入: 主力和散户同时流入，但价格涨幅有限")
            print(f"    可能原因: 上方卖压大(套牢盘/限售解禁)，资金被消耗在承接抛盘上")

        # 检查成交量趋势
        vol_first_half = merged['volume'].iloc[:len(merged)//2].mean()
        vol_second_half = merged['volume'].iloc[len(merged)//2:].mean()
        print(f"\n--- 成交量趋势 ---")
        print(f"前半段日均成交量: {vol_first_half/1e6:.2f}M")
        print(f"后半段日均成交量: {vol_second_half/1e6:.2f}M")
        if vol_second_half > vol_first_half * 1.2:
            print(f"==> 成交量放大，可能在酝酿突破")
        elif vol_second_half < vol_first_half * 0.8:
            print(f"==> 成交量萎缩，资金流入可能是低量下的小额买入")

    finally:
        ctx.close()

if __name__ == '__main__':
    check()
