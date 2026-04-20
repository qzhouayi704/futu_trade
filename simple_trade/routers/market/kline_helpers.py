#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K线路由共享辅助函数

供 routers/kline.py 使用，
避免代码重复。
"""

import logging
from datetime import datetime, timedelta
from typing import List

from ...core import get_state_manager
from ...utils.converters import get_last_price


def get_stock_info(stock_code: str, container) -> dict:
    """获取股票基本信息"""
    info = {
        'code': stock_code,
        'name': stock_code,
        'cur_price': 0,
        'price_change': 0,
        'change_rate': 0
    }

    try:
        result = container.db_manager.execute_query(
            "SELECT name, market FROM stocks WHERE code = ?", (stock_code,)
        )
        if result:
            info['name'] = result[0][0] or stock_code
            info['market'] = result[0][1] or 'HK'

        state = get_state_manager()
        cached_quotes = state.get_cached_quotes() or []
        for quote in cached_quotes:
            if isinstance(quote, dict) and quote.get('code') == stock_code:
                info['cur_price'] = get_last_price(quote)
                info['price_change'] = quote.get('price_change', 0)
                info['change_rate'] = quote.get('change_percent') or quote.get('change_rate', 0)
                break

        if not info['cur_price']:
            kline_result = container.db_manager.execute_query('''
                SELECT close_price FROM kline_data
                WHERE stock_code = ? ORDER BY time_key DESC LIMIT 1
            ''', (stock_code,))
            if kline_result:
                info['cur_price'] = kline_result[0][0]

    except Exception as e:
        logging.error(f"获取股票信息失败 {stock_code}: {e}")

    return info


def get_kline_from_db(stock_code: str, days: int, db_manager) -> list:
    """从数据库获取K线数据"""
    kline_data = []

    try:
        result = db_manager.execute_query('''
            SELECT time_key, open_price, close_price, high_price, low_price, volume
            FROM kline_data
            WHERE stock_code = ?
            ORDER BY time_key DESC
            LIMIT ?
        ''', (stock_code, days))

        for row in result:
            date_str = str(row[0]).split()[0] if row[0] else ''
            kline_data.append({
                'date': date_str,
                'open': float(row[1]) if row[1] else 0,
                'close': float(row[2]) if row[2] else 0,
                'high': float(row[3]) if row[3] else 0,
                'low': float(row[4]) if row[4] else 0,
                'volume': int(row[5]) if row[5] else 0
            })

        kline_data.sort(key=lambda x: x['date'])

    except Exception as e:
        logging.error(f"从数据库获取K线失败 {stock_code}: {e}")

    return kline_data


def fetch_kline_from_api(stock_code: str, days: int, container) -> list:
    """通过 KlineFetcher 获取K线数据（带频率控制和重试）"""
    kline_data = []

    try:
        kline_service = getattr(container, 'kline_service', None)
        if not kline_service:
            logging.warning("KlineService 不可用，无法获取K线数据")
            return kline_data

        # 通过 fetcher 获取（内置频率控制 + 重试）
        records = kline_service.fetcher.fetch_kline(stock_code, days, limit_days=days)

        for r in records:
            date_str = str(r.time_key).split()[0] if r.time_key else ''
            kline_data.append({
                'date': date_str,
                'open': r.open_price,
                'close': r.close_price,
                'high': r.high_price,
                'low': r.low_price,
                'volume': r.volume
            })

        if kline_data:
            logging.info(f"从API获取到 {len(kline_data)} 条K线数据: {stock_code}")

    except Exception as e:
        logging.error(f"从API获取K线异常 {stock_code}: {e}")

    return kline_data


def get_trade_points(stock_code: str, days: int, db_manager) -> list:
    """获取交易记录（买卖点标记）"""
    trade_points = []

    try:
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        result = db_manager.execute_query('''
            SELECT trade_type, trade_price, trade_time
            FROM trading_records
            WHERE stock_code = ? AND trade_time >= ?
            ORDER BY trade_time DESC
        ''', (stock_code, start_date))

        for row in result:
            trade_type = row[0]
            price = float(row[1]) if row[1] else 0
            trade_time = row[2]

            if trade_time:
                if isinstance(trade_time, str):
                    date_str = trade_time.split()[0]
                else:
                    date_str = trade_time.strftime('%Y-%m-%d')
            else:
                continue

            trade_points.append({
                'type': 'buy' if trade_type == 'BUY' else 'sell',
                'price': price,
                'date': date_str
            })

    except Exception as e:
        if 'no such table' in str(e).lower():
            logging.debug(f"交易记录表不存在，跳过: {stock_code}")
        else:
            logging.error(f"获取交易记录失败 {stock_code}: {e}")

    return trade_points
