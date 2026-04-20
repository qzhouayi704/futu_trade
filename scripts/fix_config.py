#!/usr/bin/env python3
import json
f = '/opt/futu_trade_sys/simple_trade/config.json'
with open(f) as fp:
    d = json.load(fp)
es = d.get('enabled_strategies', [])
print('Before:', [s.get('strategy_id') for s in es])
es = [s for s in es if s.get('strategy_id') != 'swing']
d['enabled_strategies'] = es
print('After:', [s.get('strategy_id') for s in es])
with open(f, 'w') as fp:
    json.dump(d, fp, indent=2, ensure_ascii=False)
print('Done')
