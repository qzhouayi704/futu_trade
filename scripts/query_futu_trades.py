"""查询富途API交易数据"""
from futu import OpenSecTradeContext, TrdMarket, TrdEnv
from datetime import datetime, timedelta

def main():
    trd_ctx = OpenSecTradeContext(
        host="127.0.0.1", port=11111, 
        filter_trdmarket=TrdMarket.HK, security_firm=None
    )
    
    # 1. 查看当前真实持仓
    ret, data = trd_ctx.position_list_query(trd_env=TrdEnv.REAL)
    if ret == 0:
        print("=== 当前真实持仓 ===")
        if len(data) > 0:
            for _, row in data.iterrows():
                print(f"  {row['code']} qty={row['qty']} cost={row['cost_price']:.3f} "
                      f"market_val={row['market_val']:.2f} pl_ratio={row['pl_ratio']:.2f}%")
        else:
            print("  无持仓")
    else:
        print(f"查询持仓失败: {data}")
    
    # 2. 查看最近历史成交
    end = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    ret, data = trd_ctx.history_deal_list_query(start=start, end=end, trd_env=TrdEnv.REAL)
    if ret == 0:
        print(f"\n=== 最近7天真实成交记录 ({len(data)}条) ===")
        for _, row in data.iterrows():
            print(f"  {row['create_time']} {row['code']} {row['trd_side']} "
                  f"qty={row['qty']} price={row['price']} deal_id={row['deal_id']}")
    else:
        print(f"查询成交失败: {data}")
    
    # 3. 查看模拟账户持仓
    ret, data = trd_ctx.position_list_query(trd_env=TrdEnv.SIMULATE)
    if ret == 0:
        print(f"\n=== 模拟账户持仓 ({len(data)}条) ===")
        if len(data) > 0:
            for _, row in data.iterrows():
                print(f"  {row['code']} qty={row['qty']} cost={row['cost_price']:.3f} "
                      f"market_val={row['market_val']:.2f} pl_ratio={row['pl_ratio']:.2f}%")
        else:
            print("  无持仓")
    else:
        print(f"查询模拟持仓失败: {data}")
    
    # 4. 查看最近模拟成交
    ret, data = trd_ctx.history_deal_list_query(start=start, end=end, trd_env=TrdEnv.SIMULATE)
    if ret == 0:
        print(f"\n=== 最近7天模拟成交记录 ({len(data)}条) ===")
        if len(data) > 0:
            for _, row in data.iterrows():
                print(f"  {row['create_time']} {row['code']} {row['trd_side']} "
                      f"qty={row['qty']} price={row['price']}")
        else:
            print("  无模拟成交")
    else:
        print(f"查询模拟成交失败: {data}")
    
    # 5. 查看最近30天历史订单
    start30 = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    ret, data = trd_ctx.history_order_list_query(start=start30, end=end, trd_env=TrdEnv.REAL)
    if ret == 0:
        print(f"\n=== 最近30天真实历史订单 ({len(data)}条) ===")
        if len(data) > 0:
            for _, row in data.iterrows():
                print(f"  {row['create_time']} {row['code']} {row['trd_side']} "
                      f"qty={row['qty']} price={row['price']} status={row['order_status']}")
    else:
        print(f"查询历史订单失败: {data}")
    
    # 6. 账户资金
    ret, data = trd_ctx.accinfo_query(trd_env=TrdEnv.REAL)
    if ret == 0:
        print(f"\n=== 真实账户资金 ===")
        for _, row in data.iterrows():
            print(f"  总资产={row['total_assets']:.2f} 现金={row['cash']:.2f} "
                  f"市值={row['market_val']:.2f} 浮动盈亏={row['unrealized_pl']:.2f}")
    
    ret, data = trd_ctx.accinfo_query(trd_env=TrdEnv.SIMULATE)
    if ret == 0:
        print(f"\n=== 模拟账户资金 ===")
        for _, row in data.iterrows():
            print(f"  总资产={row['total_assets']:.2f} 现金={row['cash']:.2f} "
                  f"市值={row['market_val']:.2f}")
    
    trd_ctx.close()

if __name__ == "__main__":
    main()
