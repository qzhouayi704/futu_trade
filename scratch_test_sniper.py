#!/usr/bin/env python3
"""测试 IntradaySniper 手动扫描"""
import asyncio
import sqlite3

class FakeDB:
    def get_connection(self):
        return sqlite3.connect('/opt/futu_trade_sys/simple_trade/data/trade.db')

class FakeContainer:
    def __init__(self):
        self.db_manager = FakeDB()
        self._socket_manager = None
        self.wechat_alert_service = None

from simple_trade.services.sniper.intraday_sniper import IntradaySniper

async def test():
    container = FakeContainer()
    sniper = IntradaySniper(container)
    await sniper._do_scan()
    signals = sniper.get_today_signals()
    print(f"Total signals: {len(signals)}")
    reds = sum(1 for s in signals if s['is_red'])
    greens = len(signals) - reds
    print(f"Red: {reds}, Green: {greens}")
    print()
    for s in signals:
        print(f"  [{s['time']}] {s['emoji']} {s['stock_name']:<12} @ {s['price']:>8} | {s['detail']}")

asyncio.run(test())
