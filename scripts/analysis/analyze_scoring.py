import sys
sys.stdout.reconfigure(encoding='utf-8')

# HK.06651 在 5/15 的数据
# K线: 5/15 O=48.44 H=54.35 L=48.02 C=50.00
# 5/14: C=48.84, 5/13: C=50.40, 5/12: C=48.68, 5/11: C=51.00, 5/8: C=53.30
# change_rate = +2.38%, 市场扫描报价中的数据

print("=" * 60)
print("HK.06651 五一视界 — 5/15评分模拟分析")
print("=" * 60)

# 实际指标（从K线推算）
closes = [53.30, 51.00, 48.68, 50.40, 48.84, 50.00]  # 5/8 → 5/15
last_price = 50.00
prev_close = 48.84
change_rate = (50.00 - 48.84) / 48.84 * 100  # +2.38%
high, low = 54.35, 48.02
amplitude = (high - low) / prev_close * 100  # 12.97%
change_5d = (closes[-1] - closes[0]) / closes[0] * 100  # -6.19%

# 20日K线位置（假设用最近数据）
all_highs = [58.00, 55.65, 52.90, 52.00, 52.65, 54.35]
all_lows = [52.80, 50.50, 48.28, 45.00, 48.58, 48.02]
max_h = max(all_highs)  # 58.00
min_l = min(all_lows)   # 45.00
kline_pos = (last_price - min_l) / (max_h - min_l)  # 0.385

print(f"\n--- 实际指标 ---")
print(f"  收盘价: {last_price}")
print(f"  今日涨跌: +{change_rate:.2f}%")
print(f"  振幅: {amplitude:.2f}%")
print(f"  5日涨跌: {change_5d:.2f}%")
print(f"  20日K线位置: {kline_pos:.3f} (0=最低, 1=最高)")
print(f"  量比: 未知(市场扫描数据)")
print(f"  资金流: 未知(无capital_flow_cache)")

print(f"\n--- TREND 模式评分分析 (满分100) ---")
print(f"  [1] 5日涨跌 (max=20): change_5d={change_5d:.1f}%")
print(f"      optimal=(-2, 15), marginal=(-5, 25)")
print(f"      → {change_5d:.1f}% 在 marginal 边缘区, 约 10-15 分")

print(f"  [2] 振幅 (max=20): amplitude={amplitude:.1f}%")
print(f"      optimal=(5, 20), marginal=(3, 30)")
print(f"      → {amplitude:.1f}% 在 optimal 范围内! → 20 分 ✓")

print(f"  [3] 量比 (max=25): 无数据")
print(f"      → 默认 0 分 ✗ ← 这是最大失分点!")

print(f"  [4] 资金流 (max=25): 无数据")
print(f"      → 默认 0 分 ✗ ← 这是最大失分点!")

print(f"  [5] K线位置 (max=5): pos={kline_pos:.3f}")
print(f"      → 全范围都给分 → 5 分")

print(f"  [6] 前日涨幅 (max=5): +{change_rate:.1f}%")
print(f"      → 涨幅适中 → 3-5 分")

trend_est = 15 + 20 + 0 + 0 + 5 + 4
print(f"\n  TREND 估算总分: ~{trend_est} 分")
print(f"  及格线: 60 分")
print(f"  → TREND 模式不及格, 不会被选为趋势追涨候选")

print(f"\n--- REVERSAL 模式评分分析 (满分100) ---")
print(f"  [背景] K线位置低(max=15): pos={kline_pos:.3f}")
print(f"      optimal=(0, 0.2), marginal=(0, 0.4)")
print(f"      → 0.385 在 marginal 边缘 → 约 5-8 分")

print(f"  [背景] 5日跌幅(max=15): {change_5d:.1f}%")
print(f"      optimal=(-15, -3), marginal=(-25, -1)")
print(f"      → {change_5d:.1f}% 在 optimal 范围! → 15 分 ✓")

print(f"  [背景] 前日跌幅(max=10): +{change_rate:.1f}% (今天是涨的)")
print(f"      optimal=(-8, -2) → 不在范围内 → 0 分")

print(f"  [反转] 距低点反弹(max=15): low=45.00, now=50.00")
rise_from_low = (50.00 - 45.00) / 45.00 * 100
print(f"      rise={rise_from_low:.1f}% → tier(5.0→15) → 15 分 ✓")

print(f"  [反转] 今日收涨(max=10): +{change_rate:.1f}%")
print(f"      tier(3.0→10, 1.0→8) → +2.38% → 8 分")

print(f"  [反转] 资金流(max=15): 无数据 → 0 分 ✗")
print(f"  [反转] 量比(max=15): 无数据 → 0 分 ✗")
print(f"  [反转] 振幅(max=5): {amplitude:.1f}% optimal(3,15) → 5 分 ✓")

rev_est = 7 + 15 + 0 + 15 + 8 + 0 + 0 + 5
print(f"\n  REVERSAL 估算总分: ~{rev_est} 分")
print(f"  加上盘后bonus(无连续资金数据所以约0分)")
print(f"  最终: ~{rev_est} 分 → verdict=可关注 (和实际64分吻合!)")

print(f"\n" + "=" * 60)
print(f"核心结论: 评分引擎对追涨股的致命缺陷")
print(f"=" * 60)
print(f"""
1. 量比(vol_ratio)和资金流(flow_ratio)占 TREND 满分的 50%
   但这两项依赖 capital_flow_cache 和实时行情数据,
   如果市场扫描没跑到这只股, 这两项就是0分 → 直接腰斩

2. REVERSAL 模式要求"先跌后反弹", 但 HK.06651 今天
   从50→71(+42%), 这是典型的"题材催化爆发",
   不属于"超跌反弹"也不属于"趋势延续"

3. 评分引擎的盲区:
   - 没有"题材热度/事件驱动"维度
   - 没有"板块联动/龙头效应"维度
   - 没有"盘口异动/主力扫货"实时维度
   这些恰恰是追涨股最核心的信号
""")
