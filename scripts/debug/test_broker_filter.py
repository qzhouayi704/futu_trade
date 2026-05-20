#!/usr/bin/env python3
"""验证经纪商一致性过滤器 — 用 HK.02656 和 HK.02635 分别测试"""
import asyncio
from simple_trade.core.container import ServiceContainer
from simple_trade.config.config import ConfigManager
from simple_trade.services.analysis.flow.broker_consistency_filter import BrokerConsistencyFilter
from dotenv import load_dotenv
load_dotenv()

async def main():
    config = ConfigManager.load_config()
    container = ServiceContainer(config)
    try:
        container.initialize_all()
        futu_client = getattr(container, 'futu_client', None)
        if not futu_client:
            print("futu_client not found")
            return

        print("=== 经纪商一致性过滤器验证 ===\n")
        bf = BrokerConsistencyFilter(futu_client)

        # Test 1: HK.02656 (今日暴涨 42%，已知有机构出货)
        print("--- Test 1: HK.02656 (健康160, 暴涨标的) ---")
        r1 = bf.check_distribution_trap('HK.02656', change_pct=42.0)
        print(f"  诱多陷阱: {r1.is_trap}")
        print(f"  置信度: {r1.trap_confidence:.0%}")
        print(f"  买方前5: {r1.top_buyers}")
        print(f"  卖方前5: {r1.top_sellers}")
        print(f"  机构卖方数: {r1.institutional_sell_count}")
        print(f"  散户买方数: {r1.retail_buy_count}")
        print(f"  原因: {r1.reason}")

        print()

        # Test 2: HK.02635 (你持仓的巨星传奇)
        print("--- Test 2: HK.02635 (巨星传奇, 持仓标的) ---")
        r2 = bf.check_distribution_trap('HK.02635', change_pct=5.0)
        print(f"  诱多陷阱: {r2.is_trap}")
        print(f"  置信度: {r2.trap_confidence:.0%}")
        print(f"  买方前5: {r2.top_buyers}")
        print(f"  卖方前5: {r2.top_sellers}")
        print(f"  机构卖方数: {r2.institutional_sell_count}")
        print(f"  散户买方数: {r2.retail_buy_count}")
        print(f"  原因: {r2.reason}")

    finally:
        pass

if __name__ == '__main__':
    asyncio.run(main())
