#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交易纪律分析器（纯函数，单一真相源）

读「用户当日真实成交 + 当前持仓」给出纪律判定，用于：
  - 下单前强检查 (pre_trade_check)：intended_side/intended_price 给定时，
    产出可直接并入现有 checks/warnings/score 的 findings。
  - 持仓教练卡 (coach)：intended_side=None 时，只算客观统计供 build_coach 用。

无任何 I/O / 容器依赖；deals 由调用方过滤为「当日 + 该股」后传入。
专治今天 HK.00100 的错：盈利持仓上的强迫性来回交易 / 追涨杀跌 / 把成本买高。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


@dataclass
class DisciplineThresholds:
    # 默认值与系统自动交易护栏 GuardConfig 同源（trade_frequency_guard.py:30-32）
    overtrade_count: int = 4         # 当日同股成交 ≥4 笔 = churn
    overtrade_buys: int = 2          # = GuardConfig.max_same_stock_buys
    reverse_cool_min: int = 15       # = GuardConfig.min_rotation_interval_min（反向冷却）
    min_hold_seconds: int = 300      # = GuardConfig.min_hold_seconds（刚买就卖）
    # 持有规则建议与实时移动止盈引擎同源（RiskCoordinator:78-79）
    trailing_activate_pct: float = 5.0
    trailing_pullback_pct: float = 3.0


