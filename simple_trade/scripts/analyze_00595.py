#!/usr/bin/env python3
"""分析 HK.00595 的历史K线数据"""
import sqlite3
import statistics

DB_PATH = r'd:\Program Files\futu_trade_sys\simple_trade\data\trade.db'

def analyze():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. 获取最近60天K线
    cursor.execute(
        "SELECT time_key, open_price, high_price, low_price, close_price, volume "
        "FROM kline_data WHERE stock_code = 'HK.00595' "
        "ORDER BY time_key DESC LIMIT 60"
    )
    rows = cursor.fetchall()

    if not rows:
        print("=== 未找到 HK.00595 的K线数据 ===")
        # 尝试模糊查找
        cursor.execute("SELECT DISTINCT stock_code FROM kline_data WHERE stock_code LIKE '%0595%'")
        matches = cursor.fetchall()
        if matches:
            print(f"相关股票代码: {matches}")
        else:
            print("数据库中没有0595相关数据")

        # 列出数据库中有多少小盘股
        cursor.execute("SELECT COUNT(DISTINCT stock_code) FROM kline_data")
        total = cursor.fetchone()
        print(f"数据库中共有 {total[0]} 只股票的K线数据")

        cursor.execute(
            "SELECT DISTINCT stock_code FROM kline_data ORDER BY stock_code LIMIT 30"
        )
        sample = cursor.fetchall()
        print(f"前30只样本: {[r[0] for r in sample]}")
        conn.close()
        return

    # 反转为时间正序
    rows.reverse()
    print(f"=== HK.00595 K线数据分析（最近{len(rows)}天）===\n")

    # 显示最近10天K线
    print("--- 最近10天K线 ---")
    print(f"{'日期':>12} {'开盘':>8} {'最高':>8} {'最低':>8} {'收盘':>8} {'成交量':>12} {'涨跌幅':>8}")
    for i, r in enumerate(rows[-10:]):
        date, o, h, l, c, v = r
        if i > 0 or len(rows) > 10:
            prev_idx = len(rows) - 10 + i - 1
            if prev_idx >= 0:
                prev_c = rows[prev_idx][4]
                chg = (c - prev_c) / prev_c * 100 if prev_c > 0 else 0
            else:
                chg = 0
        else:
            chg = 0
        print(f"{date[:10]:>12} {o:>8.3f} {h:>8.3f} {l:>8.3f} {c:>8.3f} {v:>12,} {chg:>7.2f}%")

    # 2. 技术指标分析
    closes = [r[4] for r in rows]
    volumes = [r[5] for r in rows]
    opens = [r[1] for r in rows]
    highs = [r[2] for r in rows]
    lows = [r[3] for r in rows]

    print("\n--- 技术指标 ---")

    # MA5, MA10, MA20
    ma5 = sum(closes[-5:]) / 5
    ma10 = sum(closes[-10:]) / 10
    ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None

    print(f"当前价格: {closes[-1]:.3f}")
    print(f"MA5: {ma5:.3f} ({'上穿' if closes[-1] > ma5 else '下穿'})")
    print(f"MA10: {ma10:.3f} ({'上穿' if closes[-1] > ma10 else '下穿'})")
    if ma20:
        print(f"MA20: {ma20:.3f} ({'上穿' if closes[-1] > ma20 else '下穿'})")

    # 量比
    avg_vol_5 = sum(volumes[-6:-1]) / 5 if len(volumes) >= 6 else sum(volumes[:-1]) / max(1, len(volumes)-1)
    vol_ratio = volumes[-1] / avg_vol_5 if avg_vol_5 > 0 else 0
    print(f"最新成交量: {volumes[-1]:,}")
    print(f"5日平均量: {avg_vol_5:,.0f}")
    print(f"量比: {vol_ratio:.2f}")

    # K线位置 (20日)
    h20 = max(highs[-20:]) if len(highs) >= 20 else max(highs)
    l20 = min(lows[-20:]) if len(lows) >= 20 else min(lows)
    position = (closes[-1] - l20) / (h20 - l20) if h20 > l20 else 0.5
    print(f"20日K线位置: {position:.2f} (0=最低, 1=最高)")
    print(f"20日最高: {h20:.3f}, 20日最低: {l20:.3f}")

    # 振幅
    amp = (highs[-1] - lows[-1]) / closes[-2] * 100 if len(closes) >= 2 and closes[-2] > 0 else 0
    print(f"最近一天振幅: {amp:.2f}%")

    # 距高点回撤
    peak = max(closes[-20:]) if len(closes) >= 20 else max(closes)
    drawdown = (peak - closes[-1]) / peak * 100 if peak > 0 else 0
    print(f"距20日高点回撤: {drawdown:.2f}%")

    # 趋势判断
    print("\n--- 趋势分析 ---")
    # 最近5日涨跌幅
    chg5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 else 0
    chg10 = (closes[-1] - closes[-11]) / closes[-11] * 100 if len(closes) >= 11 else 0
    chg20 = (closes[-1] - closes[-21]) / closes[-21] * 100 if len(closes) >= 21 else 0
    print(f"5日涨跌幅: {chg5:.2f}%")
    print(f"10日涨跌幅: {chg10:.2f}%")
    print(f"20日涨跌幅: {chg20:.2f}%")

    # 连阳/连阴
    consec = 0
    direction = None
    for i in range(len(closes)-1, max(len(closes)-8, 0), -1):
        if closes[i] > opens[i]:
            if direction is None:
                direction = 'up'
            if direction == 'up':
                consec += 1
            else:
                break
        else:
            if direction is None:
                direction = 'down'
            if direction == 'down':
                consec += 1
            else:
                break
    print(f"连续{direction or '?'}: {consec}天")

    # 最后一根K线形态
    last_o, last_h, last_l, last_c = opens[-1], highs[-1], lows[-1], closes[-1]
    body = abs(last_c - last_o)
    upper_shadow = last_h - max(last_c, last_o)
    lower_shadow = min(last_c, last_o) - last_l
    total_range = last_h - last_l if last_h > last_l else 0.001

    print(f"\n--- 最后一根K线形态 ---")
    print(f"实体: {body:.4f} ({'阳线' if last_c > last_o else '阴线'})")
    print(f"上影线: {upper_shadow:.4f} ({upper_shadow/total_range*100:.1f}%)")
    print(f"下影线: {lower_shadow:.4f} ({lower_shadow/total_range*100:.1f}%)")

    if upper_shadow > body * 2 and lower_shadow < body:
        print("形态: 射击之星/墓碑十字（看跌信号）")
    elif lower_shadow > body * 2 and upper_shadow < body:
        print("形态: 锤子线（看涨信号）")
    elif body < total_range * 0.1:
        print("形态: 十字星（犹豫信号）")
    elif last_c > last_o:
        print("形态: 阳线")
    else:
        print("形态: 阴线")

    # 3. 资金流数据
    print("\n--- 资金流数据 ---")
    cursor.execute(
        "SELECT date, net_inflow FROM capital_flow_daily "
        "WHERE stock_code = 'HK.00595' ORDER BY date DESC LIMIT 10"
    )
    cap_rows = cursor.fetchall()
    if cap_rows:
        print(f"{'日期':>12} {'净流入':>15}")
        for r in reversed(cap_rows):
            print(f"{r[0][:10]:>12} {r[1]:>15,.0f}")
        # 连续净流入天数
        cont = 0
        for r in cap_rows:
            if r[1] and r[1] > 0:
                cont += 1
            else:
                break
        print(f"连续净流入天数: {cont}")
    else:
        print("无资金流数据")

    # 4. 资金评分
    cursor.execute(
        "SELECT capital_score, net_inflow_ratio, big_order_buy_ratio, main_net_inflow "
        "FROM capital_flow_cache WHERE stock_code = 'HK.00595' "
        "ORDER BY timestamp DESC LIMIT 1"
    )
    cache = cursor.fetchone()
    if cache:
        print(f"\n资金评分: {cache[0]:.1f}")
        print(f"净流入比: {cache[1]:.4f}")
        print(f"大单买入比: {cache[2]:.4f}")
        print(f"主力净流入: {cache[3]:,.0f}")

    # 5. 交易信号（跳过，表结构不确定）
    print("\n（交易信号查询已跳过）")

    # 6. 小盘股特征分析
    print("\n--- 小盘股特征分析 ---")

    # ATR计算（14日）
    atr_period = min(14, len(rows)-1)
    tr_list = []
    for i in range(len(rows)-atr_period, len(rows)):
        if i <= 0:
            continue
        tr = max(
            rows[i][2] - rows[i][3],  # 当日高-低
            abs(rows[i][2] - rows[i-1][4]),  # 当日高-昨收
            abs(rows[i][3] - rows[i-1][4]),  # 当日低-昨收
        )
        tr_list.append(tr)
    atr = sum(tr_list) / len(tr_list) if tr_list else 0
    atr_pct = atr / closes[-1] * 100 if closes[-1] > 0 else 0
    print(f"ATR(14): {atr:.4f} ({atr_pct:.2f}%)")

    # 波动率（20日收益率标准差）
    daily_returns = []
    for i in range(1, min(21, len(closes))):
        ret = (closes[-i] - closes[-i-1]) / closes[-i-1] if closes[-i-1] > 0 else 0
        daily_returns.append(ret)
    if daily_returns:
        volatility = statistics.stdev(daily_returns) * 100
        print(f"20日波动率: {volatility:.2f}%")

    # 支撑阻力位
    support_lows = sorted(lows[-10:])[:3]
    support = statistics.median(support_lows) if len(support_lows) >= 3 else min(support_lows)
    resist_highs = sorted(highs[-10:], reverse=True)[:3]
    resistance = statistics.median(resist_highs) if len(resist_highs) >= 3 else max(resist_highs)
    print(f"近期支撑位: {support:.3f}")
    print(f"近期阻力位: {resistance:.3f}")

    # 综合判定
    print("\n" + "="*50)
    print("=== 次日情况综合预判 ===")
    print("="*50)

    bullish_signals = 0
    bearish_signals = 0

    # 均线判断
    if closes[-1] > ma5 > ma10:
        print("✅ 均线多头排列")
        bullish_signals += 1
    elif closes[-1] < ma5 < ma10:
        print("❌ 均线空头排列")
        bearish_signals += 1
    else:
        print("⚠️ 均线缠绕")

    # 量价
    if vol_ratio > 1.2 and closes[-1] > opens[-1]:
        print("✅ 放量阳线")
        bullish_signals += 1
    elif vol_ratio > 1.2 and closes[-1] < opens[-1]:
        print("❌ 放量阴线")
        bearish_signals += 1
    elif vol_ratio < 0.8:
        print("⚠️ 缩量")

    # 位置
    if position < 0.3:
        print("✅ 低位区间")
        bullish_signals += 1
    elif position > 0.8:
        print("⚠️ 高位区间")
        bearish_signals += 1

    # 趋势
    if chg5 > 0 and chg10 > 0:
        print("✅ 中短期趋势向上")
        bullish_signals += 1
    elif chg5 < 0 and chg10 < 0:
        print("❌ 中短期趋势向下")
        bearish_signals += 1

    # 资金
    if cap_rows:
        cont = 0
        for r in cap_rows:
            if r[1] and r[1] > 0:
                cont += 1
            else:
                break
        if cont >= 3:
            print(f"✅ 资金连续{cont}天净流入")
            bullish_signals += 1
        elif cont == 0 and cap_rows[0][1] and cap_rows[0][1] < 0:
            print("❌ 最新资金净流出")
            bearish_signals += 1

    print(f"\n看多信号: {bullish_signals}个")
    print(f"看空信号: {bearish_signals}个")

    if bullish_signals >= 3 and bearish_signals <= 1:
        verdict = "偏多 — 次日有上涨动力"
    elif bearish_signals >= 3 and bullish_signals <= 1:
        verdict = "偏空 — 次日有回调风险"
    elif bullish_signals > bearish_signals:
        verdict = "中性偏多 — 关注关键位置表现"
    elif bearish_signals > bullish_signals:
        verdict = "中性偏空 — 建议观望"
    else:
        verdict = "中性震荡 — 方向不明"

    print(f"\n📊 综合判定: {verdict}")
    print(f"📈 支撑位: {support:.3f}")
    print(f"📉 阻力位: {resistance:.3f}")
    if closes[-1] > 0:
        print(f"📐 预计波动区间: {closes[-1]-atr:.3f} ~ {closes[-1]+atr:.3f} (基于ATR)")

    conn.close()

if __name__ == '__main__':
    analyze()
