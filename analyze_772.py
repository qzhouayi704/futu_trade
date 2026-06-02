#!/usr/bin/env python3
"""分析 HK.00772 (阅文集团) - 综合评分脚本 v2"""
import sys, os, sqlite3, time
sys.path.insert(0, '/opt/futu_trade_sys')
os.chdir('/opt/futu_trade_sys')

from datetime import datetime
today = datetime.now().strftime('%Y-%m-%d')

print("=" * 60)
print("  HK.00772 阅文集团 综合分析报告")
print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 60)

# === 1. 实时行情 ===
print("\n[1] 实时行情数据")
print("-" * 40)
from futu import OpenQuoteContext, RET_OK, KLType, SubType
ctx = OpenQuoteContext(host='127.0.0.1', port=11111)

ret, data = ctx.get_market_snapshot(['HK.00772'])
if ret == RET_OK and not data.empty:
    row = data.iloc[0]
    last_price = row.get('last_price', 0)
    prev_close = row.get('prev_close_price', 0)
    high_price = row.get('high_price', 0)
    low_price = row.get('low_price', 0)
    amplitude = row.get('amplitude', 0)
    volume = row.get('volume', 0)
    turnover = row.get('turnover', 0)
    change_rate = ((last_price - prev_close) / prev_close * 100) if prev_close else 0
    print(f"  名称: {row.get('name','?')}  |  最新: {last_price:.3f}  |  涨跌: {change_rate:+.2f}%")
    print(f"  开:{row.get('open_price',0):.3f} 高:{high_price:.3f} 低:{low_price:.3f} 昨收:{prev_close:.3f}")
    print(f"  量:{volume:,.0f}  额:{turnover/1e6:,.2f}M  换手:{row.get('turnover_rate',0):.2f}%  振幅:{amplitude:.2f}%")
    pe = row.get('pe_ttm_ratio', 0)
    pb = row.get('pb_ratio', 0)
    mv = row.get('market_val', 0)
    if mv: print(f"  市值:{mv/1e8:,.1f}亿  PE:{pe:.1f}  PB:{pb:.2f}")
else:
    print(f"  快照失败: {data}")
    last_price = prev_close = high_price = low_price = amplitude = change_rate = 0

# === 2. K线 (订阅后获取) ===
print("\n[2] K线技术分析")
print("-" * 40)
change_5d = 0; kline_pos = 0.5; vol_ratio = 1.0; prev_change = 0
try:
    ret_sub, err = ctx.subscribe(['HK.00772'], [SubType.K_DAY], subscribe_push=False)
    if ret_sub == RET_OK:
        time.sleep(0.3)
        ret_k, kdata = ctx.get_cur_kline('HK.00772', 25, KLType.K_DAY)
        if ret_k == RET_OK and not kdata.empty:
            closes = kdata['close'].tolist()
            highs = kdata['high'].tolist()
            lows = kdata['low'].tolist()
            volumes = kdata['volume'].tolist()
            if len(closes) >= 6:
                change_5d = (closes[-1] - closes[-6]) / closes[-6] * 100
                print(f"  5日涨跌: {change_5d:+.2f}%")
            if len(closes) >= 11:
                print(f"  10日涨跌: {(closes[-1]-closes[-11])/closes[-11]*100:+.2f}%")
            if len(closes) >= 21:
                print(f"  20日涨跌: {(closes[-1]-closes[-21])/closes[-21]*100:+.2f}%")
            h20 = max(highs[-20:]); l20 = min(lows[-20:])
            if h20 > l20:
                kline_pos = (closes[-1] - l20) / (h20 - l20)
                print(f"  K线位置: {kline_pos:.3f}")
            if len(volumes) >= 6:
                avg5 = sum(volumes[-6:-1]) / 5
                vol_ratio = volumes[-1] / avg5 if avg5 > 0 else 1
                print(f"  量比: {vol_ratio:.2f}")
            if len(closes) >= 3:
                prev_change = (closes[-2] - closes[-3]) / closes[-3] * 100
                print(f"  前日涨跌: {prev_change:+.2f}%")
            # MA
            if len(closes)>=5: print(f"  MA5: {sum(closes[-5:])/5:.3f}")
            if len(closes)>=10: print(f"  MA10: {sum(closes[-10:])/10:.3f}")
            if len(closes)>=20: print(f"  MA20: {sum(closes[-20:])/20:.3f}")
            # 近5日
            print(f"\n  近5日K线:")
            for i in range(-5, 0):
                if abs(i) <= len(kdata):
                    r = kdata.iloc[i]
                    c = (r['close']-r['open'])/r['open']*100 if r['open'] else 0
                    print(f"    {r['time_key'][:10]} O:{r['open']:.2f} H:{r['high']:.2f} L:{r['low']:.2f} C:{r['close']:.2f} {'▲' if c>=0 else '▼'}{abs(c):.1f}% V:{r['volume']:,.0f}")
        else:
            print(f"  K线获取失败: {kdata}")
    else:
        print(f"  订阅失败: {err}")
except Exception as e:
    print(f"  K线异常: {e}")

# === 3. 数据库查询 (sqlite3直连) ===
db_path = '/opt/futu_trade_sys/data/trade_data.db'
db = None
if os.path.exists(db_path):
    db = sqlite3.connect(db_path)