def _parse_dt(create_time: str) -> Optional[datetime]:
    """富途 create_time 形如 'YYYY-MM-DD HH:MM:SS.mmm'，解析失败返回 None。"""
    if not create_time or len(str(create_time)) < 19:
        return None
    try:
        return datetime.strptime(str(create_time)[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _is_buy(side) -> bool:
    return str(side).upper() == "BUY"


def _finding(code, name, status, detail, impact, warning=None):
    return {"code": code, "name": name, "status": status,
            "detail": detail, "impact": int(impact), "warning": warning}


def analyze_discipline(
    stock_code: str,
    intended_side: Optional[str],      # 'buy' | 'sell' | None(教练模式)
    intended_price: Optional[float],
    today_deals: List[dict],           # [{trd_side, price, qty, create_time}, ...] 当日+该股
    position: Optional[dict],          # get_positions 的单条；含 qty/cost_price/nominal_price
    thresholds: DisciplineThresholds = None,
    now: Optional[datetime] = None,
) -> dict:
    th = thresholds or DisciplineThresholds()
    now = now or datetime.now()
    is_sell = str(intended_side).lower() == "sell" if intended_side else False
    has_side = intended_side is not None

    out = {"available": False, "trade_count": 0, "buy_count": 0, "sell_count": 0,
           "net_qty_today": 0.0, "round_trip_cash": 0.0,
           "avg_buy_today": None, "avg_sell_today": None,
           "churn": False, "cost_drift_pct": None, "last_deal": None, "findings": []}

    deals = [d for d in (today_deals or []) if d]
    if not deals and not position:
        return out
    out["available"] = True

    # ---- 客观统计 ----
    buys = [d for d in deals if _is_buy(d.get("trd_side"))]
    sells = [d for d in deals if not _is_buy(d.get("trd_side"))]
    out["trade_count"] = len(deals)
    out["buy_count"] = len(buys)
    out["sell_count"] = len(sells)

    def _qp(d):
        return float(d.get("qty", 0) or 0), float(d.get("price", 0) or 0)

    buy_qty = sum(_qp(d)[0] for d in buys)
    sell_qty = sum(_qp(d)[0] for d in sells)
    out["net_qty_today"] = round(buy_qty - sell_qty, 2)
    # 当日来回现金流：卖出收到 − 买入付出（净0股时即来回交易的净盈亏）
    out["round_trip_cash"] = round(
        sum(q * p for q, p in (_qp(d) for d in sells))
        - sum(q * p for q, p in (_qp(d) for d in buys)), 1)
    out["avg_buy_today"] = round(sum(_qp(d)[1] * _qp(d)[0] for d in buys) / buy_qty, 3) if buy_qty > 0 else None
    out["avg_sell_today"] = round(sum(_qp(d)[1] * _qp(d)[0] for d in sells) / sell_qty, 3) if sell_qty > 0 else None

    out["churn"] = out["trade_count"] >= th.overtrade_count or out["buy_count"] >= th.overtrade_buys

    cost_price = float(position.get("cost_price", 0) or 0) if position else 0.0
    nominal = float(position.get("nominal_price", 0) or 0) if position else 0.0
    pl_pct = round((nominal / cost_price - 1) * 100, 2) if cost_price > 0 and nominal > 0 else None
    if out["avg_buy_today"] and cost_price > 0:
        # 今日加仓均价 vs 持仓成本：>0 = 在成本之上加仓（把成本买高）
        out["cost_drift_pct"] = round((out["avg_buy_today"] / cost_price - 1) * 100, 2)

    # 最近一笔成交（按时间）
    timed = [(d, _parse_dt(d.get("create_time", ""))) for d in deals]
    timed_valid = [(d, dt) for d, dt in timed if dt is not None]
    last = max(timed_valid, key=lambda x: x[1]) if timed_valid else None
    if last:
        d, dt = last
        out["last_deal"] = {
            "side": "BUY" if _is_buy(d.get("trd_side")) else "SELL",
            "price": float(d.get("price", 0) or 0),
            "time": dt.strftime("%H:%M"),
            "minutes_ago": int((now - dt).total_seconds() // 60),
        }

    findings = out["findings"]

    # ===== 维度1：过度交易 =====
    tc = out["trade_count"]
    if out["churn"]:
        impact = -25 if not is_sell else -15
        findings.append(_finding(
            "overtrade", "过度交易", "DANGER",
            f"今日已成交{tc}笔(买{out['buy_count']}/卖{out['sell_count']})，典型来回折腾",
            impact, f"🔴 今日已在该股成交{tc}笔，别再追涨杀跌，坐住"))
    elif tc == 3:
        findings.append(_finding(
            "overtrade", "过度交易", "WARNING",
            f"今日已成交{tc}笔，开始频繁", -10 if not is_sell else -6, None))
    else:
        findings.append(_finding(
            "overtrade", "交易频次", "GOOD" if tc <= 1 else "NEUTRAL",
            f"今日成交{tc}笔", 0, None))

    # ===== 维度2/3/4：需要 intended_side（下单前检查）=====
    if has_side:
        last_same_buy = max((d for d in buys), key=lambda d: d.get("create_time", ""), default=None)
        last_same_sell = max((d for d in sells), key=lambda d: d.get("create_time", ""), default=None)

        # 维度2：反向冷却（刚买就卖 / 刚卖就买）
        ld = out["last_deal"]
        if ld and ld["minutes_ago"] is not None and 0 <= ld["minutes_ago"] < th.reverse_cool_min:
            opp = (is_sell and ld["side"] == "BUY") or ((not is_sell) and ld["side"] == "SELL")
            if opp:
                act = "买入" if ld["side"] == "BUY" else "卖出"
                findings.append(_finding(
                    "reverse_cool", "反向冷却", "DANGER",
                    f"{ld['minutes_ago']}分钟前你刚以{ld['price']:.3f}{act}，现在又要反向操作",
                    -20 if not is_sell else -18,
                    f"⚠️ 刚{ld['minutes_ago']}分钟前{act}@{ld['price']:.3f}，现在反手={'追涨杀跌'}，先停一下"))

        # 维度3：追买更贵 / 杀跌更便宜
        if intended_price and intended_price > 0:
            if not is_sell and last_same_buy:
                lb = float(last_same_buy.get("price", 0) or 0)
                if lb > 0 and intended_price > lb:
                    pct = (intended_price / lb - 1) * 100
                    findings.append(_finding(
                        "chase_higher", "追买更贵", "DANGER" if pct >= 1 else "WARNING",
                        f"上一笔买在{lb:.3f}，这次{intended_price:.3f}更贵+{pct:.1f}%（越买越贵）",
                        -min(15, max(5, round(pct * 3))),
                        f"🟡 你在越买越贵：上次{lb:.3f}→这次{intended_price:.3f}(+{pct:.1f}%)"))
            elif is_sell and last_same_sell:
                ls = float(last_same_sell.get("price", 0) or 0)
                if ls > 0 and intended_price < ls:
                    pct = (1 - intended_price / ls) * 100
                    findings.append(_finding(
                        "chase_higher", "杀跌更便宜", "DANGER" if pct >= 1 else "WARNING",
                        f"上一笔卖在{ls:.3f}，这次{intended_price:.3f}便宜了{pct:.1f}%（越卖越低）",
                        -min(15, max(5, round(pct * 3))),
                        f"🟡 你在越卖越低：上次{ls:.3f}→这次{intended_price:.3f}(低{pct:.1f}%)"))

        # 维度4：成本摊薄保护 / 刚买就割
        if position and not is_sell and pl_pct is not None and pl_pct > 0 and cost_price > 0:
            if intended_price and intended_price > cost_price:
                new_cushion = round((nominal / intended_price - 1) * 100, 1) if nominal > 0 else None
                tail = f"，会把盈利垫子从+{pl_pct:.1f}%摊薄到约{new_cushion:+.1f}%" if new_cushion is not None else "，会摊薄你的盈利垫子"
                findings.append(_finding(
                    "cushion_protect", "成本摊薄保护", "DANGER",
                    f"你已盈利+{pl_pct:.1f}%，在成本{cost_price:.3f}之上以{intended_price:.3f}加仓{tail}",
                    -18, f"🔴 别在盈利票上追高加仓：会把+{pl_pct:.1f}%的垫子摊薄"))
            elif intended_price is None:
                findings.append(_finding(
                    "cushion_protect", "成本摊薄保护", "WARNING",
                    f"你已盈利+{pl_pct:.1f}%，加仓买在成本之上会摊薄盈利垫子，别追", -10,
                    f"🟡 已盈利+{pl_pct:.1f}%，加仓追高会摊薄垫子"))
        if position and is_sell and intended_price and intended_price > 0 and last_same_buy:
            bt = _parse_dt(last_same_buy.get("create_time", ""))
            bp = float(last_same_buy.get("price", 0) or 0)
            if bt and 0 <= (now - bt).total_seconds() < th.min_hold_seconds and bp > 0 and intended_price < bp:
                secs = int((now - bt).total_seconds())
                findings.append(_finding(
                    "panic_cut", "刚买就割", "DANGER",
                    f"{secs}秒前才以{bp:.3f}买入，现在{intended_price:.3f}割肉，没到最小持仓{th.min_hold_seconds}秒",
                    -15, f"🔴 {secs}秒前才买@{bp:.3f}，现在亏卖={'追涨杀跌'}，先停一下"))

    out["pl_pct"] = pl_pct
    return out
