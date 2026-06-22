#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""入场择时（实验·只读）——强势股低吸择时绿灯

数据来源（2026-06 生产逐笔回测，见记忆 buy-timing-meanrev / signal-eval-canonical）：
- 股池 = **当日强势股**（今日已涨，现价/前收-1 靠前）——用户真正盯/交易的票。
- 边际**依行情(regime)而变**：涨/平盘买"刚回调"(日内低位)放大收益、跌市需日线健康过滤避死猫跳。
  单一被框定数字(某池/某窗/某几日的 +0.30%/56% 等)**不可比**；以唯一口径评估器
  canonical_signal_eval 的分行情结果为准（现样本仅 1 涨 3 跌日=方向性，待每周重跑累积）。
- 故最准的买入信号是**择时过滤器**（何时点买），不是选股器：
  🟢 当日强势 + 刚回调 + 回到日内中下位 + 主动买盘未过热 → 较优低吸点
  🔴 当日强势 + 刚冲高 + (单流过热 或 贴近日内高) → 别追（易买在局部顶）

**纯展示、绝不参与下单/评分/门控**。阈值取自回测分位，可调。
"""

import logging
import time as _time
from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import List, Optional, Tuple

logger = logging.getLogger("entry_timing")


@dataclass(frozen=True)
class EntryTimingThresholds:
    today_min_gain: float = 0.03 # 当日强势：今日涨幅(现价/前收-1) 至少 +3%
    pool_top_pct: float = 0.20   # 或取当日涨幅前 X%（两者取更高门槛）
    pool_max_n: int = 40         # 池上限
    dip_mom: float = -0.003      # mom5 <= -0.3% 视为"刚回调"
    spike_mom: float = 0.003     # mom5 >= +0.3% 视为"刚冲高"
    ofi_hot: float = 0.30        # 近15min 主动买卖单流 >= 0.30 视为"过热"
    pos_low: float = 0.50        # 日内价位 <= 0.5 视为中下位
    pos_high: float = 0.70       # 日内价位 >= 0.7 视为贴近日内高
    pos_strong_low: float = 0.34 # 回到日内低位（更优低吸）
    stale_seconds: int = 300     # 最近一笔逐笔超过 5 分钟视为陈旧/休市
    min_live_pool: int = 8       # 当日强势股不足此数（开盘空窗）时，用昨日强势 top20 兜底观察池


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

    def _all_gains(self, trade_date: str) -> List[Tuple[str, float]]:
        """当日全市场活跃股涨幅 [(code, gain)] 降序，gain=现价/前收-1。带本实例缓存(一次请求内复用)。"""
        if getattr(self, "_gains_td", None) == trade_date and hasattr(self, "_gains"):
            return self._gains
        rows = self.db.execute_query(
            "SELECT t.stock_code, t.price FROM ticker_data t "
            "JOIN (SELECT stock_code, MAX(timestamp) mx FROM ticker_data "
            "      WHERE trade_date=? AND price>0 GROUP BY stock_code) m "
            "  ON t.stock_code=m.stock_code AND t.timestamp=m.mx "
            "WHERE t.trade_date=?",
            (trade_date, trade_date)) or []
        last = {r[0]: float(r[1]) for r in rows}
        gains: List[Tuple[str, float]] = []
        if last:
            codes = list(last.keys())
            ph = ",".join("?" for _ in codes)
            krows = self.db.execute_query(
                f"SELECT stock_code, close_price FROM kline_data "
                f"WHERE stock_code IN ({ph}) AND substr(time_key,1,10) < ? AND close_price>0 "
                f"ORDER BY stock_code, time_key",
                (*codes, trade_date)) or []
            prevc: dict = {}
            for code, cl in krows:
                prevc[code] = float(cl)  # 升序遍历，最后一条即今日前最近收盘
            for code, lp in last.items():
                pc = prevc.get(code)
                if pc and pc > 0:
                    gains.append((code, lp / pc - 1))
            gains.sort(key=lambda x: -x[1])
        self._gains_td = trade_date
        self._gains = gains
        return gains

    def strong_pool(self, trade_date: str) -> List[Tuple[str, float]]:
        """当日强势股：今日已涨(现价/前收-1)靠前的活跃股。返回 [(code, today_gain), ...] 降序。"""
        th = self.th
        gains = self._all_gains(trade_date)
        if not gains:
            return []
        cut = th.today_min_gain
        if len(gains) > 5:
            cut = max(cut, gains[int(th.pool_top_pct * len(gains))][1])
        return [(c, g) for c, g in gains if g >= cut][:th.pool_max_n]

    def _prev_strong_codes(self, n: int = 20) -> List[str]:
        """昨日(最近一个交易日)涨幅强势 top-n（close/前收-1 ≥ today_min_gain）。

        用 kline_data 现算（长期保留、**不受 enricher 盘中覆盖 strong_codes 影响**），
        供开盘空窗兜底观察池——昨日妖股今日重点盯。fail-safe 返回 []。
        """
        try:
            D = self._hk_today()
            # 昨日强势全天恒定 → 按当日缓存，避免每 15s 轮询重查 kline
            if getattr(self, "_prevstrong_td", None) == D and hasattr(self, "_prevstrong"):
                return self._prevstrong[:n]
            ds = self.db.execute_query(
                "SELECT DISTINCT substr(time_key,1,10) d FROM kline_data "
                "WHERE substr(time_key,1,10) < ? ORDER BY d DESC LIMIT 2", (D,)) or []
            codes: List[str] = []
            if len(ds) >= 2:
                prev_d, prev_d2 = ds[0][0], ds[1][0]
                r1 = self.db.execute_query(
                    "SELECT stock_code, close_price FROM kline_data "
                    "WHERE substr(time_key,1,10)=? AND close_price>0", (prev_d,)) or []
                r0 = self.db.execute_query(
                    "SELECT stock_code, close_price FROM kline_data "
                    "WHERE substr(time_key,1,10)=? AND close_price>0", (prev_d2,)) or []
                c0 = {code: float(cl) for code, cl in r0}
                gains = []
                for code, cl in r1:
                    p = c0.get(code)
                    if p and p > 0:
                        gains.append((code, float(cl) / p - 1))
                gains.sort(key=lambda x: -x[1])
                codes = [c for c, g in gains if g >= self.th.today_min_gain][:40]
            self._prevstrong_td = D
            self._prevstrong = codes
            return codes[:n]
        except Exception as e:
            logger.debug("prev_strong_codes 失败: %s", e)
            return []

    def market_regime(self, trade_date: str) -> dict:
        """当日市场行情(全活跃股涨幅中位) → up/flat/down + 今日打法(纯展示·只读·不下单)。

        依据 2026-06 多日回测: 涨/平盘买'日内低位'放大收益(让利润奔跑);跌市只碰'日线健康'
        (MA20上方/真趋势)避弱势死猫跳。阈值 ±0.5% 与回测一致。
        """
        vals = [g for _, g in self._all_gains(trade_date)]
        if len(vals) < 10:
            return {"regime": "unknown", "median_pct": None,
                    "playbook": "", "hint": "活跃股数据不足"}
        med = median(vals)
        if med >= 0.005:
            regime = "up"; hint = "进攻日"
            pb = "买日内低位(低吸)、让利润奔跑、别急移动止盈"
        elif med <= -0.005:
            regime = "down"; hint = "防守日"
            pb = "只碰日线健康(MA20上方/真趋势)的强势股、避开弱势'死猫跳'"
        else:
            regime = "flat"; hint = "中性日"
            pb = "可低吸但克制、跟紧大盘"
        return {"regime": regime, "median_pct": round(med * 100, 2),
                "hint": hint, "playbook": pb}

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
        regime = self.market_regime(D)
        pool = self.strong_pool(D)
        # 开盘空窗兜底：当日强势股还没形成(开盘早期)时，补昨日强势 top20 作观察池
        from_prev: set = set()
        if market_open and len(pool) < self.th.min_live_pool:
            have = {c for c, _ in pool}
            gmap = dict(self._all_gains(D))
            for c in self._prev_strong_codes():
                if c not in have:
                    pool.append((c, gmap.get(c, 0.0)))  # gain=今日实时涨幅(可能<3%甚至负)
                    from_prev.add(c)
                    have.add(c)
        if not pool:
            return {"as_of": D, "market_open": market_open, "pool_size": 0,
                    "items": [], "regime": regime, "experimental": True}
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
                "gain_today": round(gain * 100, 2),
                "light": light,
                "label": label,
                "reason": reason,
                "mom5": round(feat["mom5"] * 100, 2) if feat["mom5"] is not None else None,
                "ofi15": round(feat["ofi15"], 2) if feat["ofi15"] is not None else None,
                "pos_range": round(feat["pos_range"], 2) if feat["pos_range"] is not None else None,
                "last_price": feat["last"],
                "stale": feat["stale"],
                "from_prev": code in from_prev,  # True=昨日强势兜底(开盘空窗观察池)，非当日强势
            })
        order = {"green": 0, "red": 1, "neutral": 2}
        items.sort(key=lambda x: (order.get(x["light"], 3), x["from_prev"], -x["gain_today"]))
        return {"as_of": D, "market_open": market_open, "pool_size": len(pool),
                "items": items, "regime": regime, "experimental": True}

    # ==================== 持久化 + 历史（供"全部信号"回查 / 复盘真实命中率）====================

    RECORD_COOLDOWN_MIN = 15   # 同股同灯 15min 内不重复落库

    def _ensure_table(self):
        """建表（幂等）。trade_date+time 为 HK 口径；落 🟢/🔴 的触发快照。"""
        self.db.execute_update("""
            CREATE TABLE IF NOT EXISTS entry_timing_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date TEXT NOT NULL,
                time TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                stock_name TEXT,
                light TEXT NOT NULL,
                label TEXT,
                reason TEXT,
                last_price REAL,
                gain_today REAL,
                mom5 REAL,
                ofi15 REAL,
                pos_range REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.db.execute_update(
            "CREATE INDEX IF NOT EXISTS idx_ets_date_code_light "
            "ON entry_timing_signals(trade_date, stock_code, light)"
        )

    @staticmethod
    def _min_gap(t1: str, t2: str) -> int:
        """两个 HH:MM 的分钟差（t2-t1）。"""
        try:
            return (int(t2[:2]) * 60 + int(t2[3:5])) - (int(t1[:2]) * 60 + int(t1[3:5]))
        except Exception:
            return 999

    @staticmethod
    def _add_min(hhmm: str, mins: int) -> str:
        total = int(hhmm[:2]) * 60 + int(hhmm[3:5]) + mins
        total = max(0, min(total, 23 * 60 + 59))
        return f"{total // 60:02d}:{total % 60:02d}"

    def record(self, result: Optional[dict] = None) -> int:
        """把 watch() 里的 🟢/🔴 触发落库（同股同灯 15min 内去重）。返回新写入条数。

        失败绝不抛出（实验功能不能影响主流程）。result 为空时自行 watch()。
        """
        try:
            result = result or self.watch()
            items = [it for it in result.get("items", [])
                     if it.get("light") in ("green", "red") and not it.get("stale")]
            if not items:
                return 0
            self._ensure_table()
            D = result.get("as_of") or self._hk_today()
            now_hm = datetime.now().strftime("%H:%M")  # 服务器=CST=HK
            written = 0
            for it in items:
                code, light = it.get("stock_code"), it.get("light")
                if not code:
                    continue
                last = self.db.execute_query(
                    "SELECT time FROM entry_timing_signals "
                    "WHERE trade_date=? AND stock_code=? AND light=? ORDER BY id DESC LIMIT 1",
                    (D, code, light))
                if last and last[0][0] and self._min_gap(last[0][0], now_hm) < self.RECORD_COOLDOWN_MIN:
                    continue
                self.db.execute_insert(
                    "INSERT INTO entry_timing_signals "
                    "(trade_date, time, stock_code, stock_name, light, label, reason, "
                    " last_price, gain_today, mom5, ofi15, pos_range) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (D, now_hm, code, it.get("stock_name"), light, it.get("label"),
                     it.get("reason"), it.get("last_price"), it.get("gain_today"),
                     it.get("mom5"), it.get("ofi15"), it.get("pos_range")))
                written += 1
            if written:
                logger.info("入场择时已落库 %d 条 (%s)", written, D)
            return written
        except Exception as e:  # noqa: BLE001
            logger.debug("入场择时落库失败: %s", e)
            return 0

    def _minute_prices(self, code: str, D: str) -> dict:
        """该股当日分钟均价 {HH:MM: price}（算触发后的事后涨跌）。"""
        rows = self.db.execute_query(
            "SELECT substr(datetime(timestamp/1000,'unixepoch','+8 hours'),12,5) m, AVG(price) ap "
            "FROM ticker_data WHERE stock_code=? AND trade_date=? AND price>0 GROUP BY m",
            (code, D)) or []
        return {m: float(p) for m, p in rows if p and float(p) > 0}

    def _outcome(self, code: str, D: str, t0: str, trig: Optional[float]) -> dict:
        """触发后的事后走势：+30min / 收盘(或至今) / 触发后最高最低 相对触发价的%。"""
        if not trig or trig <= 0:
            return {}
        mp = self._minute_prices(code, D)
        if not mp:
            return {}
        after = {m: p for m, p in mp.items() if m > t0}
        pct = lambda p: round((p / trig - 1) * 100, 2) if p else None

        def at_after(mins: int):
            base = self._add_min(t0, mins)
            cand = sorted(m for m in mp if m >= base)
            return mp[cand[0]] if cand else None

        last_p = mp[max(mp)]
        return {
            "ret_30m": pct(at_after(30)),
            "ret_last": pct(last_p),       # 至今/收盘
            "max_up": pct(max(after.values())) if after else 0.0,
            "max_dn": pct(min(after.values())) if after else 0.0,
            "last_price": round(last_p, 3),
        }

    def history(self, trade_date: Optional[str] = None) -> dict:
        """某日全部入场择时 🟢/🔴 信号 + 每条的事后走势（供复盘/真实命中率）。"""
        D = trade_date or self._hk_today()
        self._ensure_table()
        rows = self.db.execute_query(
            "SELECT time, stock_code, stock_name, light, label, reason, last_price, "
            "       gain_today, mom5, ofi15, pos_range "
            "FROM entry_timing_signals WHERE trade_date=? ORDER BY id DESC",
            (D,)) or []
        items = []
        for r in rows:
            t, code, name, light, label, reason, lp = r[0], r[1], r[2], r[3], r[4], r[5], r[6]
            oc = self._outcome(code, D, t, float(lp) if lp else None)
            items.append({
                "time": t, "stock_code": code, "stock_name": name, "light": light,
                "label": label, "reason": reason, "trigger_price": lp,
                "gain_today": r[7], "mom5": r[8], "ofi15": r[9], "pos_range": r[10],
                **oc,
            })
        greens = sum(1 for it in items if it["light"] == "green")
        reds = sum(1 for it in items if it["light"] == "red")
        return {"trade_date": D, "count": len(items),
                "green_count": greens, "red_count": reds,
                "items": items, "experimental": True}
