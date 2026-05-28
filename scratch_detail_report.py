#!/usr/bin/env python3
"""输出完整信号提醒+交易记录到文件"""
import sqlite3, os, sys
from collections import defaultdict

DB_PATH = os.environ.get("DB_PATH", "/opt/futu_trade_sys/simple_trade/data/trade.db")
OUT_FILE = "/opt/futu_trade_sys/backtest_detail_report.txt"

MEGA_MULTIPLIER = 3
SCAN_INTERVAL = 3
COOLDOWN_MINUTES = 15
CONFLICT_WINDOW = 15
SUSTAINED_RATIO = 0.35
SUSTAINED_MINUTES = 20
ACCEL_THRESHOLD = 3.0
MEGA_FLOOR_PCT = 0.02
MEGA_FLOOR_MIN = 50
RESONANCE_WINDOW = 15
SNIPER_STRENGTH = {'mega_buy':90,'accel_in':0,'reversal_bull':0,'mega_sell':95,'reversal_bear':30,'sustained_out':20}
INITIAL_CAPITAL = 25000
MAX_POSITIONS = 2
MAX_SINGLE_PCT = 0.50
CASH_RESERVE_PCT = 0.30
TAKE_PROFIT_PCT = 5.0
STOP_LOSS_PCT = 3.0
TRADE_COST_PCT = 0.15
BUY_COOLDOWN_MIN = 30
BUY_DIP_PCT = 1.0

def load_minute_data(db, stock_code, trade_date):
    rows = db.execute("""
        SELECT substr(datetime(timestamp/1000,'unixepoch','+8 hours'),12,5) as minute,
               direction, SUM(turnover) as tv, AVG(price) as ap
        FROM ticker_data WHERE stock_code=? AND trade_date=?
        GROUP BY minute, direction ORDER BY minute
    """, (stock_code, trade_date)).fetchall()
    minutes = {}
    for minute, direction, turnover, avg_price in rows:
        if not ('09:15' <= minute <= '16:10'): continue
        if minute not in minutes:
            minutes[minute] = {'buy':0.0,'sell':0.0,'price':0,'price_n':0}
        e = minutes[minute]
        tv = float(turnover or 0)
        if direction == 'BUY': e['buy'] += tv
        elif direction == 'SELL': e['sell'] += tv
        if avg_price and float(avg_price) > 0:
            e['price'] += float(avg_price); e['price_n'] += 1
    timeline = []
    cum_buy, cum_sell = 0.0, 0.0
    for m in sorted(minutes.keys()):
        e = minutes[m]
        cum_buy += e['buy']; cum_sell += e['sell']
        net = e['buy'] - e['sell']
        price = round(e['price']/e['price_n'],3) if e['price_n']>0 else 0
        timeline.append({'time':m,'net':round(net/10000,1),'cum_net':round((cum_buy-cum_sell)/10000,1),'price':price,'turnover':round((e['buy']+e['sell'])/10000,1)})
    return timeline

def detect_signals(timeline):
    signals = []
    cooldown = {}
    prev_dir = 'neutral'
    recent = []
    for i, p in enumerate(timeline):
        past = timeline[:i+1]
        day_total = sum(x['turnover'] for x in past)
        if day_total < 100: continue
        tvs = [x['turnover'] for x in past if x['turnover']>0]
        avg_tv = sum(tvs)/len(tvs) if tvs else 0
        if avg_tv <= 0: continue
        mega_floor = max(MEGA_FLOOR_MIN, day_total * MEGA_FLOOR_PCT)
        abs_nets = [abs(x['net']) for x in past if x['net']!=0]
        avg_abs = sum(abs_nets)/len(abs_nets) if abs_nets else avg_tv
        dyn_mega = max(mega_floor, avg_abs * MEGA_MULTIPLIER)
        accel_min = mega_floor * 0.5
        rev_min = mega_floor
        dyn_sustained = max(SUSTAINED_RATIO*avg_tv*SUSTAINED_MINUTES, mega_floor*0.6)
        def can(st,red):
            if st in cooldown and i-cooldown[st]<COOLDOWN_MINUTES: return False
            cut=max(0,i-CONFLICT_WINDOW)
            for _,r_red,r_idx in recent:
                if r_idx>=cut and ((red and not r_red) or (not red and r_red)): return False
            return True
        def emit(st,red):
            cooldown[st]=i
            recent.append((p['time'],red,i))
            cut=max(0,i-CONFLICT_WINDOW*2)
            while recent and recent[0][2]<cut: recent.pop(0)
            signals.append({'time':p['time'],'is_red':red,'idx':i,'type':st,'price':p['price'],'strength':SNIPER_STRENGTH.get(st,0),'dyn_mega':round(dyn_mega,1),'net':p['net']})
        is_scan = (i%SCAN_INTERVAL==0 and i>0)
        if p['net']<-dyn_mega and can('mega_sell',True): emit('mega_sell',True)
        if p['net']>dyn_mega and can('mega_buy',False): emit('mega_buy',False)
        if is_scan:
            curr_dir='positive' if p['cum_net']>0 else ('negative' if p['cum_net']<0 else 'neutral')
            if prev_dir=='negative' and curr_dir=='positive' and p['cum_net']>rev_min:
                if can('reversal_bull',False): emit('reversal_bull',False)
            if prev_dir=='positive' and curr_dir=='negative' and p['cum_net']<-rev_min:
                if can('reversal_bear',True): emit('reversal_bear',True)
            if i>=6:
                recent_3=sum(timeline[j]['net'] for j in range(i-2,i+1))
                prev_3=sum(timeline[j]['net'] for j in range(i-5,i-2))
                if prev_3>0 and recent_3>prev_3*ACCEL_THRESHOLD and recent_3>accel_min:
                    if can('accel_in',False): emit('accel_in',False)
            if i>=SUSTAINED_MINUTES:
                window_net=sum(timeline[j]['net'] for j in range(i-SUSTAINED_MINUTES+1,i+1))
                if window_net<-dyn_sustained:
                    if can('sustained_out',True): emit('sustained_out',True)
            prev_dir=curr_dir
    return signals

