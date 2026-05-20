import asyncio
import os
from simple_trade.core.container import ServiceContainer
from simple_trade.config.config import ConfigManager
from dotenv import load_dotenv
import logging

load_dotenv()
logging.basicConfig(level=logging.INFO)

async def main():
    config = ConfigManager.load_config()
    container = ServiceContainer(config)
    try:
        container.initialize_all()
        futu_trade = getattr(container, 'futu_trade_service', None)
        if not futu_trade:
            print("Trade service not found")
            return
            
        print("Futu connected:", futu_trade.is_trade_ready())
        
        await asyncio.sleep(2) # Wait for Trade API connection
        
        # Call get_positions to force initialization / unlock
        pos_res = await asyncio.get_event_loop().run_in_executor(None, futu_trade.get_positions)
        print("Positions Check:", pos_res.get('success'))

        # Test Buying 400 shares of HK.02635
        qty = 400
        print(f"--- Executing Market Buy for {qty} shares of HK.02635 ---")
        
        order_manager = futu_trade.order_manager
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: order_manager.place_order(
                stock_code='HK.02635',
                trade_type='BUY',
                price=0, # 0 indicates market order
                quantity=qty
            )
        )
        print(f"Order Placement Result: {result}")
        
    finally:
        if hasattr(container, 'stop_all'):
            await container.stop_all()

if __name__ == '__main__':
    asyncio.run(main())
