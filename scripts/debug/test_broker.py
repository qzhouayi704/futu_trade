import asyncio
import os
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
        futu_client_wrapper = getattr(container, 'futu_client', None)
        quote_client = futu_client_wrapper.client if futu_client_wrapper else None
        
        if not quote_client:
            print("Quote client not found")
            return
            
        print("Waiting for connection to stabilize...")
        await asyncio.sleep(1)
        
        stock_code = 'HK.02656'
        print(f"--- 测试获取 {stock_code} 的经纪商队列 (Broker Queue) ---")
        
        # Futu API method is get_broker_queue
        # Wait, get_broker_queue requires subscribing to broker queue first!
        # Let's subscribe first
        print("Subscribing to broker queue...")
        sub_ret, sub_err = quote_client.subscribe([stock_code], [SubType.BROKER])
        if sub_ret == RET_OK:
            print("Subscription successful.")
            
            # Now get the broker queue
            result = quote_client.get_broker_queue(stock_code)
            print(f"Broker queue result: {result}")
                
            # Unsubscribe
            quote_client.unsubscribe([stock_code], [SubType.BROKER])
        else:
            print(f"Failed to subscribe to broker queue: {sub_err}")
            print("Note: get_broker_queue might require Level 2 real-time market data privileges.")

    finally:
        if hasattr(container, 'stop_all'):
            await container.stop_all()

if __name__ == '__main__':
    asyncio.run(main())