def check_resonance(signals, cur_idx):
    cur_signals = [s for s in signals if s['idx']==cur_idx and not s['is_red']]
    if not cur_signals: return None, None
    for s in cur_signals:
        if s.get('strength',0)>=80: return 'strong_single', s
    cutoff=max(0,cur_idx-RESONANCE_WINDOW)
    recent_buys=[s for s in signals if not s['is_red'] and s['idx']>=cutoff and s['idx']<=cur_idx]
    green_types=set(s['type'] for s in recent_buys)
    if len(green_types)>=2:
        latest=max(recent_buys,key=lambda s:s['idx'])
        return 'multi_green', latest
    return None, None

class Portfolio:
    def __init__(self,capital):
        self.cash=capital;self.positions={};self.trades=[];self.cooldown={}
    def can_buy(self,code,cur_min_idx):
        if code in self.positions: return False
        if len(self.positions)>=MAX_POSITIONS: return False
        if code in self.cooldown and cur_min_idx-self.cooldown[code]<BUY_COOLDOWN_MIN: return False
        return True
    def buy(self,code,name,price,min_idx,date,resonance_type=''):
        if price<=0: return
        exec_price=price*(1-BUY_DIP_PCT/100)
        investable=self.cash*(1-CASH_RESERVE_PCT)
        max_amt=investable*MAX_SINGLE_PCT
        qty=int(max_amt/exec_price/100)*100
        if qty<100: return
        cost=exec_price*qty*(1+TRADE_COST_PCT/100)
        if cost>self.cash: return
        self.cash-=cost
        self.positions[code]={'qty':qty,'entry':exec_price,'idx':min_idx,'name':name}
        self.trades.append({'date':date,'code':code,'name':name,'dir':'BUY','price':exec_price,'qty':qty,'cost':round(cost,2),'time_idx':min_idx,'resonance':resonance_type})
    def sell(self,code,price,reason,min_idx,date):
        if code not in self.positions or price<=0: return 0
        pos=self.positions.pop(code)
        proceeds=price*pos['qty']*(1-TRADE_COST_PCT/100)
        self.cash+=proceeds
        pnl=proceeds-pos['entry']*pos['qty']*(1+TRADE_COST_PCT/100)
        pnl_pct=(price/pos['entry']-1)*100
        self.cooldown[code]=min_idx
        self.trades.append({'date':date,'code':code,'name':pos['name'],'dir':'SELL','price':price,'qty':pos['qty'],'proceeds':round(proceeds,2),'pnl':round(pnl,2),'pnl_pct':round(pnl_pct,2),'reason':reason,'hold_min':min_idx-pos['idx'],'time_idx':min_idx})
        return pnl
    def check_exits(self,code,cur_price,min_idx,date):
        if code not in self.positions: return
        pos=self.positions[code]
        chg=(cur_price/pos['entry']-1)*100
        if chg>=TAKE_PROFIT_PCT: self.sell(code,cur_price,f'止盈{chg:+.1f}%',min_idx,date)
        elif chg<=-STOP_LOSS_PCT: self.sell(code,cur_price,f'止损{chg:+.1f}%',min_idx,date)
    def force_close_all(self,stock_data,date):
        for code in list(self.positions.keys()):
            if code in stock_data:
                tl=stock_data[code]
                for p in reversed(tl):
                    if p['price']>0:
                        self.sell(code,p['price'],'收盘平仓',len(tl)-1,date);break

