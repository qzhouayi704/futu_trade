#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析买入信号后的收益率 - 按盘中均价(VWAP=turnover/volume)计算"""
import sqlite3
import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'simple_trade', 'data', 'trade.db')

def get_deduped_buy_signals(conn):
    """获取去重后的买入信号（同一股票同一天只取一条）"""
    c = conn.cursor()
    c.execute("""
        SELECT ts.id, s.code, s.name, ts.signal_price, ts.created_at,
               ts.strategy_id, ts.strategy_name
        FROM trade_signals ts
        JOIN stocks s ON ts.stock_id = s.id
        WHERE ts.signal_type = 'BUY'
        ORDER BY ts.created_at DESC
    """)
    rows = c.fetchall()

    # 按 (stock_code, date) 去重，只保留每天最早的一条
    seen = set()
    deduped = []
    for r in rows:
        key = (r[1], r[4][:10])  # (code, date)
        if key not in seen:
            seen.add(key)
            deduped.append({
                'id': r[0], 'code': r[1], 'name': r[2],
                'signal_price': r[3], 'signal_time': r[4],
                'signal_date': r[4][:10],
                'strategy': r[6] or r[5] or '-'
            })
    return deduped


def get_kline_after_date(conn, stock_code, signal_date, days_needed=15):
    """获取信号日期之后的K线数据"""
    c = conn.cursor()
    c.execute("""
        SELECT time_key, open_price, close_price, high_price, low_price,
               volume, turnover
        FROM kline_data
        WHERE stock_code = ? AND DATE(time_key) > DATE(?)
        ORDER BY time_key ASC
        LIMIT ?
    """, (stock_code, signal_date, days_needed))
    return c.fetchall()


def get_kline_on_date(conn, stock_code, signal_date):
    """获取信号当天的K线（用于计算信号日VWAP）"""
    c = conn.cursor()
    c.execute("""
        SELECT time_key, open_price, close_price, high_price, low_price,
               volume, turnover
        FROM kline_data
        WHERE stock_code = ? AND DATE(time_key) = DATE(?)
        LIMIT 1
    """, (stock_code, signal_date))
    return c.fetchone()


def calc_vwap(kline_row):
    """计算VWAP = turnover / volume"""
    if not kline_row:
        return None
    volume = kline_row[5]
    turnover = kline_row[6]
    if volume and volume > 0 and turnover and turnover > 0:
        return turnover / volume
    # fallback: 用 (open+close+high+low)/4
    prices = [p for p in [kline_row[1], kline_row[2], kline_row[3], kline_row[4]] if p]
    return sum(prices) / len(prices) if prices else None


def find_missing_kline_stocks(conn, signals):
    """找出需要补充K线数据的股票"""
    missing = []
    today = datetime.now().date()
    for sig in signals:
        sig_date = datetime.strptime(sig['signal_date'], '%Y-%m-%d').date()
        # 需要信号日之后至少10个交易日的数据
        need_until = sig_date + timedelta(days=16)  # 加上周末
        if need_until > today:
            continue  # 还没到时间，不算缺失

        klines = get_kline_after_date(conn, sig['code'], sig['signal_date'], 12)
        if len(klines) < 10:
            missing.append(sig['code'])
    return list(set(missing))


