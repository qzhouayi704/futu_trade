#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""持仓教练卡组装（纯函数）。

把单条持仓 + 当日纪律统计(disc) + 盘口洗盘判定(tape) 组装成一张教练卡：
今日交易计数(churn)、当日成本漂移、盈亏、持有规则建议、洗盘"别割"提示，
churn 时给一句直白的"别来回折腾"。专治盈利持仓上的来回交易。
"""

from typing import Optional

from .trade_discipline import DisciplineThresholds


def build_coach(position: dict, disc: dict,
                thresholds: DisciplineThresholds = None,
                tape: Optional[dict] = None) -> dict:
    th = thresholds or DisciplineThresholds()
    code = position.get("stock_code", "")
    cost = float(position.get("cost_price", 0) or 0)
    cur = float(position.get("nominal_price", 0) or 0)
    qty = float(position.get("qty", 0) or 0)
    # 自算盈亏%（不依赖 pl_ratio 的单位口径），兜底用 position 的 pl_ratio
    if cost > 0 and cur > 0:
        pl_pct = round((cur / cost - 1) * 100, 2)
    else:
        pl_pct = round(float(position.get("pl_ratio", 0) or 0), 2)

    tc = disc.get("trade_count", 0)
    churn = disc.get("churn", False)
    drift = disc.get("cost_drift_pct")
    net_qty = disc.get("net_qty_today", 0.0)
    rt_cash = disc.get("round_trip_cash", 0.0)

    hold_reco = {
        "label": "移动止盈",
        "detail": f"涨超{th.trailing_activate_pct:.0f}%激活、回撤{th.trailing_pullback_pct:.0f}%即卖（别在盈利里来回折腾）",
        "activate_pct": th.trailing_activate_pct,
        "pullback_pct": th.trailing_pullback_pct,
    }

    # 盘口洗盘/出货（用于"别割"提示）
    selloff = None
    if tape and tape.get("available"):
        so = tape.get("selloff") or {}
        if so.get("verdict") in ("shakeout", "distribution"):
            selloff = {"verdict": so["verdict"], "reason": so.get("reason", ""),
                       "position_pct": so.get("position_pct")}

    # churn 时给直白警告
    blunt = ""
    if churn:
        parts = [f"今天已成交{tc}笔"]
        if abs(net_qty) < 1:
            parts.append("净0股(白做)")
            if rt_cash < 0:
                parts.append(f"还亏约{abs(rt_cash):.0f}HKD")
        if drift is not None and drift > 0:
            parts.append(f"加仓均价比成本高+{drift:.1f}%(在把成本买高)")
        blunt = "🔴 别来回折腾：" + "、".join(parts) + \
                f"。坐住，按{th.trailing_activate_pct:.0f}%激活/{th.trailing_pullback_pct:.0f}%回撤的移动止盈走。"

    # 当盈利持仓正被来回交易 → 建议停手持有
    advice = "HOLD" if (churn and pl_pct > 0) else "NEUTRAL"

    return {
        "stock_code": code,
        "stock_name": position.get("stock_name", ""),
        "qty": qty,
        "cost_price": round(cost, 3),
        "current_price": round(cur, 3),
        "pl_ratio_pct": pl_pct,
        "trade_count": tc,
        "buy_count": disc.get("buy_count", 0),
        "sell_count": disc.get("sell_count", 0),
        "net_qty_today": net_qty,
        "round_trip_cash": rt_cash,
        "churn": churn,
        "cost_drift_pct": drift,
        "hold_recommendation": hold_reco,
        "selloff": selloff,
        "blunt": blunt,
        "advice": advice,
    }
