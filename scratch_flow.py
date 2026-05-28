#!/usr/bin/env python3
"""解析资金流时间线数据，输出关键分析"""
import json, sys, os

files = {
    'HK.00981 中芯国际': r'C:\Users\ZHOUYICAN\.gemini\antigravity\brain\ca5234b5-70e6-4524-81d4-3d18b5e1f48f\.system_generated\steps\330\content.md',
    'HK.00100 MINIMAX': r'C:\Users\ZHOUYICAN\.gemini\antigravity\brain\ca5234b5-70e6-4524-81d4-3d18b5e1f48f\.system_generated\steps\331\content.md',
    'HK.06651 五一视界': r'C:\Users\ZHOUYICAN\.gemini\antigravity\brain\ca5234b5-70e6-4524-81d4-3d18b5e1f48f\.system_generated\steps\332\content.md',
    'HK.00992 联想集团': r'C:\Users\ZHOUYICAN\.gemini\antigravity\brain\ca5234b5-70e6-4524-81d4-3d18b5e1f48f\.system_generated\steps\333\content.md',
}

for name, path in files.items():
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
        # Extract JSON from markdown
        lines = text.strip().split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith('{'):
                data = json.loads(line)
                break
        else:
            print("  No JSON found")
            continue

        result = data.get('data', {})
        if not result:
            print("  No data")
            continue

        summary = result.get('summary', {})
        timeline = result.get('timeline', [])

        if summary:
            print(f"  动能标签: {summary.get('momentum_label', 'N/A')}")
            print(f"  信号: {summary.get('signal', 'N/A')}")
            print(f"  买卖比: {summary.get('buy_sell_ratio', 'N/A')}")
            print(f"  累计净流入: {summary.get('cum_net', 0):.1f}万")
            print(f"  前半段: {summary.get('first_half_net', 0):.1f}万")
            print(f"  后半段: {summary.get('second_half_net', 0):.1f}万")
            print(f"  最近净流入: {summary.get('recent_net', 0):.1f}万")
            absorption = summary.get('absorption')
            if absorption:
                print(f"  吸筹: {absorption}")

        if timeline:
            print(f"  数据点: {len(timeline)}")
            # 找关键时间点
            # 开盘30分钟
            opening = [p for p in timeline if '09:30' <= p.get('time','') <= '10:00']
            if opening:
                opening_net = sum(p.get('net_buy', 0) for p in opening)
                print(f"  开盘30分钟净买入: {opening_net:.1f}万")

            # 午后(14:00-)
            afternoon = [p for p in timeline if p.get('time','') >= '14:00']
            if afternoon:
                afternoon_net = sum(p.get('net_buy', 0) for p in afternoon)
                print(f"  14:00后净买入: {afternoon_net:.1f}万")

            # 最大单分钟净卖出
            if timeline:
                worst = min(timeline, key=lambda p: p.get('net_buy', 0))
                print(f"  最大单分钟净卖出: {worst.get('time','')} -> {worst.get('net_buy',0):.1f}万")
                best = max(timeline, key=lambda p: p.get('net_buy', 0))
                print(f"  最大单分钟净买入: {best.get('time','')} -> {best.get('net_buy',0):.1f}万")

            # 首尾价格
            first_price = next((p.get('price', 0) for p in timeline if p.get('price', 0) > 0), 0)
            last_price = next((p.get('price', 0) for p in reversed(timeline) if p.get('price', 0) > 0), 0)
            if first_price and last_price:
                chg = (last_price - first_price) / first_price * 100
                print(f"  价格: {first_price} -> {last_price} ({chg:+.2f}%)")
    except Exception as e:
        print(f"  Error: {e}")