def main():
    db=sqlite3.connect(DB_PATH)
    dates=[r[0] for r in db.execute("SELECT DISTINCT trade_date FROM ticker_data ORDER BY trade_date ASC").fetchall()]
    f=open(OUT_FILE,'w',encoding='utf-8')
    def w(s=''): f.write(s+'\n'); print(s)

    w(f"{'='*100}")
    w(f"  完整信号提醒 + 交易记录报告")
    w(f"  回测期间: {dates[0]} ~ {dates[-1]} ({len(dates)}天)")
    w(f"  参数: 止盈{TAKE_PROFIT_PCT}% 止损{STOP_LOSS_PCT}% 最大持仓{MAX_POSITIONS} 挂低{BUY_DIP_PCT}%买入")
    w(f"  阈值: MEGA_FLOOR=max({MEGA_FLOOR_MIN}, day_total×{MEGA_FLOOR_PCT*100}%) MULTIPLIER={MEGA_MULTIPLIER}")
    w(f"{'='*100}")

    pf=Portfolio(INITIAL_CAPITAL)
    for trade_date in dates:
        day_start=pf.cash
        codes=[r[0] for r in db.execute("SELECT DISTINCT stock_code FROM ticker_data WHERE trade_date=?",(trade_date,)).fetchall()]
        stock_data={};stock_signals={}
        for code in codes:
            tl=load_minute_data(db,code,trade_date)
            if len(tl)<10: continue
            stock_data[code]=tl
            sigs=detect_signals(tl)
            if sigs: stock_signals[code]=sigs

        w(f"\n{'─'*100}")
        w(f"  📅 {trade_date}  ({len(stock_data)}只活跃股票, 余额=${pf.cash:,.2f})")
        w(f"{'─'*100}")

        # 输出当日所有信号（按时间排序）
        all_sigs=[]
        for code,sigs in stock_signals.items():
            for s in sigs:
                all_sigs.append({**s,'code':code})
        all_sigs.sort(key=lambda x:x['time'])

        if all_sigs:
            w(f"\n  📡 当日信号提醒 ({len(all_sigs)}条):")
            for s in all_sigs:
                emoji='🔴' if s['is_red'] else '🟢'
                w(f"    {emoji} {s['time']} {s['code']:<12} {s['type']:<16} @${s['price']:.3f}  净流={s['net']:+.1f}万 阈值={s['dyn_mega']:.0f}万")

        # 执行交易逻辑
        all_minutes=set()
        for tl in stock_data.values():
            for p in tl: all_minutes.add(p['time'])
        day_trades_before=len(pf.trades)

        for minute in sorted(all_minutes):
            for code in list(pf.positions.keys()):
                if code in stock_data:
                    tl=stock_data[code]
                    for p in tl:
                        if p['time']==minute and p['price']>0:
                            pf.check_exits(code,p['price'],tl.index(p),trade_date)
            for code,sigs in stock_signals.items():
                for sig in sigs:
                    if sig['time']!=minute: continue
                    if sig['type']=='mega_sell' and sig['is_red']:
                        if code in pf.positions:
                            pf.sell(code,sig['price'],'mega_sell信号',sig['idx'],trade_date)
                        continue
                    if not sig['is_red']:
                        res_type,trigger=check_resonance(sigs,sig['idx'])
                        if res_type and pf.can_buy(code,sig['idx']):
                            tl=stock_data[code]
                            exec_idx=min(sig['idx']+1,len(tl)-1)
                            exec_price=tl[exec_idx]['price']
                            if exec_price<=0: exec_price=sig['price']
                            pf.buy(code,code,exec_price,sig['idx'],trade_date,res_type)

        pf.force_close_all(stock_data,trade_date)
        day_trades=pf.trades[day_trades_before:]

        if day_trades:
            w(f"\n  💰 当日交易记录 ({len(day_trades)}笔):")
            for t in day_trades:
                if t['dir']=='BUY':
                    w(f"    🟢买入 {t['code']:<12} @${t['price']:.3f} ×{t['qty']}  花费${t['cost']:,.2f}  [{t.get('resonance','')}]")
                else:
                    w(f"    🔴卖出 {t['code']:<12} @${t['price']:.3f} ×{t['qty']}  P&L=${t.get('pnl',0):+,.2f}({t.get('pnl_pct',0):+.1f}%)  持仓{t.get('hold_min',0)}分  {t.get('reason','')}")

        day_pnl=pf.cash-day_start
        marker='🟢' if day_pnl>=0 else '🔴'
        w(f"\n  {marker} 日结: P&L=${day_pnl:+,.2f}  余额=${pf.cash:,.2f}")

    w(f"\n{'='*100}")
    w(f"  最终: ${pf.cash:,.2f} (收益${pf.cash-INITIAL_CAPITAL:+,.2f}, {(pf.cash/INITIAL_CAPITAL-1)*100:+.2f}%)")
    w(f"{'='*100}")
    f.close()
    print(f"\n报告已保存到: {OUT_FILE}")

if __name__=='__main__':
    main()
