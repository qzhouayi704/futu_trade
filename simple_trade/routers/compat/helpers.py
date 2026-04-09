#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
兼容路由的辅助函数
"""

import logging
from datetime import datetime, timedelta

from ...core import get_state_manager

# 从共享模块导入 K线相关辅助函数（避免重复）
from ..market.kline_helpers import (
    get_stock_info as _get_stock_info,
    get_kline_from_db as _get_kline_from_db,
    fetch_kline_from_api as _fetch_kline_from_api,
    get_trade_points as _get_trade_points,
)


def _add_manual_stocks(stock_codes, plate_id, is_manual, stock_priority, db_manager, futu_client):
    """添加自选股辅助函数"""
    result = {'success': False, 'message': '', 'added_count': 0, 'failed_codes': [], 'manual_count': 0}

    try:
        if not stock_codes:
            result['message'] = '股票代码列表为空'
            return result

        target_plate_id = plate_id

        # 如果没有指定板块，使用或创建"自选股"板块
        if target_plate_id is None:
            manual_plates = db_manager.execute_query(
                "SELECT id FROM plates WHERE plate_code = 'MANUAL' OR plate_name = '自选股' LIMIT 1"
            )

            if manual_plates:
                target_plate_id = manual_plates[0][0]
            else:
                db_manager.execute_update('''
                    INSERT INTO plates (plate_code, plate_name, market, is_target, priority)
                    VALUES (?, ?, ?, ?, ?)
                ''', ('MANUAL', '自选股', 'Mixed', 1, 100))

                manual_plates = db_manager.execute_query(
                    "SELECT id FROM plates WHERE plate_code = 'MANUAL' LIMIT 1"
                )
                if manual_plates:
                    target_plate_id = manual_plates[0][0]

        added_count = 0
        failed_codes = []
        manual_count = 0

        for stock_code in stock_codes:
            try:
                stock_code = stock_code.strip()
                if not stock_code:
                    continue

                # 检查股票是否已存在
                existing = db_manager.execute_query(
                    "SELECT id, is_manual FROM stocks WHERE code = ?", (stock_code,)
                )

                if existing:
                    stock_id = existing[0][0]
                    db_manager.execute_update(
                        "UPDATE stocks SET is_manual = ?, stock_priority = ? WHERE id = ?",
                        (is_manual, stock_priority, stock_id)
                    )
                else:
                    # 从富途API获取股票信息
                    if not futu_client or not futu_client.is_available():
                        failed_codes.append(stock_code)
                        continue

                    ret, data = futu_client.get_stock_basicinfo(market=None, stock_code=stock_code)
                    if ret != 0 or data is None or data.empty:
                        failed_codes.append(stock_code)
                        continue

                    stock_info = data.iloc[0]
                    stock_name = stock_info.get('name', stock_code)
                    market = stock_code.split('.')[0] if '.' in stock_code else 'HK'

                    db_manager.execute_update('''
                        INSERT INTO stocks (code, name, market, is_manual, stock_priority)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (stock_code, stock_name, market, is_manual, stock_priority))

                    stock_id_result = db_manager.execute_query(
                        "SELECT id FROM stocks WHERE code = ?", (stock_code,)
                    )
                    if stock_id_result:
                        stock_id = stock_id_result[0][0]
                    else:
                        failed_codes.append(stock_code)
                        continue

                # 关联板块
                if target_plate_id:
                    existing_relation = db_manager.execute_query(
                        "SELECT 1 FROM stock_plates WHERE stock_id = ? AND plate_id = ?",
                        (stock_id, target_plate_id)
                    )
                    if not existing_relation:
                        db_manager.execute_update(
                            "INSERT INTO stock_plates (stock_id, plate_id) VALUES (?, ?)",
                            (stock_id, target_plate_id)
                        )

                added_count += 1
                if is_manual:
                    manual_count += 1

            except Exception as e:
                logging.error(f"添加股票失败 {stock_code}: {e}")
                failed_codes.append(stock_code)

        result['success'] = True
        result['added_count'] = added_count
        result['failed_codes'] = failed_codes
        result['manual_count'] = manual_count
        result['message'] = f"成功添加 {added_count} 只股票"
        if failed_codes:
            result['message'] += f"，失败 {len(failed_codes)} 只"

    except Exception as e:
        logging.error(f"添加自选股失败: {e}")
        result['message'] = str(e)

    return result

