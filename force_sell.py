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
        
        pos_res = await asyncio.get_event_loop().run_in_executor(None, futu_trade.get_positions)
        if pos_res.get('success'):
            positions = pos_res.get('positions', [])
            target = next((p for p in positions if p['stock_code'] == 'HK.02635'), None)
            if target:
                qty = target['qty']
                print(f"Found position for HK.02635: {qty} shares, cost: {target.get('cost_price')}")
                
                print(f"--- Executing Market Sell for {qty} shares of HK.02635 ---")
                
                # Use place_order directly
                # trade_type='SELL', order_type='MARKET' (if supported) or we can just send price=0 which futu wrapper might convert to market order
                order_manager = futu_trade.order_manager
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: order_manager.place_order(
                        stock_code='HK.02635',
                        trade_type='SELL',
                        price=0, # 0 indicates market order in our wrapper
                        quantity=qty
                    )
                )
                print(f"Order Placement Result: {result}")
            else:
                print("No position found for HK.02635 in account.")
        else:
            print("Failed to get positions:", pos_res.get('message'))
    finally:
        if hasattr(container, 'stop_all'):
            await container.stop_all()

if __name__ == '__main__':
    asyncio.run(main())
