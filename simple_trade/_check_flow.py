#!/usr/bin/env python3
"""检查资金流时间线数据"""
import json, urllib.request

url = "http://localhost:5001/api/enhanced-heat/capital-flow-timeline/HK.06821"
resp = urllib.request.urlopen(url)
data = json.load(resp)

tl = data["data"]["timeline"]
print(f"总数据点: {len(tl)}")
print(f"{'时间':>6}  {'buy_in':>8}  {'sell_in':>8}  {'net_buy':>8}  {'cum_net':>8}")
print("-" * 50)

# 打印12:00-13:30 区间（图中标记的区域）
for p in tl:
    t = p["time"]
    if "12:0" <= t <= "13:3":
        print(f"{t:>6}  {p.get('buy_in',0):>8.1f}  {p.get('sell_in',0):>8.1f}  {p.get('net_buy',0):>8.1f}  {p.get('cum_net',0):>8.1f}")
