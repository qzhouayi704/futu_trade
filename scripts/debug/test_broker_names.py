import asyncio, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from simple_trade.core.container import ServiceContainer
from simple_trade.config.config import ConfigManager
from simple_trade.services.analysis.flow.broker_consistency_filter import BrokerConsistencyFilter, RETAIL_BROKER_KEYWORDS, INSTITUTIONAL_BROKER_KEYWORDS
from futu import *
from dotenv import load_dotenv
load_dotenv()

async def main():
    config = ConfigManager.load_config()
    container = ServiceContainer(config)
    container.initialize_all()
    client = container.futu_client.client
    await asyncio.sleep(1)

    for code in ['HK.02656', 'HK.02635']:
        client.subscribe([code], [SubType.BROKER])
        ret, bid_df, ask_df = client.get_broker_queue(code)
        if ret != RET_OK:
            print(f"{code} FAILED")
            continue
        print(f"\n=== {code} ===")
        print("BID (buyers):")
        seen = set()
        for _, row in bid_df.sort_values('bid_broker_pos').iterrows():
            name = str(row['bid_broker_name']).strip()
            if name not in seen:
                seen.add(name)
                is_retail = any(kw in name for kw in RETAIL_BROKER_KEYWORDS)
                is_inst = any(kw in name for kw in INSTITUTIONAL_BROKER_KEYWORDS)
                tag = "[散户]" if is_retail else "[机构]" if is_inst else "[未分类]"
                print(f"  pos={row['bid_broker_pos']} id={row['bid_broker_id']} {tag} {name}")
                if len(seen) >= 8:
                    break
        print("ASK (sellers):")
        seen = set()
        for _, row in ask_df.sort_values('ask_broker_pos').iterrows():
            name = str(row['ask_broker_name']).strip()
            if name not in seen:
                seen.add(name)
                is_retail = any(kw in name for kw in RETAIL_BROKER_KEYWORDS)
                is_inst = any(kw in name for kw in INSTITUTIONAL_BROKER_KEYWORDS)
                tag = "[散户]" if is_retail else "[机构]" if is_inst else "[未分类]"
                print(f"  pos={row['ask_broker_pos']} id={row['ask_broker_id']} {tag} {name}")
                if len(seen) >= 8:
                    break
        client.unsubscribe([code], [SubType.BROKER])

if __name__ == '__main__':
    asyncio.run(main())
