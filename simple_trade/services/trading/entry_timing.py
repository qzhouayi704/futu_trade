#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""入场择时（实验·只读）——强势股低吸择时绿灯

数据来源（2026-06 生产逐笔回测，见记忆 buy-timing-meanrev-2026-06）：
- 在"近几日强势股"子集上，买"刚回调"(近5min为负) 后30min 市场相对收益 +0.30%/命中56%、
  到60min +0.37%、4/4 天为正；而追"刚冲高"命中仅 46%、半数日为负，靠极少数强趋势日肥尾。
- 故最准的买入信号是**择时过滤器**（何时点买），不是选股器：
  🟢 强势股 + 刚回调 + 回到日内中下位 + 主动买盘未过热 → 较优低吸点
  🔴 强势股 + 刚冲高 + (单流过热 或 贴近日内高) → 别追（易买在局部顶）

**纯展示、绝不参与下单/评分/门控**。阈值取自回测分位，可调。
"""

import logging
import time as _time
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger("entry_timing")


@dataclass(frozen=True)
class EntryTimingThresholds:
    sessions: int = 3            # 近 N 个交易日累计涨幅
    pool_top_pct: float = 0.20   # 强势股池：当日活跃股按涨幅取前 X%
    pool_min_gain: float = 0.05  # 且累计涨幅至少 +5%
    pool_max_n: int = 40         # 池上限
    dip_mom: float = -0.003      # mom5 <= -0.3% 视为"刚回调"
    spike_mom: float = 0.003     # mom5 >= +0.3% 视为"刚冲高"
    ofi_hot: float = 0.30        # 近15min 主动买卖单流 >= 0.30 视为"过热"
    pos_low: float = 0.50        # 日内价位 <= 0.5 视为中下位
    pos_high: float = 0.70       # 日内价位 >= 0.7 视为贴近日内高
    pos_strong_low: float = 0.34 # 回到日内低位（更优低吸）
    stale_seconds: int = 300     # 最近一笔逐笔超过 5 分钟视为陈旧/休市


def judge_entry_timing(mom5: Optional[float], ofi15: Optional[float],
                       pos_range: Optional[float],
                       th: EntryTimingThresholds = EntryTimingThresholds()
                       ) -> Tuple[str, str, str]:
    """纯函数：给出 (light, label, reason)。light ∈ {green, red, neutral}。

    仅用三个只往回看的逐笔特征，不引入任何外部状态——便于单测与复跑。
    """
    if mom5 is None or pos_range is None:
        return ("neutral", "数据不足", "缺少近5分钟动量或日内价位")
    pct = lambda x: ("%+.1f%%" % (x * 100))
    # 🔴 追高：刚冲 + (单流过热 或 贴近日内高)
    if mom5 >= th.spike_mom and ((ofi15 is not None and ofi15 >= th.ofi_hot)
                                 or pos_range >= th.pos_high):
        why = ["刚冲高(5m %s)" % pct(mom5)]
        if ofi15 is not None and ofi15 >= th.ofi_hot:
            why.append("主动买盘过热")
        if pos_range >= th.pos_high:
            why.append("贴近日内高")
        return ("red", "别追", "、".join(why) + "：回测此处命中最低，易买在局部顶")
    # 🟢 低吸：刚回调 + 日内中下位 + 单流未过热
    if (mom5 <= th.dip_mom and pos_range <= th.pos_low
            and (ofi15 is None or ofi15 < th.ofi_hot)):
        strong = pos_range <= th.pos_strong_low
        why = ["刚回调(5m %s)" % pct(mom5),
               "回到日内低位" if strong else "日内中下位"]
        if ofi15 is not None:
            why.append("单流未过热")
        label = "可低吸(较优)" if strong else "可低吸"
        return ("green", label, "、".join(why) + "：回测此处胜率/前向收益最高")
    return ("neutral", "观望", "非明确低吸/追高区间")


class EntryTimingService:
    """只读：从日线建强势股池 + 读近 15min 逐笔算择时绿灯。不持有任何下单能力。"""

    def __init__(self, db_manager, thresholds: Optional[EntryTimingThresholds] = None):
        self.db = db_manager
        self.th = thresholds or EntryTimingThresholds()

    def _hk_today(self) -> str:
        from ...utils.market_helper import MarketTimeHelper
        return MarketTimeHelper.get_market_today('HK')

    def _market_open(self) -> bool:
        try:
            from ...utils.market_helper import MarketTimeHelper
            return MarketTimeHelper.is_any_market_trading()
        except Exception:
            return False

    def strong_pool(self, trade_date: str) -> List[Tuple[str, float]]:
        """当日有逐笔的活跃股中，近 N 日累计涨幅靠前者。返回 [(code, gain), ...] 按涨幅降序。"""
        th = self.th
        active = self.db.execute_query(
            "SELECT DISTINCT stock_code FROM ticker_data WHERE trade_date=?",
            (trade_date,)) or []
        codes = [r[0] for r in active]
        if not codes:
            return []
        ph = ",".join("?" for _ in codes)
        rows = self.db.execute_query(
            f"SELECT stock_code, substr(time_key,1,10) d, close_price FROM kline_data "
            f"WHERE stock_code IN ({ph}) AND substr(time_key,1,10) < ? AND close_price>0 "
            f"ORDER BY stock_code, time_key",
            (*codes, trade_date)) or []
        series: dict = {}
        for code, _d, cl in rows:
            series.setdefault(code, []).append(float(cl))
        gains = []
        for code, cl in series.items():
            if len(cl) >= th.sessions + 1:
                base = cl[-1 - th.sessions]
                if base > 0:
                    gains.append((code, cl[-1] / base - 1))
        if not gains:
            return []
        gains.sort(key=lambda x: -x[1])
        cut = th.pool_min_gain
        if len(gains) > 5:
            cut = max(cut, gains[int(th.pool_top_pct * len(gains))][1])
        pool = [(c, g) for c, g in gains if g >= cut][:th.pool_max_n]
        return pool

    def _names(self, codes: List[str]) -> dict:
        if not codes:
            return {}
        ph = ",".join("?" for _ in codes)
        rows = self.db.execute_query(
            f"SELECT code, name FROM stocks WHERE code IN ({ph})", tuple(codes)) or []
        return {r[0]: r[1] for r in rows}

    def _features(self, ticks: list, day_minmax: Optional[Tuple[float, float]],
                  now_ms: int) -> dict:
        """ticks: 近窗口内 [(code,ts,price,turnover,direction), ...] 按时间升序。"""
        if not ticks:
            return {"mom5": None, "ofi15": None, "pos_range": None,
                    "last": None, "last_ts": None, "stale": True}
        last_price = float(ticks[-1][2]); last_ts = int(ticks[-1][1])
        cutoff = now_ms - 5 * 60000
        p5 = None
        for t in ticks:
            if int(t[1]) <= cutoff:
                p5 = float(t[2])
        mom5 = (last_price / p5 - 1) if (p5 and p5 > 0) else None
        buy = sum(float(t[3] or 0) for t in ticks if t[4] == "BUY")
        sell = sum(float(t[3] or 0) for t in ticks if t[4] == "SELL")
        ofi = ((buy - sell) / (buy + sell)) if (buy + sell) > 0 else None
        pr = None
        if day_minmax:
            lo, hi = day_minmax
            if hi > lo:
                pr = (last_price - lo) / (hi - lo)
        stale = (now_ms - last_ts) > self.th.stale_seconds * 1000
        return {"mom5": mom5, "ofi15": ofi, "pos_range": pr,
                "last": last_price, "last_ts": last_ts, "stale": stale}

    def watch(self) -> dict:
        """主入口：返回强势股池 + 每只的入场择时绿灯。"""
        D = self._hk_today()
        market_open = self._market_open()
        pool = self.strong_pool(D)
        if not pool:
            return {"as_of": D, "market_open": market_open, "pool_size": 0,
                    "items": [], "experimental": True}
        codes = [c for c, _ in pool]
        names = self._names(codes)
        ph = ",".join("?" for _ in codes)
        now_ms = int(_time.time() * 1000)
        since = now_ms - 16 * 60000
        trows = self.db.execute_query(
            f"SELECT stock_code,timestamp,price,turnover,direction FROM ticker_data "
            f"WHERE trade_date=? AND stock_code IN ({ph}) AND timestamp>=? "
            f"ORDER BY stock_code,timestamp",
            (D, *codes, since)) or []
        drows = self.db.execute_query(
            f"SELECT stock_code,MIN(price),MAX(price) FROM ticker_data "
            f"WHERE trade_date=? AND stock_code IN ({ph}) AND price>0 GROUP BY stock_code",
            (D, *codes)) or []
        dmm = {r[0]: (float(r[1]), float(r[2])) for r in drows}
        byc: dict = {}
        for r in trows:
            byc.setdefault(r[0], []).append(r)
        items = []
        for code, gain in pool:
            feat = self._features(byc.get(code, []), dmm.get(code), now_ms)
            if feat["stale"]:
                light, label, reason = ("neutral", "无最新逐笔", "休市或该股暂无近5分钟成交")
            else:
                light, label, reason = judge_entry_timing(
                    feat["mom5"], feat["ofi15"], feat["pos_range"], self.th)
            items.append({
                "stock_code": code,
                "stock_name": names.get(code, code),
                "gain_3d": round(gain * 100, 2),
                "light": light,
                "label": label,
                "reason": reason,
                "mom5": round(feat["mom5"] * 100, 2) if feat["mom5"] is not None else None,
                "ofi15": round(feat["ofi15"], 2) if feat["ofi15"] is not None else None,
                "pos_range": round(feat["pos_range"], 2) if feat["pos_range"] is not None else None,
                "last_price": feat["last"],
                "stale": feat["stale"],
            })
        order = {"green": 0, "red": 1, "neutral": 2}
        items.sort(key=lambda x: (order.get(x["light"], 3), -x["gain_3d"]))
        return {"as_of": D, "market_open": market_open, "pool_size": len(pool),
                "items": items, "experimental": True}
