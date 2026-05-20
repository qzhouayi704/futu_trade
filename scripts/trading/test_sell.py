import asyncio
import os
from simple_trade.core.container import ServiceContainer
from simple_trade.config.config import ConfigManager
from simple_trade.services.trading.profit.intraday_risk_manager import IntradayRiskManager
from dotenv import load_dotenv

load_dotenv()

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
                print(f"Found position for HK.02635: {target['qty']} shares, cost: {target.get('cost_price')}")
                
                # Check intraday levels
                levels_svc = getattr(container, 'intraday_levels_service', None)
                if levels_svc:
                    levels = await levels_svc.get_levels('HK.02635')
                    print(f"Current price: {levels.current_price}")
                    
                    # TEST THE MANAGER
                    print("\n--- Testing IntradayRiskManager ---")
                    manager = IntradayRiskManager(container.db_manager, futu_trade.client, levels_svc, futu_trade)
                    
                    # Fake a quote that is slightly below the support level to trigger breakdown stop loss
                    support = levels_svc.get_nearest_strong_support(levels, levels.current_price)
                    if support:
                        fake_price = support.price * 0.997 # below 0.998 threshold
                        print(f"Fake current price below support {support.price} -> {fake_price}")
                        fake_quote = {'last_price': fake_price, 'code': 'HK.02635', 'name': 'TEST_STOCK'}
                        actions = await manager.check_risks('HK.02635', fake_quote, target, None)
                        print(f"Manager check result actions: {actions}")
                    else:
                        print("No strong support found to test breakdown.")
                        # Force a test sell of 100 shares if we want
                        print("\n--- Testing direct execute_market_sell ---")
                        # res = manager._execute_sell('HK.02635', 100, "TEST SELL SCRIPT")
                        # print(res)
            else:
                print("No position found for HK.02635 in account.")
        else:
            print("Failed to get positions:", pos_res.get('message'))
    finally:
        if hasattr(container, 'stop_all'):
            await container.stop_all()

if __name__ == '__main__':
    asyncio.run(main())
