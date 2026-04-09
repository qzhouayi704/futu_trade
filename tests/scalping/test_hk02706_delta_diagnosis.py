"""
HK.02706 Delta 数据异常诊断测试脚本

目标：
1. 从 FutuClient 获取 HK.02706 的真实逐笔数据
2. 将数据喂给 DeltaCalculator，模拟完整计算流程
3. 验证系统是否能正常生成 Delta 数据
4. 输出详细诊断信息，定位具体问题所在
"""

import sys
from pathlib import Path
import asyncio

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from futu import RET_OK
from simple_trade.api.futu_client import FutuClient
from simple_trade.services.scalping.calculators.delta_calculator import DeltaCalculator
from simple_trade.services.scalping.data_converter import row_to_tick
from simple_trade.services.scalping.models import TickData


def fetch_realtime_ticks(futu_client, stock_code: str, num: int = 1000):
    """从 FutuClient 获取实时逐笔数据"""
    ret, df = futu_client.get_rt_ticker(stock_code, num)
    return ret, df


def convert_dataframe_to_ticks(df, stock_code: str) -> list[TickData]:
    """将 DataFrame 转换为 TickData 列表"""
    ticks = []
    for _, row in df.iterrows():
        tick = row_to_tick(stock_code, row)  # 注意参数顺序：stock_code 在前
        if tick:
            ticks.append(tick)
    return ticks


async def simulate_delta_calculation(
    ticks: list[TickData],
    stock_code: str,
    min_volume: int = 100,
    period_seconds: int = 10
) -> dict:
    """模拟 DeltaCalculator 完整计算流程"""

    # 创建独立的 DeltaCalculator 实例
    calculator = DeltaCalculator(
        socket_manager=None,  # 测试不需要 WebSocket
        persistence=None,     # 测试不需要持久化
        market="HK"
    )

    # 统计信息
    stats = {
        "total_ticks": len(ticks),
        "filtered_ticks": 0,
        "direction_stats": {"BUY": 0, "SELL": 0, "NEUTRAL": 0},
        "delta_periods": []
    }

    # 按时间戳排序
    ticks.sort(key=lambda t: t.timestamp)

    if not ticks:
        return stats

    # 模拟逐笔处理
    last_flush_time = ticks[0].timestamp

    for tick in ticks:
        # 检查是否被过滤
        if tick.volume < min_volume:
            stats["filtered_ticks"] += 1
            continue

        # 调用 on_tick
        direction = calculator.on_tick(stock_code, tick)
        stats["direction_stats"][direction.name] += 1

        # 检查是否需要 flush（基于真实时间戳）
        if tick.timestamp - last_flush_time >= period_seconds * 1000:
            delta_data = await calculator.flush_period(stock_code)
            if delta_data:
                stats["delta_periods"].append({
                    "delta": delta_data.delta,
                    "volume": delta_data.volume,
                    "timestamp": delta_data.timestamp
                })
            last_flush_time = tick.timestamp

    # 最后一次 flush
    delta_data = await calculator.flush_period(stock_code)
    if delta_data:
        stats["delta_periods"].append({
            "delta": delta_data.delta,
            "volume": delta_data.volume,
            "timestamp": delta_data.timestamp
        })

    return stats


def print_diagnosis_report(stats: dict, stock_code: str):
    """打印详细诊断报告"""

    print(f"\n{'='*60}")
    print(f"【{stock_code} Delta 计算诊断报告】")
    print(f"{'='*60}\n")

    # 原始数据统计
    print("原始数据统计:")
    print(f"  - 总 tick 数: {stats['total_ticks']}")
    print(f"  - 过滤掉的 tick 数: {stats['filtered_ticks']} (volume < 100)")
    print(f"  - 有效 tick 数: {stats['total_ticks'] - stats['filtered_ticks']}")

    # 方向分类统计
    total_classified = sum(stats['direction_stats'].values())
    print(f"\n方向分类统计:")
    for direction, count in stats['direction_stats'].items():
        pct = (count / total_classified * 100) if total_classified > 0 else 0
        print(f"  - {direction}: {count} 笔, 占比 {pct:.1f}%")

    # Delta 周期统计
    periods = stats['delta_periods']
    print(f"\nDelta 周期统计:")
    print(f"  - 总周期数: {len(periods)}")

    if periods:
        deltas = [p['delta'] for p in periods]
        avg_delta = sum(deltas) / len(deltas)
        max_delta = max(deltas)
        min_delta = min(deltas)

        print(f"  - 平均 Delta: {avg_delta:+.1f}")
        print(f"  - 最大 Delta: {max_delta:+.1f}")
        print(f"  - 最小 Delta: {min_delta:+.1f}")

        # 显示前 5 个周期
        print(f"\n前 5 个周期详情:")
        for i, p in enumerate(periods[:5], 1):
            print(f"  周期{i}: delta={p['delta']:+.0f}, volume={p['volume']}")

    # 结论
    print(f"\n{'='*60}")
    print("【结论】")
    if len(periods) > 0:
        print(f"[成功] DeltaCalculator 能够正常处理 {stock_code} 的逐笔数据")
        print(f"[成功] 生成了 {len(periods)} 个有效的 Delta 周期")
    else:
        print(f"[失败] DeltaCalculator 无法生成 Delta 数据")
        if stats['filtered_ticks'] > stats['total_ticks'] * 0.9:
            print(f"[警告] 原因：超过 90% 的 tick 被过滤（volume < 100）")
        elif total_classified == 0:
            print(f"[警告] 原因：无法分类任何 tick 的方向")
    print(f"{'='*60}\n")


def main():
    stock_code = "HK.02706"

    print(f"开始测试 {stock_code} 的 Delta 计算...")

    # 1. 初始化 FutuClient
    print("\n=== 步骤1：连接 FutuClient ===")
    futu_client = FutuClient()
    success = futu_client.connect()
    if not success:
        print(f"[失败] 连接失败")
        return
    print("[成功] 连接成功")

    # 2. 订阅 Ticker 数据
    print(f"\n=== 步骤2：订阅 {stock_code} Ticker 数据 ===")
    from futu import SubType
    ret, msg = futu_client.client.subscribe([stock_code], [SubType.TICKER], subscribe_push=False)
    if ret != RET_OK:
        print(f"[失败] 订阅失败: {msg}")
        futu_client.disconnect()
        return
    print("[成功] 订阅成功")

    # 3. 获取逐笔数据
    print(f"\n=== 步骤3：获取 {stock_code} 逐笔数据 ===")
    ret, df = fetch_realtime_ticks(futu_client, stock_code, num=1000)
    if ret != RET_OK:
        print(f"[失败] 获取失败: {df}")
        futu_client.disconnect()
        return

    print(f"[成功] 获取到 {len(df)} 笔逐笔数据")
    if len(df) > 0:
        print(f"   时间范围: {df['time'].min()} ~ {df['time'].max()}")
        print(f"   成交量范围: {df['volume'].min()} ~ {df['volume'].max()}")

    # 4. 转换数据格式
    print(f"\n=== 步骤4：转换数据格式 ===")
    ticks = convert_dataframe_to_ticks(df, stock_code)
    print(f"[成功] 成功转换 {len(ticks)} 笔 TickData")

    # 5. 模拟 Delta 计算
    print(f"\n=== 步骤5：模拟 Delta 计算 ===")
    stats = asyncio.run(simulate_delta_calculation(ticks, stock_code))

    # 6. 输出诊断报告
    print_diagnosis_report(stats, stock_code)

    # 7. 清理资源
    futu_client.disconnect()
    print("测试完成")


if __name__ == "__main__":
    main()
