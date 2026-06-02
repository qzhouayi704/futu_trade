#!/usr/bin/env python3
"""一次性脚本：手动触发持仓操作建议生成"""
import asyncio
import json
import sys
sys.path.insert(0, '/opt/futu_trade_sys')

from simple_trade.database.core.db_manager import DatabaseManager
from simple_trade.services.analysis.position_advisor import PositionAdvisor

db = DatabaseManager('/opt/futu_trade_sys/data/trade.db')
advisor = PositionAdvisor(db)

# 尝试通过交易服务获取持仓
try:
    from simple_trade.services.trading.futu_trade_service import FutuTradeService
    trade_svc = FutuTradeService(host='127.0.0.1', port=11111)
    result = trade_svc.get_positions()
    if result.get('success') and result.get('positions'):
        positions = result['positions']
        print(f"获取到 {len(positions)} 只持仓")
        advices = asyncio.run(advisor.generate_all_advice(positions))
        for a in advices:
            print(json.dumps(a.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"持仓获取失败: {result.get('message', '无')}")
except Exception as e:
    print(f"交易服务异常: {e}")
    # 查看已有建议
    existing = advisor.get_latest_advice()
    print(f"已有建议: {len(existing)} 条")
