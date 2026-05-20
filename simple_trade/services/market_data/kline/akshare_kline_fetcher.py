#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AkShare K线数据获取器

免费数据源，用于盘后批量下载港股日K线，解决富途API配额瓶颈。
数据来源：东方财富网（通过 AkShare 库）

使用场景：
- 盘后 16:30 自动更新时，优先使用 AkShare 下载日K线
- 富途 API 仅用于 AkShare 失败时的 fallback
- 释放富途 API 配额给实时报价和交易

依赖：pip install akshare
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# AkShare 是否可用的标志
_akshare_available = False
try:
    import akshare as ak
    _akshare_available = True
except ImportError:
    logger.info("akshare 未安装，AkShare K线获取器不可用。安装方法: pip install akshare")


def is_available() -> bool:
    """检查 AkShare 是否可用"""
    return _akshare_available


def _futu_code_to_akshare(futu_code: str) -> Optional[str]:
    """将富途格式的股票代码转换为 AkShare 格式

    富途格式: HK.00700, US.AAPL, SH.600000, SZ.000001
    AkShare 港股格式: 00700
    AkShare A股格式: 600000 / 000001
    AkShare 美股格式: AAPL (stock_us_hist)

    Args:
        futu_code: 富途格式的股票代码

    Returns:
        AkShare 格式的代码，如果市场不支持则返回 None
    """
    if '.' not in futu_code:
        return None
    market, code = futu_code.split('.', 1)
    if market in ('HK', 'SH', 'SZ', 'US'):
        return code
    return None


def _get_market(futu_code: str) -> str:
    """从富途代码中提取市场"""
    return futu_code.split('.', 1)[0] if '.' in futu_code else ''


def fetch_daily_kline(
    futu_code: str,
    days: int = 30,
    adjust: str = "qfq"
) -> List[Dict[str, Any]]:
    """从 AkShare 获取日K线数据

    Args:
        futu_code: 富途格式的股票代码 (如 HK.00700)
        days: 获取最近 N 天的数据
        adjust: 复权方式 ("" 不复权, "qfq" 前复权, "hfq" 后复权)

    Returns:
        K线数据列表，格式兼容 kline_storage.save_kline_batch()
        每条记录包含:
            stock_code, time_key, open_price, close_price,
            high_price, low_price, volume, turnover,
            pe_ratio, turnover_rate
    """
    if not _akshare_available:
        return []

    ak_code = _futu_code_to_akshare(futu_code)
    market = _get_market(futu_code)
    if not ak_code or not market:
        return []

    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days + 10)).strftime("%Y%m%d")  # 多取几天容错

    try:
        if market == 'HK':
            df = ak.stock_hk_hist(
                symbol=ak_code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust=adjust
            )
        elif market in ('SH', 'SZ'):
            df = ak.stock_zh_a_hist(
                symbol=ak_code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust=adjust
            )
        elif market == 'US':
            df = ak.stock_us_hist(
                symbol=ak_code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust=adjust
            )
        else:
            return []

        if df is None or df.empty:
            return []

        # 转换为系统标准格式
        result = []
        for _, row in df.iterrows():
            # AkShare 港股/A股返回的列名（中文）
            kline = {
                'time_key': str(row.get('日期', '')),
                'open_price': float(row.get('开盘', 0)),
                'close_price': float(row.get('收盘', 0)),
                'high_price': float(row.get('最高', 0)),
                'low_price': float(row.get('最低', 0)),
                'volume': int(row.get('成交量', 0)),
                'turnover': float(row.get('成交额', 0)),
                'pe_ratio': 0.0,  # AkShare 不提供 PE
                'turnover_rate': float(row.get('换手率', 0)),
            }

            # 跳过无效数据
            if kline['close_price'] <= 0:
                continue

            # 标准化日期格式为 YYYY-MM-DD
            try:
                if isinstance(kline['time_key'], str) and len(kline['time_key']) >= 10:
                    kline['time_key'] = kline['time_key'][:10]
                else:
                    dt = datetime.strptime(str(kline['time_key']), "%Y%m%d")
                    kline['time_key'] = dt.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                continue

            result.append(kline)

        # 只保留最近 days 条
        result = result[-days:] if len(result) > days else result

        logger.debug(f"[AkShare] {futu_code} 获取 {len(result)} 条日K线")
        return result

    except Exception as e:
        logger.debug(f"[AkShare] {futu_code} 获取失败: {e}")
        return []


def batch_fetch_daily_kline(
    futu_codes: List[str],
    days: int = 30,
    delay: float = 0.3,
    adjust: str = "qfq"
) -> Dict[str, List[Dict[str, Any]]]:
    """批量获取多只股票的日K线

    Args:
        futu_codes: 富途格式的股票代码列表
        days: 获取最近 N 天数据
        delay: 每次请求间隔（秒），避免被封
        adjust: 复权方式

    Returns:
        {stock_code: [kline_data_list]}
    """
    results = {}
    for code in futu_codes:
        klines = fetch_daily_kline(code, days=days, adjust=adjust)
        if klines:
            results[code] = klines
        time.sleep(delay)
    return results
