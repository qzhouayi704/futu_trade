import asyncio
from simple_trade.core.container import ServiceContainer
from simple_trade.config.config import ConfigManager
from futu import *
from dotenv import load_dotenv
load_dotenv()

async def main():
    config = ConfigManager.load_config()
    container = ServiceContainer(config)
    try:
        container.initialize_all()
        client = container.futu_client.client
        await asyncio.sleep(1)
        client.subscribe(['HK.02635'], [SubType.BROKER])
        ret, bid_df, ask_df = client.get_broker_queue('HK.02635')
        if ret == RET_OK:
            print("=== BID COLUMNS ===")
            print(bid_df.columns.tolist())
            print(bid_df.head(5).to_string())
            print("\n=== ASK COLUMNS ===")
            print(ask_df.columns.tolist())
            print(ask_df.head(5).to_string())
        else:
            print(f"Failed: {bid_df}")
        client.unsubscribe(['HK.02635'], [SubType.BROKER])
    finally:
        pass

if __name__ == '__main__':
    asyncio.run(main())
