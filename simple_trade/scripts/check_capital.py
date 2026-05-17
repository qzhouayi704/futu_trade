import sys
sys.path.insert(0, r'd:\Program Files\futu_trade_sys')
from simple_trade.config.config import ConfigManager
config = ConfigManager.load_config(r'd:\Program Files\futu_trade_sys\simple_trade\config.json')
key = config.gemini.api_key
model = config.gemini.model
print(f'api_key: {key[:15]}... (len={len(key)})')
print(f'model: {model}')
expected = 'AIzaSyC4e7kbq2AvTgdrqfPbOU0DkjV_TR5L8oo'
print(f'key matches expected: {key == expected}')
