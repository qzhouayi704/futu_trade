#!/usr/bin/env python3
"""分析富途API获取的真实交易记录"""
import json
from collections import defaultdict
from datetime import datetime

IN_PATH = "scripts/futu_real_trades.json"
OUT_PATH = "scripts/real_trade_analysis.json"

with open(IN_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

result = {}

# 1. 账户概况
acct = data.get("account_info", [{}])[0]
result["account_summary"] = {
    "total_assets_hkd": acct.get("total_assets", 0),
    "cash_hkd": acct.get("cash", 0),
    "market_value": acct.get("market_val", 0),
    "buying_power": acct.get("power", 0),
    "risk_status": acct.get("risk_status", ""),
}

# 2. 当前持仓分析
positions = data.get("positions", [])
active_positions = [p for p in positions if p.get("qty", 0) > 0]
result["active_positions"] = [{
    "code": p["code"],
    "name": p["stock_name"],
    "qty": p["qty"],
    "cost_price": p["cost_price"],
    "market_val": p["market_val"],
    "pl_val": p["pl_val"],
    "pl_ratio": p["pl_ratio"],
    "today_pl": p["today_pl_val"],
} for p in active_positions]

# 已清仓的今日交易盈亏
cleared_today = [p for p in positions if p.get("qty", 0) == 0 and p.get("today_trd_val", 0) > 0]
result["cleared_today_pnl"] = [{
    "code": p["code"],
    "name": p["stock_name"],
    "realized_pl": p["realized_pl"],
    "today_pl": p["today_pl_val"],
    "today_buy_qty": p["today_buy_qty"],
    "today_sell_qty": p["today_sell_qty"],
    "avg_cost": p["average_cost"],
} for p in cleared_today]

# 3. 今日成交统计
today_deals = data.get("today_deals", [])
result["today_deals_count"] = len(today_deals)

# 按股票分组统计今日交易
today_by_stock = defaultdict(lambda: {"buys": [], "sells": [], "stock_name": ""})
for d in today_deals:
    code = d["code"]
    today_by_stock[code]["stock_name"] = d["stock_name"]
    entry = {"qty": d["qty"], "price": d["price"], "time": d["create_time"]}
    if d["trd_side"] == "BUY":
        today_by_stock[code]["buys"].append(entry)
    else:
        today_by_stock[code]["sells"].append(entry)

today_stock_summary = []
for code, trades in today_by_stock.items():
    buy_qty = sum(b["qty"] for b in trades["buys"])
    sell_qty = sum(s["qty"] for s in trades["sells"])
    buy_avg = sum(b["qty"]*b["price"] for b in trades["buys"]) / buy_qty if buy_qty > 0 else 0
    sell_avg = sum(s["qty"]*s["price"] for s in trades["sells"]) / sell_qty if sell_qty > 0 else 0
    
    min_qty = min(buy_qty, sell_qty)
    pnl = (sell_avg - buy_avg) * min_qty if min_qty > 0 and buy_avg > 0 else 0
    
    today_stock_summary.append({
        "code": code,
        "name": trades["stock_name"],
        "buy_count": len(trades["buys"]),
        "sell_count": len(trades["sells"]),
        "buy_qty": buy_qty,
        "sell_qty": sell_qty,
        "buy_avg": round(buy_avg, 3),
        "sell_avg": round(sell_avg, 3),
        "estimated_pnl": round(pnl, 0),
        "net_qty": buy_qty - sell_qty,
    })
result["today_stock_summary"] = sorted(today_stock_summary, key=lambda x: abs(x["estimated_pnl"]), reverse=True)

# 4. 历史成交分析（90天）
history_deals = data.get("history_deals", [])
result["history_deals_count"] = len(history_deals)

# 按日期统计交易频率
daily_stats = defaultdict(lambda: {"count": 0, "buy_count": 0, "sell_count": 0, "stocks": set(), "volume": 0})
for d in history_deals:
    date_str = d.get("create_time", "")[:10]
    daily_stats[date_str]["count"] += 1
    daily_stats[date_str]["volume"] += d.get("qty", 0) * d.get("price", 0)
    daily_stats[date_str]["stocks"].add(d.get("code", ""))
    if d.get("trd_side") == "BUY":
        daily_stats[date_str]["buy_count"] += 1
    else:
        daily_stats[date_str]["sell_count"] += 1

daily_list = []
for date_str, stats in sorted(daily_stats.items(), reverse=True):
    daily_list.append({
        "date": date_str,
        "total_deals": stats["count"],
        "buy_deals": stats["buy_count"],
        "sell_deals": stats["sell_count"],
        "unique_stocks": len(stats["stocks"]),
        "total_volume_hkd": round(stats["volume"], 0),
    })
result["daily_trade_stats"] = daily_list

# 5. 按股票统计历史交易频率和盈亏
stock_history = defaultdict(lambda: {"name": "", "buys": [], "sells": [], "deal_count": 0})
for d in history_deals:
    code = d.get("code", "")
    stock_history[code]["name"] = d.get("stock_name", "")
    stock_history[code]["deal_count"] += 1
    entry = {"qty": d.get("qty", 0), "price": d.get("price", 0), "time": d.get("create_time", "")}
    if d.get("trd_side") == "BUY":
        stock_history[code]["buys"].append(entry)
    else:
        stock_history[code]["sells"].append(entry)

stock_summary = []
for code, hist in stock_history.items():
    buy_qty = sum(b["qty"] for b in hist["buys"])
    sell_qty = sum(s["qty"] for s in hist["sells"])
    buy_val = sum(b["qty"]*b["price"] for b in hist["buys"])
    sell_val = sum(s["qty"]*s["price"] for s in hist["sells"])
    buy_avg = buy_val / buy_qty if buy_qty > 0 else 0
    sell_avg = sell_val / sell_qty if sell_qty > 0 else 0
    
    stock_summary.append({
        "code": code,
        "name": hist["name"],
        "deal_count": hist["deal_count"],
        "buy_count": len(hist["buys"]),
        "sell_count": len(hist["sells"]),
        "buy_total_qty": buy_qty,
        "sell_total_qty": sell_qty,
        "buy_avg_price": round(buy_avg, 3),
        "sell_avg_price": round(sell_avg, 3),
        "buy_total_val": round(buy_val, 0),
        "sell_total_val": round(sell_val, 0),
        "net_qty": buy_qty - sell_qty,
        "realized_pnl_estimate": round(sell_val - buy_val, 0) if sell_qty >= buy_qty else "holding",
    })
result["stock_history_summary"] = sorted(stock_summary, key=lambda x: x["deal_count"], reverse=True)

# 6. 总体统计
total_buy_val = sum(s["buy_total_val"] for s in stock_summary)
total_sell_val = sum(s["sell_total_val"] for s in stock_summary)
result["overall_stats"] = {
    "total_deals_90d": len(history_deals),
    "total_buy_value": round(total_buy_val, 0),
    "total_sell_value": round(total_sell_val, 0),
    "trading_days": len(daily_list),
    "avg_deals_per_day": round(len(history_deals) / max(len(daily_list), 1), 1),
    "unique_stocks_traded": len(stock_summary),
}

with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2, default=str)

