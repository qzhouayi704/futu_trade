#!/usr/bin/env python3
"""通过富途API获取真实交易记录"""
import json
import sys
from datetime import datetime, timedelta

try:
    from futu import OpenSecTradeContext, TrdEnv, TrdMarket, SecurityFirm, RET_OK
except ImportError:
    print("Error: futu package not installed")
    sys.exit(1)

HOST = "127.0.0.1"
PORT = 11111
TRD_ENV = TrdEnv.REAL
OUT_PATH = "scripts/futu_real_trades.json"

result = {}

trd_ctx = OpenSecTradeContext(filter_trdmarket=TrdMarket.HK, host=HOST, port=PORT, security_firm=SecurityFirm.FUTUSECURITIES)

try:
    # 1. 解锁交易
    ret, data = trd_ctx.unlock_trade(password="910429")
    result["unlock"] = {"ret": ret, "msg": str(data) if ret != RET_OK else "OK"}
    
    if ret != RET_OK:
        print(f"解锁失败: {data}")
        # 继续尝试，某些查询可能不需要解锁
    
    # 2. 获取账户信息
    ret, data = trd_ctx.accinfo_query(trd_env=TRD_ENV)
    if ret == RET_OK:
        result["account_info"] = data.to_dict('records')
        print(f"账户信息: {len(data)} 条")
    else:
        result["account_info_error"] = str(data)
    
    # 3. 获取当前持仓
    ret, data = trd_ctx.position_list_query(trd_env=TRD_ENV)
    if ret == RET_OK:
        positions = data.to_dict('records')
        result["positions"] = positions
        print(f"当前持仓: {len(positions)} 只股票")
        for p in positions:
            pnl = p.get('pl_val', 0)
            pnl_pct = p.get('pl_ratio', 0)
            print(f"  {p.get('code', '')} {p.get('stock_name', '')} "
                  f"持仓{p.get('qty', 0)}股 成本{p.get('cost_price', 0):.3f} "
                  f"现价{p.get('market_val', 0):.0f} 盈亏{pnl:.0f} ({pnl_pct*100:.1f}%)")
    else:
        result["positions_error"] = str(data)
    
    # 4. 获取今日成交
    ret, data = trd_ctx.deal_list_query(trd_env=TRD_ENV)
    if ret == RET_OK:
        today_deals = data.to_dict('records')
        result["today_deals"] = today_deals
        print(f"\n今日成交: {len(today_deals)} 条")
        for d in today_deals:
            print(f"  {d.get('trd_side', '')} {d.get('code', '')} {d.get('stock_name', '')} "
                  f"{d.get('qty', 0)}股 @ {d.get('price', 0):.3f} {d.get('create_time', '')}")
    else:
        result["today_deals_error"] = str(data)
    
    # 5. 获取今日订单
    ret, data = trd_ctx.order_list_query(trd_env=TRD_ENV)
    if ret == RET_OK:
        today_orders = data.to_dict('records')
        result["today_orders"] = today_orders
        print(f"\n今日订单: {len(today_orders)} 条")
        for o in today_orders:
            print(f"  {o.get('trd_side', '')} {o.get('code', '')} {o.get('stock_name', '')} "
                  f"{o.get('qty', 0)}股 @ {o.get('price', 0):.3f} "
                  f"状态:{o.get('order_status', '')} {o.get('create_time', '')}")
    else:
        result["today_orders_error"] = str(data)
    
    # 6. 获取历史成交（最近90天）
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
    
    ret, data = trd_ctx.history_deal_list_query(
        trd_env=TRD_ENV,
        start=start_date,
        end=end_date
    )
    if ret == RET_OK:
        history_deals = data.to_dict('records')
        result["history_deals"] = history_deals
        result["history_deals_count"] = len(history_deals)
        print(f"\n历史成交({start_date} ~ {end_date}): {len(history_deals)} 条")
        for d in history_deals:
            print(f"  {d.get('create_time', '')} {d.get('trd_side', '')} "
                  f"{d.get('code', '')} {d.get('stock_name', '')} "
                  f"{d.get('qty', 0)}股 @ {d.get('price', 0):.3f}")
    else:
        result["history_deals_error"] = str(data)
        print(f"\n历史成交查询失败: {data}")
    
    # 7. 获取历史订单
    ret, data = trd_ctx.history_order_list_query(
        trd_env=TRD_ENV,
        start=start_date,
        end=end_date
    )
    if ret == RET_OK:
        history_orders = data.to_dict('records')
        result["history_orders"] = history_orders
        result["history_orders_count"] = len(history_orders)
        print(f"\n历史订单({start_date} ~ {end_date}): {len(history_orders)} 条")
        for o in history_orders:
            print(f"  {o.get('create_time', '')} {o.get('trd_side', '')} "
                  f"{o.get('code', '')} {o.get('stock_name', '')} "
                  f"{o.get('qty', 0)}股 @ {o.get('price', 0):.3f} "
                  f"成交{o.get('dealt_qty', 0)}股@{o.get('dealt_avg_price', 0):.3f} "
                  f"状态:{o.get('order_status', '')}")
    else:
        result["history_orders_error"] = str(data)
        print(f"\n历史订单查询失败: {data}")

finally:
    trd_ctx.close()

# 保存结果
with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2, default=str)

print(f"\n数据已保存到 {OUT_PATH}")
