#!/usr/bin/env python3
"""组合卖出策略: 追踪止盈+高抛兜底, 最大15天"""
import sqlite3, os
from datetime import datetime

DB = os.path.join(os.path.dirname(__file__), '..', 'simple_trade', 'data', 'trade.db')
OUT = os.path.join(os.path.dirname(__file__), 'backtest_hybrid.md')
SL, TC, MH, LB = -10, 5, 15, 12
TRAIL_PCT, ACTIVATE_PCT = 3, 8

def vwap(r):
    if not r: return None
    v,t=r[5],r[6]
    if v and v>0 and t and t>0: return t/v
    ps=[p for p in r[1:5] if p]
    return sum(ps)/len(ps) if ps else None

def is_ht(kl,i):
    if i<1 or i>=len(kl): return False
    th,yh=kl[i][3],kl[i-1][3]
    if not th or not yh or th>=yh: return False
    s=max(0,i-LB)
    hs=[kl[j][3] for j in range(s,i) if kl[j][3]]
    return yh==max(hs) if hs else False

def main():
    conn=sqlite3.connect(DB); c=conn.cursor()
    c.execute("""SELECT ts.id,s.code,s.name,ts.signal_price,ts.created_at
        FROM trade_signals ts JOIN stocks s ON ts.stock_id=s.id
        WHERE ts.signal_type='BUY' AND (ts.strategy_name='趋势反转策略' OR ts.strategy_id='trend_reversal')
        ORDER BY ts.created_at DESC""")
    seen,sigs=set(),[]
    for r in c.fetchall():
        k=(r[1],r[4][:10])
        if k not in seen: seen.add(k); sigs.append({'code':r[1],'name':r[2],'price':r[3],'date':r[4][:10]})

    trades,pending=[],[]
    for sig in sigs:
        code,bd=sig['code'],sig['date']
        c.execute("SELECT time_key,open_price,close_price,high_price,low_price,volume,turnover FROM kline_data WHERE stock_code=? AND DATE(time_key)=DATE(?) LIMIT 1",(code,bd))
        d0=c.fetchone()
        if not d0 or not d0[1] or not d0[2] or d0[2]<=d0[1]: continue
        c.execute("SELECT time_key,open_price,close_price,high_price,low_price,volume,turnover FROM kline_data WHERE stock_code=? AND DATE(time_key)>DATE(?) ORDER BY time_key LIMIT ?",(code,bd,MH+5))
        fut=c.fetchall()
        if not fut: continue
        bp=fut[0][1] or vwap(fut[0]); fut=fut[1:]
        if not bp or len(fut)<TC: pending.append(sig); continue

        sp=sd=sr=None; hd=0; mx=bp; activated=False
        for i in range(len(fut)):
            hd=i+1; dv=vwap(fut[i]); dc=fut[i][2]; cur=dv or dc or bp
            if fut[i][3] and fut[i][3]>mx: mx=fut[i][3]
            ret=(cur-bp)/bp*100; pk=(mx-bp)/bp*100; dd=(mx-cur)/mx*100 if mx>0 else 0
            if pk>=ACTIVATE_PCT: activated=True
            # 1.止损
            if ret<=SL: sp,sd,sr=cur,fut[i][0][:10],f'止损({ret:.0f}%)'; break
            # 2.T验证
            if hd==TC:
                up=sum(1 for j in range(TC) if fut[j][2] and fut[j][1] and fut[j][2]>fut[j][1])
                if ret<0 and up<1: sp,sd,sr=dc or cur,fut[i][0][:10],'趋势未延续'; break
            # 3+4.卖出(T验证后)
            if hd>TC:
                if activated and dd>=TRAIL_PCT:
                    sp,sd,sr=dv or cur,fut[i][0][:10],f'追踪止盈(峰{pk:.0f}%回撤{dd:.0f}%)'; break
                if not activated and is_ht(fut,i):
                    sp,sd,sr=dv or cur,fut[i][0][:10],f'高抛兜底({ret:.0f}%)'; break
            # 5.超时
            if hd>=MH: sp,sd,sr=cur,fut[i][0][:10],'超时'; break

        if sp:
            trades.append({'ret':(sp-bp)/bp*100,'days':hd,'reason':sr.split('(')[0].strip(),
                'code':sig['code'],'name':sig['name'],'buy_date':bd,'buy_price':bp,
                'sell_date':sd,'sell_price':sp,'max_rise':(mx-bp)/bp*100,'reason_full':sr})
        else: pending.append(sig)
    conn.close()

    # 报告
    L=['# 组合卖出策略回测\n']
    L.append(f'> 生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    L.append(f'> 买入: 阳线确认+T+1开盘 | 止损: {SL}% | T{TC}验证 | 最大{MH}天')
    L.append(f'> 卖出: 涨≥{ACTIVATE_PCT}%激活追踪(回撤{TRAIL_PCT}%卖) + 未激活用高抛(LB{LB})兜底\n')

    if trades:
        rets=[t['ret'] for t in trades]; wins=[r for r in rets if r>0]; losses=[r for r in rets if r<=0]
        days=[t['days'] for t in trades]; aw=sum(wins)/len(wins) if wins else 0; al=abs(sum(losses)/len(losses)) if losses else 1
        maxr=[t['max_rise'] for t in trades]; cap=sum(rets)/sum(maxr)*100 if sum(maxr)>0 else 0

        L.append('## 汇总\n')
        L.append(f'| 指标 | 值 |\n|------|------|\n| 交易数 | {len(trades)} |\n| 平均收益 | {sum(rets)/len(rets):+.2f}% |')
        L.append(f'| 胜率 | {len(wins)/len(trades)*100:.0f}% |\n| 盈亏比 | {aw/al:.2f} |\n| 平均持有 | {sum(days)/len(days):.1f}天 |')
        L.append(f'| 最大盈利 | {max(rets):+.1f}% |\n| 最大亏损 | {min(rets):+.1f}% |\n| 利润捕获率 | {cap:.0f}% |\n')

        reasons={}
        for t in trades: reasons.setdefault(t['reason'],[]).append(t)
        L.append('## 按退出原因\n')
        L.append('| 原因 | 数量 | 平均收益 | 胜率 |')
        L.append('|------|------|---------|------|')
        for rn,grp in sorted(reasons.items()):
            gr=[t['ret'] for t in grp]; gw=len([r for r in gr if r>0])
            L.append(f"| {rn} | {len(grp)} | {sum(gr)/len(gr):+.2f}% | {gw/len(grp)*100:.0f}% |")

        L.append('\n## 详细记录\n')
        L.append('| 股票 | 买入日 | 买入价 | 卖出日 | 卖出价 | 天数 | 收益 | 最高涨幅 | 原因 |')
        L.append('|------|--------|--------|--------|--------|------|------|---------|------|')
        for t in sorted(trades, key=lambda x:x['ret'], reverse=True):
            rs=f"+{t['ret']:.1f}%" if t['ret']>=0 else f"{t['ret']:.1f}%"
            L.append(f"| {t['code']} {t['name']} | {t['buy_date']} | {t['buy_price']:.2f} | {t['sell_date']} | {t['sell_price']:.2f} | {t['days']} | {rs} | +{t['max_rise']:.1f}% | {t['reason_full']} |")

    if pending:
        L.append(f'\n## 待观察({len(pending)}条)\n')
        for p in pending: L.append(f"- {p['code']} {p['name']} {p['date']}")

    with open(OUT,'w',encoding='utf-8') as f: f.write('\n'.join(L))
    print(f'Report: {OUT}')

if __name__=='__main__': main()
