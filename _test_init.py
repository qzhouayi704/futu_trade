#!/usr/bin/env python3
import urllib.request, json

req = urllib.request.Request(
    'http://127.0.0.1:5001/api/stocks/init',
    data=json.dumps({'force_refresh': True}).encode(),
    headers={'Content-Type': 'application/json'},
    method='POST'
)
try:
    resp = urllib.request.urlopen(req, timeout=120)
    print(resp.read().decode())
except Exception as e:
    print(f'Error: {e}')
    if hasattr(e, 'read'):
        print(e.read().decode())
