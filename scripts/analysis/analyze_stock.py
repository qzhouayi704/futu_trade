import asyncio
import os
from simple_trade.core.container import ServiceContainer
from simple_trade.config.config import ConfigManager
from dotenv import load_dotenv
import logging

load_dotenv()
# logging.basicConfig(level=logging.WARNING)

async def main():
    config = ConfigManager.load_config()
    container = ServiceContainer(config)
    try:
        container.initialize_all()
        futu_trade = getattr(container, 'futu_trade_service', None)
        levels_svc = getattr(container, 'intraday_levels_service', None)
        capital_svc = getattr(container, 'capital_flow_signal_engine', None)
        
        stock_code = 'HK.02656'
        print(f"=== Analyzing {stock_code} ===")
        
        # Get quotes
        if futu_trade and futu_trade.is_trade_ready():
            await asyncio.sleep(1) # wait for connection
            quote_res = await asyncio.get_event_loop().run_in_executor(
                None, lambda: futu_trade.client.get_market_snapshot([stock_code])
            )
            if quote_res[0] == 0 and not quote_res[1].empty:
                quote = quote_res[1].iloc[0]
                print(f"\n--- 基本报价 ---")
                print(f"现价: {quote.get('last_price', 'N/A')}")
                print(f"涨跌幅: {quote.get('change_rate', 'N/A')}%")
                print(f"换手率: {quote.get('turnover_rate', 'N/A')}%")
                print(f"成交额: {quote.get('turnover', 'N/A')}")
        
        pass
        
        pass

    except Exception as e:
        print(f"Error: {e}")
    finally:
        if hasattr(container, 'stop_all'):
            await container.stop_all()

if __name__ == '__main__':
    asyncio.run(main())
