#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""持仓做T助手（盘中高抛低吸 / 正T）

治"看到主力净流出却干等信号、手慢；砸下去又看到巨量流入却没买回"。

对"波动大、流动性好"的**持仓股**跑两腿状态机：
  高位 + 主力净流出  → 卖一档（高抛）
  回落 + 资金转流入  → 买回同等股数（低吸），完成一次正T、摊低成本

执行分阶段（默认最稳）：
  alert  仅推企微建议、用现价做"虚拟成交"跑通状态机与盈亏记账，**不下任何单**
  semi   前端一键确认 → 走 /api/trading/execute 真实下单（Phase 2）
  full   护栏内自动下单（Phase 3，本期不开）

只读 system_config 的开关/模式/熔断（重启不丢、改配置不必重部署）。
卖腿只针对已持有的股票、且永不卖破底仓下限；买回股数 ≤ 卖出股数，绝不净增敞口。

由 QuotePipeline.run_monitoring_cycle() 每轮调用。状态持久化在 t_trade_legs 表。
"""

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from ....utils import parse_flag

logger = logging.getLogger("intraday.ttrade")


# 状态字符串（与 t_trade_legs.state 一致）
S_IDLE = "IDLE"
S_SELL_PENDING = "SELL_PENDING"
S_SOLD_WAITING = "SOLD_WAITING_BUYBACK"
S_BUY_PENDING = "BUY_PENDING"
S_COMPLETED = "COMPLETED"
S_EXPIRED = "EXPIRED"

_OPEN_STATES = (S_IDLE, S_SELL_PENDING, S_SOLD_WAITING, S_BUY_PENDING)


class TMode(str, Enum):
    ALERT = "alert"
    SEMI = "semi"
    FULL = "full"


@dataclass
class TConfig:
    """做T护栏配置。enabled/mode/熔断每轮从 system_config 实时读，其余数值取 env→默认。"""
    enabled: bool = False
    mode: str = TMode.ALERT.value
    max_per_day: int = 2                 # 每股每日最多做T次数
    trim_fraction: float = 0.25          # 单次减仓比例（1/4）
    max_trim_fraction: float = 0.34      # 减仓硬上限（~1/3）
    min_core_fraction: float = 0.50      # 底仓保留下限（永不卖破原持仓的此比例）
    min_profit_gap_pct: float = 1.5      # 买回价须比卖出价低≥此（%）
    buyback_drawdown_pct: float = 2.0    # 自卖出/峰值回落到此才考虑买回（%）
    cooldown_min: int = 20               # 同股两次做T动作最小间隔（分钟）
    skip_open_min: int = 15              # 开盘跳过分钟
    skip_close_min: int = 20             # 收盘前跳过分钟
    eod_cutoff: str = "15:55"            # 失效未完结腿的截点（HK）
    daily_loss_kill_hkd: float = -500.0  # 当日做T已实现亏损≤此则冻结新腿
    outflow_ratio_thresh: float = -0.05  # net_inflow_ratio 低于此=净流出（卖腿条件）
    min_high_change_pct: float = 2.0     # 判"高位"的最低日内涨幅（%）
    near_high_pct: float = 0.99          # 现价≥当日高×此 也算"高位"（接近日内高点，治平/跌势下的局部高点）
    lot_size: int = 100                  # 每手股数回退值（优先用富途该股真实 lot_size，取不到才用此值）
    # 资格过滤（波动大 + 流动性好）
    min_amplitude_pct: float = 2.5       # 当日振幅(高-低)/昨收 下限（%）
    min_turnover_amount: float = 2.0e7   # 成交额下限（HKD）
    min_volume: int = 0                  # 成交量下限

    @classmethod
    def from_env(cls) -> "TConfig":
        def _f(key, default):
            try:
                return float(os.environ.get(key, default))
            except (TypeError, ValueError):
                return default

        def _i(key, default):
            try:
                return int(float(os.environ.get(key, default)))
            except (TypeError, ValueError):
                return default

        return cls(
            enabled=False,  # 总开关唯一来源=system_config: t_trade.enabled（每轮 _load_runtime_cfg 覆盖）；构造期默认关
            mode=str(os.environ.get("T_TRADE_MODE", TMode.ALERT.value)).lower(),
            max_per_day=_i("T_TRADE_MAX_PER_DAY", 2),
            trim_fraction=_f("T_TRADE_TRIM_FRACTION", 0.25),
            max_trim_fraction=_f("T_TRADE_MAX_TRIM_FRACTION", 0.34),
            min_core_fraction=_f("T_TRADE_MIN_CORE_FRACTION", 0.50),
            min_profit_gap_pct=_f("T_TRADE_MIN_PROFIT_GAP_PCT", 1.5),
            buyback_drawdown_pct=_f("T_TRADE_BUYBACK_DRAWDOWN_PCT", 2.0),
            cooldown_min=_i("T_TRADE_COOLDOWN_MIN", 20),
            skip_open_min=_i("T_TRADE_WINDOW_SKIP_OPEN_MIN", 15),
            skip_close_min=_i("T_TRADE_WINDOW_SKIP_CLOSE_MIN", 20),
            eod_cutoff=str(os.environ.get("T_TRADE_EOD_CUTOFF", "15:55")),
            daily_loss_kill_hkd=_f("T_TRADE_DAILY_LOSS_KILL_HKD", -500.0),
            outflow_ratio_thresh=_f("T_TRADE_OUTFLOW_RATIO_THRESH", -0.05),
            min_high_change_pct=_f("T_TRADE_MIN_HIGH_CHANGE_PCT", 2.0),
            near_high_pct=_f("T_TRADE_NEAR_HIGH_PCT", 0.99),
            lot_size=_i("T_TRADE_LOT_SIZE", 100),
            min_amplitude_pct=_f("T_TRADE_MIN_AMPLITUDE_PCT", 2.5),
            min_turnover_amount=_f("T_TRADE_MIN_TURNOVER_AMOUNT", 2.0e7),
            min_volume=_i("T_TRADE_MIN_VOLUME", 0),
        )


# ==================== 纯函数：报价取数 & 触发判定（便于单测） ====================

def _price(quote: Dict[str, Any]) -> float:
    """统一取现价（兼容 last_price / current_price / cur_price）。"""
    for k in ("last_price", "current_price", "cur_price"):
        v = quote.get(k)
        if v:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return 0.0


def _change_pct(quote: Dict[str, Any]) -> float:
    """日内涨跌幅%（优先用昨收现算，回退报价自带字段）。"""
    cur = _price(quote)
    prev = quote.get("prev_close", 0) or 0
    try:
        prev = float(prev)
    except (TypeError, ValueError):
        prev = 0.0
    if cur > 0 and prev > 0:
        return (cur - prev) / prev * 100.0
    for k in ("change_rate", "change_pct"):
        v = quote.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return 0.0


def _amplitude_pct(quote: Dict[str, Any]) -> float:
    """当日振幅%(高-低)/昨收。"""
    try:
        hi = float(quote.get("high_price", 0) or 0)
        lo = float(quote.get("low_price", 0) or 0)
        prev = float(quote.get("prev_close", 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    if hi > 0 and lo > 0 and prev > 0:
        return (hi - lo) / prev * 100.0
    return 0.0


def eligible(quote: Dict[str, Any], cfg: TConfig) -> Tuple[bool, str]:
    """波动大 + 流动性好 才做T。返回 (是否合格, 原因)。"""
    amp = _amplitude_pct(quote)
    if amp < cfg.min_amplitude_pct:
        return False, f"振幅不足({amp:.1f}%<{cfg.min_amplitude_pct}%)"
    try:
        turnover = float(quote.get("turnover", 0) or 0)
        volume = float(quote.get("volume", 0) or 0)
    except (TypeError, ValueError):
        turnover, volume = 0.0, 0.0
    if turnover < cfg.min_turnover_amount:
        return False, f"成交额不足({turnover/1e8:.2f}亿<{cfg.min_turnover_amount/1e8:.2f}亿)"
    if cfg.min_volume and volume < cfg.min_volume:
        return False, "成交量不足"
    return True, f"振幅{amp:.1f}%/成交额{turnover/1e8:.2f}亿"


def eval_sell_trigger(quote: Dict[str, Any], flow: Optional[Dict], cfg: TConfig) -> Optional[str]:
    """卖腿（高抛）触发：高位 + 主力净流出。命中返回原因文案，否则 None。

    "高位"= 日内涨幅≥阈值（强势日的高位）**或** 现价接近当日高点（平/跌势下的局部高点，
    治"523是局部高峰但当日没涨2%、净流出却没卖"的真实场景）。
    """
    chg = _change_pct(quote)
    price = _price(quote)
    try:
        high = float(quote.get("high_price", 0) or 0)
    except (TypeError, ValueError):
        high = 0.0
    near_high = high > 0 and price >= high * cfg.near_high_pct
    if chg < cfg.min_high_change_pct and not near_high:
        return None  # 既不强势、也不在局部高点 → 不高抛
    if not flow:
        return None
    net = flow.get("main_net_inflow", 0) or 0
    ratio = flow.get("net_inflow_ratio", 0) or 0
    inflow_change = flow.get("inflow_change", 0) or 0
    is_outflow = (net < 0 and ratio <= cfg.outflow_ratio_thresh) or (net < 0 and inflow_change < 0)
    if not is_outflow:
        return None
    pos_desc = f"日内涨{chg:.1f}%" if chg >= cfg.min_high_change_pct else f"逼近日高{high:.3f}"
    return (f"{pos_desc} + 主力净流出"
            f"(净流入{net/1e6:.0f}百万/占比{ratio*100:.1f}%)")


def eval_buyback_trigger(leg: Dict[str, Any], quote: Dict[str, Any], flow: Optional[Dict],
                         momentum: Any, cfg: TConfig) -> Optional[Tuple[str, int]]:
    """买回（低吸）触发：移植自 IntradaySwingTracker，至少2/3：
       1. 自卖出后峰值回落≥buyback_drawdown_pct
       2. 资金转正(主力净流入>0 且在增加)
       3. 5分钟动量转正(方向为正 或 底分型 或 下影支撑)
    且 现价 < 卖出价 − 最小利润间隔。命中返回 (原因, 条件数)。
    """
    price = _price(quote)
    sold = float(leg.get("sold_price") or 0)
    if price <= 0 or sold <= 0:
        return None

    peak = float(leg.get("peak_after_sell") or sold)
    conditions = 0
    reasons: List[str] = []

    if peak > 0:
        drawdown = (peak - price) / peak * 100.0
        if drawdown >= cfg.buyback_drawdown_pct:
            conditions += 1
            reasons.append(f"自峰值{peak:.3f}回落{drawdown:.1f}%")

    if flow:
        net = flow.get("main_net_inflow", 0) or 0
        inflow_change = flow.get("inflow_change", 0) or 0
        if net > 0 and inflow_change > 0:
            conditions += 1
            reasons.append(f"资金回流(净流入{net/1e6:.0f}百万,变化+{inflow_change/1e6:.0f}百万)")

    if momentum is not None:
        direction = getattr(momentum, "momentum_direction", 0) or 0
        has_bottom = getattr(momentum, "has_bottom_pattern", False)
        lower_support = getattr(momentum, "lower_shadow_support", False)
        if direction > 0 or has_bottom or lower_support:
            conditions += 1
            d = []
            if direction > 0:
                d.append(f"动量转正({direction:.2f})")
            if has_bottom:
                d.append("底分型")
            if lower_support:
                d.append("下影支撑")
            reasons.append(", ".join(d))

    if conditions < 2:
        return None

    # 必须比卖出价低足够多，否则做T无意义/亏损
    profit_gap = (sold - price) / sold * 100.0
    if profit_gap < cfg.min_profit_gap_pct:
        return None

    return " + ".join(reasons), conditions


def compute_trim_qty(original_qty: int, can_sell_qty: int, cfg: TConfig,
                     lot_size: Optional[int] = None) -> int:
    """按减仓比例、底仓下限、可卖量、整手 计算本次高抛股数（不足一手返回0）。

    lot_size: 该股真实每手股数（来自富途 lot_size）。不传则退回 cfg.lot_size（默认100）。
    """
    lot = int(lot_size) if lot_size and lot_size > 0 else cfg.lot_size
    if original_qty <= 0 or lot <= 0:
        return 0
    by_fraction = original_qty * cfg.trim_fraction
    by_cap = original_qty * cfg.max_trim_fraction
    floor_room = original_qty * (1.0 - cfg.min_core_fraction)  # 最多能卖到只剩底仓
    qty = min(by_fraction, by_cap, floor_room)
    if can_sell_qty > 0:
        qty = min(qty, can_sell_qty)
    lots = int(qty // lot)
    return lots * lot


# ==================== 助手主体 ====================

class TTradeAssistant:
    """持仓做T助手。db_manager 必需；order_manager/position_manager 供 Phase 2/3 真实下单与对账。"""

    def __init__(self, db_manager, order_manager=None, position_manager=None):
        self.db = db_manager
        self.order_manager = order_manager
        self.position_manager = position_manager
        self._cfg = TConfig.from_env()
        self._current_date: str = ""
        self._last_action_min: Dict[str, int] = {}  # code -> 上次动作距开盘分钟（内存，冷却用）

    # ---------- 配置 / 状态 ----------

    def _queries(self):
        from ....database.queries.t_trade_queries import TTradeQueries
        return TTradeQueries(self.db)

    @staticmethod
    def _lot_size(code: str) -> Optional[int]:
        """该股真实每手股数（富途 lot_size）。取不到返回 None → 退回 cfg.lot_size。"""
        try:
            from ...market_data.lot_size_provider import get_lot_size_provider
            return get_lot_size_provider().get(code)
        except Exception as e:
            logger.debug("获取每手股数失败 %s: %s", code, e)
            return None

    def _load_runtime_cfg(self) -> TConfig:
        """每轮刷新 enabled/mode（system_config 覆盖 env）。数值护栏沿用 from_env。"""
        cfg = self._cfg
        try:
            sq = getattr(self.db, "system_queries", None)
            if sq:
                en = sq.get_system_config("t_trade.enabled")
                if en is not None:
                    cfg.enabled = parse_flag(en)
                md = sq.get_system_config("t_trade.mode")
                if md:
                    cfg.mode = str(md).lower()
        except Exception as e:
            logger.debug("读取 t_trade 配置失败: %s", e)
        return cfg

    @staticmethod
    def _hk_today() -> str:
        from ....utils.market_helper import MarketTimeHelper
        return MarketTimeHelper.get_market_today("HK")

    @staticmethod
    def _trade_date(now: Optional[datetime] = None) -> str:
        """Use the injected clock for replay/tests and Hong Kong today in realtime."""
        if now is None:
            return TTradeAssistant._hk_today()
        if now.tzinfo is not None:
            from datetime import timedelta, timezone
            now = now.astimezone(timezone(timedelta(hours=8)))
        return now.strftime("%Y-%m-%d")

    @staticmethod
    def _now_min(now: Optional[datetime] = None) -> int:
        """距港股 09:30 的分钟数（服务器=北京时间=HK）。"""
        now = now or datetime.now()
        return (now.hour * 60 + now.minute) - (9 * 60 + 30)

    def _reset_if_new_day(self, trade_date: str):
        if trade_date != self._current_date:
            self._current_date = trade_date
            self._last_action_min.clear()

    # ---------- 主入口 ----------

    def evaluate_cycle(self, quotes: List[Dict], positions: Dict[str, Dict],
                       capital_flows: Optional[Dict[str, Dict]] = None,
                       momentum_map: Optional[Dict] = None,
                       now: Optional[datetime] = None) -> List[Dict]:
        """每轮评估持仓股的做T卖腿/买腿，返回 trade_action 列表（source='t_trade'）。"""
        cfg = self._load_runtime_cfg()
        if not cfg.enabled or not positions:
            return []

        trade_date = self._trade_date(now)
        self._reset_if_new_day(trade_date)

        now_min = self._now_min(now)
        # 时间窗护栏：开盘 N 分钟内、收盘前 N 分钟内不动手
        if now_min < cfg.skip_open_min:
            return []
        close_min = (16 * 60) - (9 * 60 + 30)  # 09:30→16:00 共390分钟
        if now_min > (close_min - cfg.skip_close_min):
            return []

        capital_flows = capital_flows or {}
        momentum_map = momentum_map or {}
        quotes_map = {q.get("code", ""): q for q in quotes if q.get("code")}

        q = self._queries()
        open_legs = {leg["stock_code"]: leg for leg in q.get_open_legs(trade_date)}

        # 当日做T亏损熔断：只冻结"新开卖腿"，已在等待买回的腿仍允许买回（先把敞口补回）
        frozen = q.sum_realized_loss_today(trade_date) <= cfg.daily_loss_kill_hkd

        actions: List[Dict] = []
        for code, pos in positions.items():
            quote = quotes_map.get(code)
            if not quote:
                continue
            price = _price(quote)
            if price <= 0:
                continue
            flow = capital_flows.get(code)
            mom = momentum_map.get(code)
            leg = open_legs.get(code)

            if leg and leg["state"] == S_SOLD_WAITING:
                # 更新峰/谷后评估买回
                act = self._handle_buyback(q, cfg, leg, quote, flow, mom, price, now_min)
                if act:
                    actions.append(act)
            elif not leg and not frozen:
                act = self._handle_sell(q, cfg, code, pos, quote, flow, trade_date, price, now_min)
                if act:
                    actions.append(act)
            # 其余状态(SELL_PENDING/BUY_PENDING) 等对账推进，本轮不产新动作

        return actions

    # ---------- 卖腿 ----------

    def _handle_sell(self, q, cfg: TConfig, code: str, pos: Dict, quote: Dict,
                     flow: Optional[Dict], trade_date: str, price: float,
                     now_min: int) -> Optional[Dict]:
        # 每股每日上限
        if q.count_completed_today(code, trade_date) >= cfg.max_per_day:
            return None
        # 冷却
        last = self._last_action_min.get(code)
        if last is not None and (now_min - last) < cfg.cooldown_min:
            return None
        # 资格：波动大 + 流动性好
        ok, elig_reason = eligible(quote, cfg)
        if not ok:
            return None
        # 触发：高位 + 净流出
        reason = eval_sell_trigger(quote, flow, cfg)
        if not reason:
            return None

        original_qty = int(pos.get("qty", 0) or 0)
        can_sell = int(pos.get("can_sell_qty", original_qty) or original_qty)
        trim_qty = compute_trim_qty(original_qty, can_sell, cfg, self._lot_size(code))
        if trim_qty <= 0:
            return None

        frac_label = f"约{cfg.trim_fraction*100:.0f}%仓"
        target = price * (1 - cfg.min_profit_gap_pct / 100.0)
        stock_name = pos.get("stock_name", code)

        if cfg.mode == TMode.ALERT.value:
            # 虚拟成交：以现价记卖出，进入等待买回
            leg_id = q.create_leg(
                stock_code=code, stock_name=stock_name, trade_date=trade_date,
                mode=cfg.mode, state=S_SOLD_WAITING, original_qty=original_qty,
                sold_qty=trim_qty, sold_price=price,
                sold_time=datetime.now().strftime("%H:%M:%S"),
                sell_reason=reason, peak_after_sell=price, trough_after_sell=price)
        else:
            # semi/full：建待确认腿（真实下单在 Phase 2/3 接入）
            leg_id = q.create_leg(
                stock_code=code, stock_name=stock_name, trade_date=trade_date,
                mode=cfg.mode, state=S_SELL_PENDING, original_qty=original_qty,
                sold_qty=trim_qty, sell_reason=reason)

        self._last_action_min[code] = now_min
        msg = (f"🅣 做T·高抛建议 {stock_name}({code}) @ {price:.3f} — "
               f"减约{trim_qty}股({frac_label})；{reason}。回落买回目标≤{target:.3f}")
        logger.info("[做T] 卖腿触发 %s leg=%s qty=%s @%.3f: %s",
                    code, leg_id, trim_qty, price, reason)
        return {
            "signal_type": "SELL",
            "stock_code": code,
            "stock_name": stock_name,
            "price": price,
            "reason": f"做T·高抛 {reason}",
            "message": msg,
            "action": "t_trade_sell",
            "source": "t_trade",
            "t_leg": {
                "leg_id": leg_id, "side": "sell", "mode": cfg.mode,
                "trim_qty": trim_qty, "trim_fraction": cfg.trim_fraction,
                "target_buyback_price": round(target, 3), "elig": elig_reason,
            },
        }

    # ---------- 买腿 ----------

    def _handle_buyback(self, q, cfg: TConfig, leg: Dict, quote: Dict,
                        flow: Optional[Dict], mom: Any, price: float,
                        now_min: int) -> Optional[Dict]:
        code = leg["stock_code"]
        # 更新卖后峰/谷
        peak = max(float(leg.get("peak_after_sell") or price), price)
        trough_prev = leg.get("trough_after_sell")
        trough = min(float(trough_prev), price) if trough_prev else price
        if peak != leg.get("peak_after_sell") or trough != leg.get("trough_after_sell"):
            q.update_leg(leg["id"], peak_after_sell=peak, trough_after_sell=trough)
            leg["peak_after_sell"] = peak

        # 冷却（卖腿与买腿之间也尊重冷却，避免秒卖秒买）
        last = self._last_action_min.get(code)
        if last is not None and (now_min - last) < cfg.cooldown_min:
            return None

        hit = eval_buyback_trigger(leg, quote, flow, mom, cfg)
        if not hit:
            return None
        reason, conditions = hit

        sold = float(leg.get("sold_price") or 0)
        sold_qty = int(leg.get("sold_qty") or 0)
        stock_name = leg.get("stock_name", code)
        profit_pct = (sold - price) / sold * 100.0 if sold > 0 else 0.0
        realized = (sold - price) * sold_qty

        if cfg.mode == TMode.ALERT.value:
            q.update_leg(leg["id"], state=S_COMPLETED, bought_price=price,
                         bought_time=datetime.now().strftime("%H:%M:%S"),
                         buy_reason=reason, realized_pnl=round(realized, 2))
        else:
            q.update_leg(leg["id"], state=S_BUY_PENDING,
                         target_buyback_price=round(price, 3), buy_reason=reason)

        self._last_action_min[code] = now_min
        msg = (f"🅣 做T·买回建议 {stock_name}({code}) @ {price:.3f} — "
               f"较卖出{sold:.3f}低{profit_pct:.1f}%；{reason}。"
               f"本次做T实现≈{realized:.0f}港元")
        logger.info("[做T] 买腿触发 %s leg=%s qty=%s @%.3f 实现≈%.0f: %s",
                    code, leg["id"], sold_qty, price, realized, reason)
        return {
            "signal_type": "BUY",
            "stock_code": code,
            "stock_name": stock_name,
            "price": price,
            "reason": f"做T·买回({conditions}/3) {reason}",
            "message": msg,
            "action": "t_trade_buyback",
            "source": "t_trade",
            "t_leg": {
                "leg_id": leg["id"], "side": "buy", "mode": cfg.mode,
                "buy_qty": sold_qty, "sold_price": sold,
                "profit_pct": round(profit_pct, 2), "realized_pnl": round(realized, 2),
            },
        }

    # ---------- 收盘失效 ----------

    def expire_eod(self, now: Optional[datetime] = None):
        """收盘截点后，把仍未完结的腿标 EXPIRED（DAY 限价单自然到收盘失效，无需撤单）。"""
        cfg = self._cfg
        now = now or datetime.now()
        try:
            cutoff_h, cutoff_m = (int(x) for x in cfg.eod_cutoff.split(":"))
        except Exception:
            cutoff_h, cutoff_m = 15, 55
        if (now.hour, now.minute) < (cutoff_h, cutoff_m):
            return
        trade_date = self._hk_today()
        q = self._queries()
        for leg in q.get_open_legs(trade_date):
            q.update_leg(leg["id"], state=S_EXPIRED)
            logger.info("[做T] 收盘失效 leg=%s %s 状态=%s",
                        leg["id"], leg["stock_code"], leg["state"])

    # ---------- 对账（Phase 2：真实成交回写；alert 模式无挂单，安全空跑） ----------

    def reconcile_fills(self, deals_by_code: Dict[str, List[Dict]]):
        """用真实成交推进 SELL_PENDING/BUY_PENDING。alert 模式无挂单 → 无操作。"""
        if not deals_by_code:
            return
        trade_date = self._hk_today()
        q = self._queries()
        for leg in q.get_open_legs(trade_date):
            if leg["state"] not in (S_SELL_PENDING, S_BUY_PENDING):
                continue
            # Phase 2 接入：按 leg 的 order_id 在 deals 中匹配成交，回写 sold/bought 与状态。
            # 此处保留挂钩点，alert 模式不会进入该分支。

    # ---------- 半自动确认/取消（Phase 2 实现真实下单；此处先安全占位） ----------

    def confirm_leg(self, leg_id: int) -> Dict:
        q = self._queries()
        leg = q.get_leg(leg_id)
        if not leg:
            return {"ok": False, "message": "腿不存在"}
        return {"ok": False, "message": "半自动下单将于 Phase 2 接入；当前为告警阶段"}

    def cancel_leg(self, leg_id: int) -> Dict:
        q = self._queries()
        leg = q.get_leg(leg_id)
        if not leg:
            return {"ok": False, "message": "腿不存在"}
        if leg["state"] in (S_COMPLETED, S_EXPIRED):
            return {"ok": False, "message": f"腿已 {leg['state']}，无法取消"}
        q.update_leg(leg_id, state=S_EXPIRED)
        return {"ok": True, "message": "已取消该做T腿"}

    # ---------- 状态查询（供 API/前端） ----------

    def get_status(self) -> Dict[str, Any]:
        cfg = self._load_runtime_cfg()
        trade_date = self._hk_today()
        legs = []
        try:
            legs = self._queries().list_legs(trade_date)
        except Exception as e:
            logger.debug("读取做T状态失败: %s", e)
        realized = sum((l.get("realized_pnl") or 0) for l in legs)
        by_code: Dict[str, Dict] = {}
        for l in legs:
            # 每股取最新一条（list_legs 已按 id DESC）
            by_code.setdefault(l["stock_code"], l)
        return {
            "trade_date": trade_date,
            "enabled": cfg.enabled,
            "mode": cfg.mode,
            "config": {
                "trim_fraction": cfg.trim_fraction,
                "min_core_fraction": cfg.min_core_fraction,
                "max_per_day": cfg.max_per_day,
                "min_profit_gap_pct": cfg.min_profit_gap_pct,
                "buyback_drawdown_pct": cfg.buyback_drawdown_pct,
                "daily_loss_kill_hkd": cfg.daily_loss_kill_hkd,
            },
            "realized_pnl_today": round(realized, 2),
            "legs": legs,
            "by_code": by_code,
        }

    def set_config(self, enabled: Optional[bool] = None, mode: Optional[str] = None) -> Dict:
        sq = getattr(self.db, "system_queries", None)
        if not sq:
            return {"ok": False, "message": "system_config 不可用"}
        if enabled is not None:
            sq.set_system_config("t_trade.enabled", "true" if enabled else "false", "做T总开关")
        if mode is not None:
            if mode not in (m.value for m in TMode):
                return {"ok": False, "message": f"非法模式 {mode}"}
            sq.set_system_config("t_trade.mode", mode, "做T执行模式")
        return {"ok": True, "message": "已更新做T配置"}
