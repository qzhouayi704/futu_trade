"""刷新所有目标板块的股票成员数据（从富途API获取最新成员列表）"""
import sqlite3
import sys
import os
import time

# 添加项目路径
sys.path.insert(0, r'd:\Program Files\futu_trade_sys')

db_path = r'd:\Program Files\futu_trade_sys\simple_trade\data\trade.db'

try:
    from futu import OpenQuoteContext, RET_OK
    
    # 连接富途OpenD
    quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # 获取所有目标板块
    plates = conn.execute(
        "SELECT id, plate_code, plate_name, market FROM plates WHERE is_target=1 AND is_enabled=1"
    ).fetchall()
    
    print(f"共 {len(plates)} 个目标板块需要刷新\n")
    
    total_new = 0
    for i, plate in enumerate(plates):
        plate_id = plate['id']
        plate_code = plate['plate_code']
        plate_name = plate['plate_name']
        market = plate['market']
        
        # 跳过特殊板块
        if plate_code == 'POSITION_MONITOR':
            continue
        
        # 从API获取板块成员
        ret, data = quote_ctx.get_plate_stock(plate_code)
        if ret != RET_OK or data is None or data.empty:
            print(f"  [{i+1}/{len(plates)}] {plate_name} ({plate_code}): API失败 - {data}")
            time.sleep(1)
            continue
        
        new_count = 0
        for _, row in data.iterrows():
            stock_code = row.get('code', '')
            stock_name = row.get('stock_name', '')
            stock_market = 'HK' if stock_code.startswith('HK.') else 'US'
            
            if not stock_code:
                continue
            
            # 插入股票（如果不存在）
            conn.execute(
                "INSERT OR IGNORE INTO stocks (code, name, market) VALUES (?, ?, ?)",
                (stock_code, stock_name, stock_market)
            )
            
            # 获取stock_id
            result = conn.execute("SELECT id FROM stocks WHERE code=?", (stock_code,)).fetchone()
            if result:
                stock_id = result['id']
                # 插入关联（如果不存在）
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO stock_plates (stock_id, plate_id) VALUES (?, ?)",
                    (stock_id, plate_id)
                )
                if cursor.rowcount > 0:
                    new_count += 1
        
        # 更新板块股票数量
        actual_count = conn.execute(
            "SELECT COUNT(DISTINCT stock_id) FROM stock_plates WHERE plate_id=?", (plate_id,)
        ).fetchone()[0]
        conn.execute("UPDATE plates SET stock_count=? WHERE id=?", (actual_count, plate_id))
        conn.commit()
        
        if new_count > 0:
            print(f"  [{i+1}/{len(plates)}] {plate_name}: 新增 {new_count} 只, 总计 {actual_count} 只")
            total_new += new_count
        
        # 限流 - 板块接口 10次/30秒
        time.sleep(3.5)
    
    # 检查群核是否已入板块
    print(f"\n=== 刷新完成: 新增 {total_new} 只股票关联 ===")
    qunhe = conn.execute(
        "SELECT s.code, s.name, p.plate_name FROM stocks s "
        "JOIN stock_plates sp ON s.id=sp.stock_id "
        "JOIN plates p ON sp.plate_id=p.id "
        "WHERE s.code='HK.00068'"
    ).fetchall()
    if qunhe:
        print(f"\n群核科技板块关联:")
        for r in qunhe:
            print(f"  {r[0]} {r[1]} -> {r[2]}")
    else:
        print("\n群核科技仍无板块关联（可能不在当前目标板块中）")
    
    conn.close()
    quote_ctx.close()
    
except ImportError:
    print("错误: 需要安装 futu-api 并启动 OpenD")
except Exception as e:
    print(f"错误: {e}")
    import traceback
    traceback.print_exc()
