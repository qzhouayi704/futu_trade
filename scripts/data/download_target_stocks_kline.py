#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
下载价格位置统计策略目标股票的日线K线数据

用法：
    python scripts/download_target_stocks_kline.py

功能：
    1. 连接富途API
    2. 检查K线额度
    3. 逐只下载目标股票的日线数据（默认1年）
    4. 去重保存到数据库（INSERT OR REPLACE）
    5. 显示下载结果统计
"""

import os
import sys
import time
import logging
from datetime import datetime, timedelta

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from simple_trade.config.config import Config
from simple_trade.database.core.db_manager import DatabaseManager
from simple_trade.api.futu_client import FutuClient
from simple_trade.services.analysis.kline_fetcher import KlineFetcher
from simple_trade.services.analysis.kline_storage import KlineStorage
from simple_trade.utils.rate_limiter import get_global_rate_limiter

# 配置日志
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/target_stocks_download.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# 目标股票列表（价格位置统计策略）
TARGET_STOCKS = [
    ('HK.00700', '腾讯控股'),
    ('HK.03690', '美团'),
    ('HK.01810', '小米集团'),
    ('HK.01024', '快手'),
    ('HK.09988', '阿里巴巴'),
    ('HK.01347', '华虹半导体'),
    ('HK.09888', '百度集团'),
    ('HK.09618', '京东集团'),
    ('HK.09999', '网易'),
    ('HK.09626', '哔哩哔哩'),
    ('HK.02015', '理想汽车'),
    ('HK.09868', '小鹏汽车'),
]

# 大盘情绪参考ETF（用于回测情绪调整，需同步下载K线数据）
SENTIMENT_STOCKS = [
    ('HK.03032', '恒生科技ETF'),
]


def check_existing_data(db_manager, stock_code):
    """检查数据库中已有的K线数据"""
    try:
        result = db_manager.execute_query(
            'SELECT COUNT(*), MIN(time_key), MAX(time_key) FROM kline_data WHERE stock_code = ?',
            (stock_code,)
        )
        if result and result[0][0] > 0:
            return {
                'count': result[0][0],
                'min_date': result[0][1][:10] if result[0][1] else '',
                'max_date': result[0][2][:10] if result[0][2] else '',
            }
    except Exception as e:
        logger.warning(f"检查已有数据失败 {stock_code}: {e}")
    return {'count': 0, 'min_date': '', 'max_date': ''}


def ensure_stock_in_db(db_manager, stock_code, stock_name):
    """确保股票存在于 stocks 表中"""
    try:
        existing = db_manager.execute_query(
            'SELECT id FROM stocks WHERE code = ?', (stock_code,)
        )
        if not existing:
            db_manager.execute_update(
                'INSERT OR IGNORE INTO stocks (code, name, market) VALUES (?, ?, ?)',
                (stock_code, stock_name, 'HK')
            )
            logger.info(f"  新增股票到数据库: {stock_code} {stock_name}")
    except Exception as e:
        logger.warning(f"  确保股票记录失败 {stock_code}: {e}")


def fetch_kline_with_debug(futu_client, config, stock_code, days):
    """
    带详细调试信息的K线下载

    直接调用富途API并打印完整的返回值，方便排查下载失败的原因。

    Returns:
        (kline_data_list, debug_info_dict)
    """
    from simple_trade.api.market_types import ReturnCode
    from datetime import timedelta

    debug_info = {
        'stock_code': stock_code,
        'api_available': futu_client.is_available(),
        'ret_code': None,
        'ret_data_type': None,
        'ret_data_preview': None,
        'data_empty': None,
        'data_shape': None,
        'data_columns': None,
        'page_req_key': None,
        'error': None,
    }

    if not futu_client.is_available():
        debug_info['error'] = '富途API不可用'
        return [], debug_info

    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days + 30)).strftime('%Y-%m-%d')
    debug_info['start_date'] = start_date
    debug_info['end_date'] = end_date

    try:
        ret, data, page_req_key = futu_client.request_history_kline(
            code=stock_code,
            start=start_date,
            end=end_date,
            max_count=1000
        )

        debug_info['ret_code'] = ret
        debug_info['ret_data_type'] = type(data).__name__
        debug_info['page_req_key'] = page_req_key

        if data is not None:
            debug_info['data_empty'] = data.empty if hasattr(data, 'empty') else (len(data) == 0 if hasattr(data, '__len__') else 'N/A')
            if hasattr(data, 'shape'):
                debug_info['data_shape'] = str(data.shape)
            if hasattr(data, 'columns'):
                debug_info['data_columns'] = list(data.columns)
            # 预览前几行或字符串内容
            data_str = str(data)
            debug_info['ret_data_preview'] = data_str[:500] if len(data_str) > 500 else data_str
        else:
            debug_info['ret_data_preview'] = 'None'

        if ReturnCode.is_ok(ret) and data is not None and hasattr(data, 'empty') and not data.empty:
            kline_data = []
            for _, row in data.iterrows():
                kline_data.append({
                    'time_key': row['time_key'],
                    'open_price': float(row['open']),
                    'close_price': float(row['close']),
                    'high_price': float(row['high']),
                    'low_price': float(row['low']),
                    'volume': int(row['volume']),
                    'turnover': float(row.get('turnover', 0)),
                    'pe_ratio': float(row.get('pe_ratio', 0)) if row.get('pe_ratio') else None,
                    'turnover_rate': float(row.get('turnover_rate', 0)) if row.get('turnover_rate') else None
                })
            return kline_data, debug_info
        else:
            return [], debug_info

    except Exception as e:
        debug_info['error'] = f'{type(e).__name__}: {e}'
        return [], debug_info


def main():
    logger.info("=" * 70)
    logger.info("目标股票日线K线数据下载")
    logger.info("=" * 70)

    # 1. 初始化
    config = Config()
    db_manager = DatabaseManager(config.database_path)
    kline_storage = KlineStorage(db_manager)

    # 下载参数 - 从配置读取
    days_back = 400  # 约1年多，确保有足够数据
    request_delay = config.kline_rate_limit.get("request_delay", 1.0)

    # 初始化全局频率控制器
    rate_limiter = get_global_rate_limiter(
        max_requests=config.kline_rate_limit.get("max_requests", 60),
        time_window=config.kline_rate_limit.get("time_window", 30)
    )

    # 2. 连接富途API
    logger.info(f"连接富途API: {config.futu_host}:{config.futu_port}")
    futu_client = FutuClient(host=config.futu_host, port=config.futu_port)

    if not futu_client.connect():
        logger.error("❌ 富途API连接失败！请检查：")
        logger.error("   1. 富途客户端是否已启动并登录")
        logger.error("   2. OpenD 是否正在运行")
        return

    logger.info("✅ 富途API连接成功")

    # 3. 检查K线额度
    kline_fetcher = KlineFetcher(futu_client, config)
    quota = kline_fetcher.get_quota_info()
    logger.info(f"K线额度: 已用 {quota.get('used', '?')}, 剩余 {quota.get('remaining', '?')}")

    remaining = quota.get('remaining', 0)

    # 合并下载列表：目标股票 + 情绪参考ETF
    all_stocks = TARGET_STOCKS + SENTIMENT_STOCKS

    if remaining is not None and remaining < len(all_stocks):
        logger.warning(f"⚠️ 剩余额度({remaining})可能不足以下载所有{len(all_stocks)}只股票/ETF")

    # 4. 检查已有数据
    logger.info("")
    logger.info("检查数据库已有数据：")
    logger.info("-" * 70)
    for code, name in all_stocks:
        info = check_existing_data(db_manager, code)
        if info['count'] > 0:
            logger.info(f"  {code} {name}: {info['count']}条 ({info['min_date']} ~ {info['max_date']})")
        else:
            logger.info(f"  {code} {name}: 无数据")
    logger.info("-" * 70)

    # 5. 开始下载
    logger.info("")
    logger.info(f"开始下载 {len(all_stocks)} 只股票/ETF的日线数据（约{days_back}天）...")
    logger.info(f"  其中目标股票 {len(TARGET_STOCKS)} 只，情绪参考ETF {len(SENTIMENT_STOCKS)} 只")
    logger.info("")

    success_count = 0
    failed_count = 0
    total_saved = 0
    results = []

    for i, (stock_code, stock_name) in enumerate(all_stocks, 1):
        logger.info(f"[{i}/{len(all_stocks)}] {stock_code} ({stock_name})")

        # 确保股票在数据库中
        ensure_stock_in_db(db_manager, stock_code, stock_name)

        try:
            # 下载K线数据（带详细调试信息）
            kline_data, debug_info = fetch_kline_with_debug(
                futu_client, config, stock_code, days_back
            )

            if kline_data:
                # 去重保存（KlineStorage 使用 INSERT OR REPLACE）
                saved = kline_storage.save_kline_batch(stock_code, kline_data)
                total_saved += saved
                success_count += 1

                # 下载后再查一次确认
                after = check_existing_data(db_manager, stock_code)
                logger.info(f"  ✅ 下载 {len(kline_data)} 条，保存 {saved} 条 → 数据库共 {after['count']} 条 ({after['min_date']} ~ {after['max_date']})")
                results.append((stock_code, stock_name, 'OK', len(kline_data), after['count']))
            else:
                failed_count += 1
                logger.warning(f"  ❌ 未获取到数据")
                logger.warning(f"  调试信息:")
                logger.warning(f"    ret_code={debug_info.get('ret_code')}")
                logger.warning(f"    data_type={debug_info.get('ret_data_type')}")
                logger.warning(f"    data_empty={debug_info.get('data_empty')}")
                logger.warning(f"    data_shape={debug_info.get('data_shape')}")
                logger.warning(f"    date_range={debug_info.get('start_date')} ~ {debug_info.get('end_date')}")
                logger.warning(f"    error={debug_info.get('error')}")
                logger.warning(f"    data_preview={debug_info.get('ret_data_preview')}")
                results.append((stock_code, stock_name, 'FAIL', 0, 0))

        except Exception as e:
            failed_count += 1
            logger.error(f"  ❌ 下载异常: {e}")
            results.append((stock_code, stock_name, 'ERROR', 0, 0))

        # 请求间隔 - 使用频率控制器
        if i < len(all_stocks):
            rate_limiter.wait_if_needed()
            time.sleep(request_delay)

    # 6. 断开连接
    futu_client.disconnect()

    # 7. 打印汇总
    logger.info("")
    logger.info("=" * 70)
    logger.info("下载完成！汇总：")
    logger.info("=" * 70)
    logger.info(f"  成功: {success_count} 只")
    logger.info(f"  失败: {failed_count} 只")
    logger.info(f"  总保存: {total_saved} 条")
    logger.info("")
    logger.info(f"{'股票代码':<12} {'名称':<10} {'状态':<6} {'下载':<6} {'数据库总计'}")
    logger.info("-" * 55)
    for code, name, status, downloaded, total in results:
        logger.info(f"  {code:<12} {name:<10} {status:<6} {downloaded:<6} {total}")
    logger.info("=" * 70)


if __name__ == '__main__':
    main()