print(f"分析完成: {OUT_PATH}")
print(f"\n=== 账户概况 ===")
print(f"  总资产: HK${result['account_summary']['total_assets_hkd']:,.0f}")
print(f"  持仓市值: HK${result['account_summary']['market_value']:,.0f}")
print(f"  可用现金: HK${result['account_summary']['cash_hkd']:,.0f}")

print(f"\n=== 90天交易统计 ===")
print(f"  总成交: {result['overall_stats']['total_deals_90d']} 笔")
print(f"  交易天数: {result['overall_stats']['trading_days']} 天")
print(f"  日均成交: {result['overall_stats']['avg_deals_per_day']} 笔")
print(f"  涉及股票: {result['overall_stats']['unique_stocks_traded']} 只")
print(f"  总买入金额: HK${result['overall_stats']['total_buy_value']:,.0f}")
print(f"  总卖出金额: HK${result['overall_stats']['total_sell_value']:,.0f}")

print(f"\n=== 今日交易 ===")
print(f"  成交: {result['today_deals_count']} 笔")
for s in result["today_stock_summary"]:
    print(f"  {s['code']} {s['name']}: 买{s['buy_count']}次/卖{s['sell_count']}次, 预估盈亏: HK${s['estimated_pnl']:.0f}")

print(f"\n=== 交易最频繁的股票 (Top 10) ===")
for s in result["stock_history_summary"][:10]:
    print(f"  {s['code']} {s['name']}: {s['deal_count']}次交易, "
          f"买{s['buy_count']}次/卖{s['sell_count']}次, 净持仓:{s['net_qty']}")