def download_missing_kline(conn, stock_codes):
    """通过Futu API下载缺失的K线数据"""
    if not stock_codes:
        return

    print(f"\n需要补充 {len(stock_codes)} 只股票的K线数据...")

    try:
        from futu import OpenQuoteContext, KLType, KL_FIELD, RET_OK
    except ImportError:
        print("  [WARN] futu SDK未安装，跳过数据补充")
        return

    try:
        ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
    except Exception as e:
        print(f"  [WARN] 无法连接FutuOpenD: {e}，跳过数据补充")
        return

    import time
    c = conn.cursor()
    for i, code in enumerate(stock_codes):
        print(f"  [{i+1}/{len(stock_codes)}] 下载 {code} ...")
        try:
            ret, data, _ = ctx.request_history_kline(
                code, start='2025-12-01',
                ktype=KLType.K_DAY,
                fields=[KL_FIELD.ALL]
            )
            if ret != RET_OK:
                print(f"    失败: {data}")
                continue

            count = 0
            for _, row in data.iterrows():
                try:
                    c.execute("""
                        INSERT OR REPLACE INTO kline_data
                        (stock_code, time_key, open_price, close_price, high_price,
                         low_price, volume, turnover, pe_ratio, turnover_rate)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        code, row['time_key'],
                        row.get('open', 0), row.get('close', 0),
                        row.get('high', 0), row.get('low', 0),
                        row.get('volume', 0), row.get('turnover', 0),
                        row.get('pe_ratio', 0), row.get('turnover_rate', 0)
                    ))
                    count += 1
                except Exception:
                    pass
            conn.commit()
            print(f"    写入 {count} 条K线")
            time.sleep(0.5)
        except Exception as e:
            print(f"    异常: {e}")

    ctx.close()


def analyze_returns(conn, signals):
    """分析每个买入信号的后续收益率"""
    results = []
    today_str = datetime.now().strftime('%Y-%m-%d')

    for sig in signals:
        # 获取信号日当天的VWAP作为买入价
        day0_kline = get_kline_on_date(conn, sig['code'], sig['signal_date'])
        buy_vwap = calc_vwap(day0_kline)
        if not buy_vwap:
            buy_vwap = sig['signal_price']  # fallback

        # 获取信号日之后的K线
        future_klines = get_kline_after_date(conn, sig['code'], sig['signal_date'], 15)

        row = {
            'code': sig['code'],
            'name': sig['name'],
            'signal_date': sig['signal_date'],
            'strategy': sig['strategy'],
            'buy_vwap': buy_vwap,
        }

        # 计算 T+1, T+3, T+5, T+10 的VWAP和收益率
        for label, idx in [('d1', 0), ('d3', 2), ('d5', 4), ('d10', 9)]:
            if idx < len(future_klines):
                kline = future_klines[idx]
                vwap = calc_vwap(kline)
                date = kline[0][:10]
                if vwap and buy_vwap:
                    ret_pct = (vwap - buy_vwap) / buy_vwap * 100
                else:
                    ret_pct = None
                row[f'{label}_date'] = date
                row[f'{label}_vwap'] = vwap
                row[f'{label}_ret'] = ret_pct
            else:
                row[f'{label}_date'] = '-'
                row[f'{label}_vwap'] = None
                row[f'{label}_ret'] = None

        results.append(row)
    return results


def fmt_price(val):
    if val is None:
        return '-'
    return f'{val:.3f}'


def fmt_pct(val):
    if val is None:
        return '-'
    sign = '+' if val >= 0 else ''
    return f'{sign}{val:.2f}%'


def print_results(results):
    """打印结果表格"""
    if not results:
        print("没有找到买入信号记录")
        return

    print(f"\n{'='*180}")
    print(f"{'买入信号收益率分析 (按盘中均价VWAP计算)':^180}")
    print(f"{'='*180}")

    # 表头
    header = (
        f"{'股票代码':<12} {'名称':<8} {'信号日期':<12} {'策略':<10} "
        f"{'买入均价':>10} "
        f"{'T+1日期':<12} {'T+1均价':>10} {'T+1收益':>9} "
        f"{'T+3日期':<12} {'T+3均价':>10} {'T+3收益':>9} "
        f"{'T+5日期':<12} {'T+5均价':>10} {'T+5收益':>9} "
        f"{'T+10日期':<12} {'T+10均价':>10} {'T+10收益':>9}"
    )
    print(header)
    print('-' * 180)

    for r in results:
        line = (
            f"{r['code']:<12} {r['name']:<8} {r['signal_date']:<12} {r['strategy']:<10} "
            f"{fmt_price(r['buy_vwap']):>10} "
            f"{r.get('d1_date','-'):<12} {fmt_price(r.get('d1_vwap')):>10} {fmt_pct(r.get('d1_ret')):>9} "
            f"{r.get('d3_date','-'):<12} {fmt_price(r.get('d3_vwap')):>10} {fmt_pct(r.get('d3_ret')):>9} "
            f"{r.get('d5_date','-'):<12} {fmt_price(r.get('d5_vwap')):>10} {fmt_pct(r.get('d5_ret')):>9} "
            f"{r.get('d10_date','-'):<12} {fmt_price(r.get('d10_vwap')):>10} {fmt_pct(r.get('d10_ret')):>9}"
        )
        print(line)

    # 汇总统计
    print(f"\n{'='*80}")
    print("汇总统计:")
    for label, desc in [('d1', 'T+1'), ('d3', 'T+3'), ('d5', 'T+5'), ('d10', 'T+10')]:
        rets = [r[f'{label}_ret'] for r in results if r.get(f'{label}_ret') is not None]
        if rets:
            avg = sum(rets) / len(rets)
            win_rate = len([x for x in rets if x > 0]) / len(rets) * 100
            max_r = max(rets)
            min_r = min(rets)
            print(f"  {desc}: 样本={len(rets)}, 平均收益={avg:+.2f}%, "
                  f"胜率={win_rate:.1f}%, 最大盈利={max_r:+.2f}%, 最大亏损={min_r:+.2f}%")
    print(f"{'='*80}")


def main():
    conn = sqlite3.connect(DB_PATH)
    try:
        # 1. 获取买入信号
        signals = get_deduped_buy_signals(conn)
        print(f"共找到 {len(signals)} 条去重后的买入信号")

        if not signals:
            print("没有买入信号，退出")
            return

        # 2. 检查缺失数据（跳过下载，用现有数据分析）
        missing = find_missing_kline_stocks(conn, signals)
        if missing:
            print(f"注意: {len(missing)} 只股票缺少后续K线数据，收益率将标记为 '-'")

        # 3. 分析收益率
        results = analyze_returns(conn, signals)

        # 4. 输出表格
        print_results(results)

    finally:
        conn.close()


if __name__ == '__main__':
    main()