# 逐笔成交
print("\n[3] 逐笔成交分析")
print("-" * 40)
ticker_power = None
if db:
    try:
        cur = db.execute(
            """SELECT SUM(CASE WHEN direction='BUY' THEN volume ELSE 0 END),
                      SUM(CASE WHEN direction='SELL' THEN volume ELSE 0 END),
                      SUM(CASE WHEN direction='BUY' THEN turnover ELSE 0 END),
                      SUM(CASE WHEN direction='SELL' THEN turnover ELSE 0 END),
                      COUNT(*)
               FROM ticker_data WHERE stock_code='HK.00772' AND trade_date=?""", (today,))
        r = cur.fetchone()
        if r and r[4] and r[4] > 0:
            bv, sv, ba, sa, tc = r
            bv=bv or 0; sv=sv or 0; ba=ba or 0; sa=sa or 0
            tv = bv + sv
            bsr = bv/sv if sv>0 else 0
            ticker_power = bsr - 1.0
            print(f"  逐笔数: {tc:,}  主买量: {bv:,.0f}({bv/tv*100:.1f}%)  主卖量: {sv:,.0f}({sv/tv*100:.1f}%)")
            print(f"  主买额: {ba/1e6:.2f}M  主卖额: {sa/1e6:.2f}M  买卖比: {bsr:.3f}  力量: {ticker_power:+.3f}")
        else:
            print("  今日无逐笔数据")
    except Exception as e:
        print(f"  异常: {e}")
else:
    print("  数据库不存在")

# 资金流向
print("\n[4] 资金流向")
print("-" * 40)
if db:
    try:
        cur = db.execute(
            """SELECT timestamp, net_inflow_ratio, capital_score
               FROM capital_flow_cache WHERE stock_code='HK.00772'
               ORDER BY timestamp DESC LIMIT 5""")
        rows = cur.fetchall()
        if rows:
            for r in rows:
                nir = r[1] or 0; score = r[2] or 0
                d = "流入" if nir>0.02 else ("流出" if nir<-0.02 else "均衡")
                print(f"  {r[0][:19]} | 净流入比:{nir:+.4f} | 评分:{score:.0f} | {d}")
        else:
            print("  无资金流向数据")
    except Exception as e:
        print(f"  异常: {e}")

# 大单
print("\n[5] 大单追踪")
print("-" * 40)
if db:
    try:
        cur = db.execute(
            """SELECT timestamp, big_buy_count, big_sell_count,
                      big_buy_amount, big_sell_amount, buy_sell_ratio
               FROM big_order_tracking WHERE stock_code='HK.00772'
               ORDER BY timestamp DESC LIMIT 5""")
        rows = cur.fetchall()
        if rows:
            for r in rows:
                print(f"  {r[0][:19]} | 大买:{r[1]} 大卖:{r[2]} | 买额:{(r[3] or 0)/1e6:.2f}M 卖额:{(r[4] or 0)/1e6:.2f}M | 比:{r[5]:.2f}")
        else:
            print("  无大单数据")
    except Exception as e:
        print(f"  异常: {e}")

# === 6. 策略评分 ===
print("\n[6] 策略评分")
print("-" * 40)
from simple_trade.services.strategy.stock_scorer import StockScorer, PASSING_SCORE
scorer = StockScorer()
indicators = {
    'change_5d': change_5d, 'kline_pos_20d': kline_pos,
    'day_amplitude': amplitude if amplitude else None,
    'vol_ratio': vol_ratio, 'prev_day_change': prev_change,
    'ticker_power': ticker_power, 'today_change': change_rate or None,
}
print(f"  指标: {indicators}")
results = scorer.score_all_strategies('HK.00772', '阅文集团', indicators)

for mode in ['trend', 'breakout', 'momentum']:
    r = results[mode]
    triggered = results.get(f'{mode}_triggered', True)
    st = "✅通过" if r.passed else "❌未通过"
    tm = "" if triggered else " [未触发]"
    print(f"\n  [{mode.upper()}] {r.total_score}/100 {st}{tm}")
    if r.veto_reason: print(f"    否决: {r.veto_reason}")
    for d in r.details:
        bar = "█" * (d.score * 15 // d.max_score) if d.max_score > 0 else ""
        print(f"    {d.dimension:8s} {d.score:2d}/{d.max_score:2d} {bar:15s} {d.value} {d.note}")

best = results['best']
print(f"\n  >>> 最佳: {best.mode}({best.total_score}分) {'✅建议关注' if best.passed else '❌暂不建议'}")
if best.trade_params:
    tp = best.trade_params
    print(f"  >>> 低吸:{tp.buy_dip_pct}% 止盈:{tp.take_profit_pct}% 止损:{tp.stop_loss_pct}% 持仓:{tp.max_hold_days}天 {tp.confidence} {tp.reason}")

# === 7. 结论 ===
print("\n" + "=" * 60)
print("  综合结论")
print("=" * 60)
if best.passed:
    print(f"  ✅ {best.mode}策略通过 ({best.total_score}分)")
else:
    print(f"  ❌ 所有策略未达标 (最高:{best.total_score}分)")
if ticker_power is not None:
    if ticker_power > 0.2: print(f"  ✅ 买盘强势 ({ticker_power:+.3f})")
    elif ticker_power < -0.2: print(f"  ⚠️ 卖压较大 ({ticker_power:+.3f})")
    else: print(f"  ➖ 买卖均衡 ({ticker_power:+.3f})")
if vol_ratio >= 2: print(f"  ✅ 量比放大 ({vol_ratio:.2f})")
elif vol_ratio >= 1.5: print(f"  ➖ 量比温和 ({vol_ratio:.2f})")
else: print(f"  ⚠️ 量比偏低 ({vol_ratio:.2f})")
if -5 < change_5d < 15: print(f"  ✅ 5日涨跌合理 ({change_5d:+.2f}%)")
else: print(f"  ⚠️ 5日偏极端 ({change_5d:+.2f}%)")
print("=" * 60)

ctx.close()
if db: db.close()
