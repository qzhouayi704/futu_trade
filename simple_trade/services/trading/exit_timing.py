#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离场择时（实验·只读）——持仓股开盘检查

对照 entry_timing(入场择时绿灯)，这里给**持仓**一张开盘判读：每只持仓在 09:30 用
第一笔报价就能算的特征(低开/跌破昨收/高开低走/破开盘均价) + 盘前预设的离场计划 + 当日
regime，给出 red/amber/green 一句话。专治"开盘想卖却干等信号"。

**纯展示/告警·绝不下单·绝不门控·绝不预测**。regime 复用 EntryTimingService.market_regime。
"""

import logging
from typing import List, Optional

from .open_check import (
    OpenCheckThresholds,
    compute_open_features,
    judge_open_risk,
)

logger = logging.getLogger("exit_timing")


class ExitTimingService:
    """只读：对持仓股做开盘即时风险判读。不持有任何下单能力。"""

    def __init__(self, db_manager, thresholds: Optional[OpenCheckThresholds] = None):
        self.db = db_manager
        self.th = thresholds or OpenCheckThresholds()
        self._entry = None
        self._regime_cache: dict = {}

    def _hk_today(self) -> str:
        from ...utils.market_helper import MarketTimeHelper
        return MarketTimeHelper.get_market_today('HK')

    def market_regime(self, trade_date: Optional[str] = None) -> Optional[dict]:
        """复用入场择时的当日 regime(全活跃股涨幅 中位/均值/宽度)。失败 → None。

        按日缓存(同实例内)；regime 在盘中会演化，跨实例不缓存以保证新鲜。
        """
        D = trade_date or self._hk_today()
        if D in self._regime_cache:
            return self._regime_cache[D]
        r = None
        try:
            if self._entry is None:
                from .entry_timing import EntryTimingService
                self._entry = EntryTimingService(self.db)
            r = self._entry.market_regime(D)
        except Exception as e:
            logger.debug("exit_timing regime 失败: %s", e)
        self._regime_cache[D] = r
        return r

    def open_check(self, positions: List[dict], quotes_by_code: dict,
                   plans_by_code: Optional[dict] = None,
                   secs_since_open: Optional[int] = None,
                   regime: Optional[dict] = None) -> dict:
        """逐持仓算开盘判读。

        positions: 富途持仓字典列表(需含 stock_code/cost_price/nominal_price/stock_name)。
        quotes_by_code: {code: {prev_close, open_price, last_price, ...}}。
        plans_by_code: {code: 预设离场计划}；regime: 传入则用于收紧 amber 措辞(None=跳过)。
        返回 {as_of, regime, items:[...], experimental:True}，items 已按 red→amber→green 排序。
        """
        plans_by_code = plans_by_code or {}
        D = self._hk_today()
        items = []
        for pos in positions:
            code = pos.get("stock_code", "")
            if not code:
                continue
            q = quotes_by_code.get(code) or {}
            feat = compute_open_features(
                q.get("prev_close"), q.get("open_price"), q.get("last_price"),
                secs_since_open=secs_since_open)
            cost = float(pos.get("cost_price", 0) or 0)
            cur = float(pos.get("nominal_price", 0) or 0)
            if cur <= 0 and feat.get("last"):
                cur = float(feat["last"])
            pl_pct = round((cur / cost - 1) * 100, 2) if (cost > 0 and cur > 0) else None
            plan = plans_by_code.get(code)
            light, label, reason = judge_open_risk(
                feat, pl_pct, plan, regime, self.th, secs_since_open)
            items.append({
                "stock_code": code,
                "stock_name": pos.get("stock_name", code),
                "light": light,
                "label": label,
                "reason": reason,
                "gap_pct": round(feat["gap_pct"] * 100, 2) if feat.get("gap_pct") is not None else None,
                "fade_pct": round(feat["fade_pct"] * 100, 2) if feat.get("fade_pct") is not None else None,
                "intraday_chg": round(feat["intraday_chg"] * 100, 2) if feat.get("intraday_chg") is not None else None,
                "pl_pct": pl_pct,
                "has_plan": plan is not None,
                "plan_action": (plan or {}).get("planned_action"),
                "last_price": feat.get("last"),
            })
        order = {"red": 0, "amber": 1, "green": 2}
        items.sort(key=lambda x: order.get(x["light"], 3))
        return {"as_of": D, "regime": regime, "items": items, "experimental": True}
