#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
盘前评分脚本

每日盘前运行（建议9:25），对监控股票池中的所有标的进行评分。
评分结果缓存在 StockScorer 中，供盘中交易门卫使用。

用法：
  python scripts/pre_market_scoring.py
  或由系统协调器在盘前自动调用
"""

import sys
import os
import json
import logging
from datetime import datetime, timedelta

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


def run_scoring():
    """执行盘前评分"""
    import sqlite3

    DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'simple_trade', 'data', 'trade.db')
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 1. 获取监控标的池
    cur.execute("SELECT code, name FROM stocks WHERE is_active = 1")
    stocks = cur.fetchall()
    logger.info(f"监控标的池: {len(stocks)} 只")

    if not stocks:
        logger.warning("无活跃监控标的，退出")
        return []

    # 2. 对每只标的计算指标
    from simple_trade.services.strategy.stock_scorer import StockScorer
    scorer = StockScorer()
    scorer.reset_daily()

    today = datetime.now().strftime('%Y-%m-%d')
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    five_days_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

    results = []
    for code, name in stocks:
        try:
            indicators = _calc_indicators(cur, code, today, yesterday, five_days_ago)
            result = scorer.score_stock(code, name, indicators)
            results.append(result)

            status = "✅ PASS" if result.passed else f"❌ FAIL({result.veto_reason or '低分'})"
            logger.info(f"  {code} {name}: {result.total_score}分 {status}")
        except Exception as e:
            logger.warning(f"  {code} {name}: 评分失败 - {e}")

    # 3. 输出候选列表
    candidates = scorer.get_candidates()
    logger.info(f"\n{'='*60}")
    logger.info(f"及格候选（≥60分）: {len(candidates)} 只")
    for c in candidates:
        logger.info(f"  {c.total_score:3d}分 | {c.stock_code} {c.stock_name}")
    logger.info(f"{'='*60}")

    # 4. 保存评分结果到JSON（供API和前端使用）
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'pre_market_scores.json')
    output = {
        'date': today,
        'timestamp': datetime.now().isoformat(),
        'total_stocks': len(stocks),
        'candidates': len(candidates),
        'scores': [r.to_dict() for r in results],
    }
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    logger.info(f"评分结果已保存: {output_path}")

    return scorer, results


def _calc_indicators(cur, code: str, today: str, yesterday: str, five_days_ago: str) -> dict:
    """计算单只标的的评分指标"""
    indicators = {}

    # 5日累计涨幅：(今日收盘 - 5日前收盘) / 5日前收盘
    cur.execute("""
        SELECT close_price FROM kline_data
        WHERE stock_code = ? AND date(time_key) <= ? 
        ORDER BY time_key DESC LIMIT 1
    """, (code, today))
    latest = cur.fetchone()

    cur.execute("""
        SELECT close_price FROM kline_data
        WHERE stock_code = ? AND date(time_key) <= ?
        ORDER BY time_key DESC LIMIT 1
    """, (code, five_days_ago))
    five_day = cur.fetchone()

    if latest and five_day and five_day[0] > 0:
        indicators['change_5d'] = (latest[0] - five_day[0]) / five_day[0] * 100
    else:
        indicators['change_5d'] = None

    # K线20日位置
    cur.execute("""
        SELECT high_price, low_price FROM kline_data
        WHERE stock_code = ? ORDER BY time_key DESC LIMIT 20
    """, (code,))
    klines_20 = cur.fetchall()
    if klines_20 and latest:
        high_20 = max(k[0] for k in klines_20)
        low_20 = min(k[1] for k in klines_20)
        if high_20 > low_20:
            indicators['kline_pos_20d'] = (latest[0] - low_20) / (high_20 - low_20)
        else:
            indicators['kline_pos_20d'] = 0.5
    else:
        indicators['kline_pos_20d'] = None

    # 前日涨幅 + 日振幅
    cur.execute("""
        SELECT open_price, close_price, high_price, low_price, volume
        FROM kline_data WHERE stock_code = ? ORDER BY time_key DESC LIMIT 2
    """, (code,))
    recent_2 = cur.fetchall()
    if len(recent_2) >= 2:
        today_o, today_c, today_h, today_l, today_v = recent_2[0]
        yest_o, yest_c, yest_h, yest_l, yest_v = recent_2[1]
        if yest_c > 0:
            indicators['prev_day_change'] = (today_c - yest_c) / yest_c * 100
        else:
            indicators['prev_day_change'] = 0
        if today_l > 0:
            indicators['day_amplitude'] = (today_h - today_l) / today_l * 100
        else:
            indicators['day_amplitude'] = 0
    elif len(recent_2) == 1:
        today_o, today_c, today_h, today_l, today_v = recent_2[0]
        indicators['prev_day_change'] = 0
        if today_l > 0:
            indicators['day_amplitude'] = (today_h - today_l) / today_l * 100
        else:
            indicators['day_amplitude'] = 0
    else:
        indicators['prev_day_change'] = None
        indicators['day_amplitude'] = None

    # 量比（vs 5日均量）
    cur.execute("""
        SELECT volume FROM kline_data
        WHERE stock_code = ? ORDER BY time_key DESC LIMIT 6
    """, (code,))
    vol_data = cur.fetchall()
    if len(vol_data) >= 2:
        today_vol = vol_data[0][0]
        avg_5d_vol = sum(v[0] for v in vol_data[1:]) / len(vol_data[1:])
        if avg_5d_vol > 0:
            indicators['vol_ratio'] = today_vol / avg_5d_vol
        else:
            indicators['vol_ratio'] = 1.0
    else:
        indicators['vol_ratio'] = None

    # 资金流净比率（从capital_flow_data表获取，如有）
    cur.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='capital_flow_data'
    """)
    if cur.fetchone():
        cur.execute("""
            SELECT net_inflow, total_amount FROM capital_flow_data
            WHERE stock_code = ? ORDER BY created_at DESC LIMIT 1
        """, (code,))
        flow = cur.fetchone()
        if flow and flow[1] and flow[1] > 0:
            indicators['flow_ratio'] = flow[0] / flow[1]
        else:
            indicators['flow_ratio'] = 0
    else:
        indicators['flow_ratio'] = 0

    return indicators


if __name__ == '__main__':
    scorer, results = run_scoring()
    
    # 打印详细评分
    passed = [r for r in results if r.passed]
    failed = [r for r in results if not r.passed]
    
    print(f"\n总计: {len(results)}只 | 通过: {len(passed)}只 | 未通过: {len(failed)}只")
