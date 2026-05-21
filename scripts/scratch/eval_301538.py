#!/usr/bin/env python3
"""评估 SZ.301538 - 使用系统 StockScorer 参数架构"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from simple_trade.database.core.db_manager import DatabaseManager
from simple_trade.services.strategy.stock_scorer import StockScorer, PASSING_SCORE

STOCK_CODE = 'SZ.301538'

def main():
    db_path = '/data/futu_trade_data/futu_trade.db'
    db = DatabaseManager(db_path)

    # 1. 查询股票基本信息
    try:
        result = db.execute_query('SELECT * FROM stocks WHERE code = ?', (STOCK_CODE,))
        if result:
            print(f"=== 股票信息 ===")
            info = result[0]
            print(json.dumps(info, ensure_ascii=False, default=str, indent=2))
        else:
            print(f"{STOCK_CODE} 不在股票表中")
    except Exception as e:
        print(f"查询股票信息出错: {e}")

    # 2. 获取K线数据
    klines = db.kline_queries.get_stock_kline(STOCK_CODE, days=30)
    if not klines:
        print(f"\n无K线数据，尝试从daily_kline表直接查询...")
        try:
            klines_raw = db.execute_query(
                'SELECT * FROM daily_kline WHERE stock_code = ? ORDER BY trade_date DESC LIMIT 30',
                (STOCK_CODE,)
            )
            if klines_raw:
                klines = list(reversed(klines_raw))
                print(f"从daily_kline表获取到 {len(klines)} 条数据")
        except Exception as e:
            print(f"查询K线出错: {e}")

    if not klines:
        print("无法获取K线数据，退出")
        return

    print(f"\n=== K线数据（最近10天） ===")
    for k in klines[-10:]:
        print(json.dumps(k, ensure_ascii=False, default=str))

    # 3. 计算指标
    closes = [k.get('close', 0) for k in klines if k.get('close', 0) > 0]
    last_close = closes[-1] if closes else 0

    indicators = {}

    # 前日涨幅
    if len(closes) >= 2:
        indicators['prev_day_change'] = (closes[-1] - closes[-2]) / closes[-2] * 100

    # 5日涨幅
    if len(closes) >= 6:
        indicators['change_5d'] = (closes[-1] - closes[-6]) / closes[-6] * 100

    # 日内振幅（使用最后一根K线）
    last_k = klines[-1]
    high = last_k.get('high', 0)
    low = last_k.get('low', 0)
    prev_close_price = closes[-2] if len(closes) >= 2 else last_k.get('close', 0)
    if prev_close_price > 0 and high > 0 and low > 0:
        indicators['day_amplitude'] = (high - low) / prev_close_price * 100

    # 量比（需要计算5日平均成交量 vs 当日）
    if len(klines) >= 6:
        volumes = [k.get('volume', 0) for k in klines if k.get('volume', 0) > 0]
        if len(volumes) >= 6:
            avg_vol_5d = sum(volumes[-6:-1]) / 5
            today_vol = volumes[-1]
            if avg_vol_5d > 0:
                indicators['vol_ratio'] = today_vol / avg_vol_5d

    # K线20日位置
    if len(klines) >= 10:
        recent = klines[-20:] if len(klines) >= 20 else klines
        highs = [k.get('high', 0) for k in recent]
        lows = [k.get('low', 0) for k in recent]
        max_h = max(highs) if highs else 0
        min_l = min(lows) if lows else 0
        if max_h > min_l and last_close > 0:
            indicators['kline_pos_20d'] = (last_close - min_l) / (max_h - min_l)

    # 今日涨跌
    if len(closes) >= 2:
        indicators['today_change'] = (closes[-1] - closes[-2]) / closes[-2] * 100

    # 反包力度
    if high > 0 and low > 0 and high > low:
        indicators['recovery_ratio'] = (last_close - low) / (high - low)

    # ticker_power 盘后无逐笔数据，设为 None
    indicators['ticker_power'] = None

    print(f"\n=== 计算指标 ===")
    for k, v in indicators.items():
        print(f"  {k}: {v:.4f}" if v is not None else f"  {k}: None")

    # 4. 执行评分
    scorer = StockScorer()
    stock_name = ""
    try:
        result = db.execute_query('SELECT * FROM stocks WHERE code = ?', (STOCK_CODE,))
        if result:
            stock_name = result[0].get('name', '')
    except:
        pass

    all_scores = scorer.score_all_strategies(STOCK_CODE, stock_name, indicators)

    # 5. 输出结果
    print(f"\n{'='*60}")
    print(f"  SZ.301538 {stock_name} — 多策略评分报告")
    print(f"{'='*60}")

    # 最佳策略
    best = all_scores['best']
    print(f"\n★ 最佳策略: {best.mode} | 总分: {best.total_score}/100 | {'通过✓' if best.passed else '未通过✗'}")
    if best.veto_reason:
        print(f"  一票否决: {best.veto_reason}")

    # 各策略详情
    for mode_key in ('trend', 'breakout', 'momentum'):
        sr = all_scores[mode_key]
        triggered = True
        if mode_key == 'breakout':
            triggered = all_scores.get('breakout_triggered', False)
        elif mode_key == 'momentum':
            triggered = all_scores.get('momentum_triggered', False)

        status = '已触发' if triggered else '未触发'
        pass_status = '通过✓' if sr.passed else '未通过✗'
        print(f"\n--- {sr.mode} ({status}) ---")
        print(f"  总分: {sr.total_score}/100 | {pass_status}")
        if sr.veto_reason:
            print(f"  否决: {sr.veto_reason}")
        for d in sr.details:
            val_str = f"{d.value}" if d.value is not None else "N/A"
            note_str = f" ({d.note})" if d.note else ""
            print(f"  {d.dimension:12s}: {val_str:>10s} → {d.score:>2d}/{d.max_score}{note_str}")

    # 交易参数推荐
    if best.passed:
        tp = scorer._recommend_trade_params(best.mode, indicators)
        print(f"\n=== 交易参数推荐 ===")
        print(f"  交易类型: {tp.trade_type}")
        print(f"  低吸比例: {tp.buy_dip_pct}%")
        print(f"  止盈点位: {tp.take_profit_pct}%")
        print(f"  止损点位: {tp.stop_loss_pct}%")
        print(f"  最大持仓: {tp.max_hold_days}天")
        print(f"  信心等级: {tp.confidence}")
        print(f"  理由: {tp.reason}")

    print(f"\n及格线: {PASSING_SCORE}分")


if __name__ == '__main__':
    main()
