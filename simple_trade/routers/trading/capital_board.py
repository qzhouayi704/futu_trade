#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主力资金看板（Capital Board）API 路由

把"主力资金"从信号流的**事件流**(按时间倒序、同股散落多条)，重组成**以股票为中心
的聚合排行**(一只票一行)：直观对比每只票的"资金态 + 股价态 + 跨源确认(V1 Sniper)"。

口径(与前端信号流里的 capital_trend 提醒同源)：
- **主口径=逐笔自建**(TickCapitalAccumulator.snapshot_all)：累计净额 cum_main_net、
  力度倍数(相对自身)、第几次大单——与用户看到的信号流同一种语言。
- **兜底=富途聚合**(capital_flow_cache)：累加器 OFF/无快照(本地 dev、盘前空窗)时退化，
  逐行标注 flow_source，绝不静默混排两口径。
- **只留真大单**：用 CapitalThresholdCalibrator 标定的"按股自适应大单门槛"过滤，
  小额(净额未达该股门槛)的票不进榜、不长期霸榜。

纯读 + 内存聚合，不新增表；统一 {success, data, message}；任何异常都返回空榜不抛 500。
"""

import asyncio
import logging
from collections import defaultdict

from fastapi import APIRouter, Query

from ...dependencies import get_container

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/capital-board", tags=["主力资金看板"])

# 资金侧买入语义的 sniper 信号类型（用于共振判定）
_BUY_SNIPER_TYPES = frozenset({"mega_buy", "accel_in", "reversal_bull"})
# 强度档位阈值（与 CapitalTrendConfig 默认一致：强≥2.0× / 中≥1.0×）
_STRONG_MULT = 2.0
_MID_MULT = 1.0


def _derive_tick_state(snap: dict, large_thr: float, scale: float, chg: float):
    """从逐笔快照无状态地派生 (direction, strength_tier, strength_mult)。

    注意：这是看板要的"当前资金态"，与 CapitalTrendDetector 的事件型 evaluate(带冷却/
    re-arm) 不同——这里不门控，只读当下状态。方向口径对齐 detector：
      流入 / 回落(自峰值回撤) / 拉高出货(股价涨而主力净流出) / 流出 / 持平。
    """
    cum = float(snap.get("cum_main_net") or 0.0)
    peak = float(snap.get("cum_peak") or 0.0)
    window_net = float(snap.get("window_main_net") or 0.0)
    strength_mult = (abs(window_net) / scale) if scale > 0 else 0.0
    if strength_mult >= _STRONG_MULT:
        tier = "强"
    elif strength_mult >= _MID_MULT:
        tier = "中"
    else:
        tier = "弱"

    pullback = peak - cum
    had_peak = peak >= large_thr and large_thr > 0
    if chg > 0 and not had_peak and large_thr > 0 and cum <= -large_thr:
        direction = "distribution"          # 拉高出货
    elif had_peak and pullback >= max(large_thr, peak * 0.15):
        direction = "pullback"              # 自峰值回落
    elif cum > 0:
        direction = "inflow"
    elif cum < 0:
        direction = "outflow"
    else:
        direction = "flat"
    return direction, tier, round(strength_mult, 2)


def _derive_cache_state(cf: dict):
    """从富途缓存口径派生 (direction, strength_tier)。无 cum_peak/窗口 → 只判流入/流出。"""
    main_net = float(cf.get("main_net_inflow") or 0.0)
    score = float(cf.get("capital_score") or 0.0)
    if score >= 70:
        tier = "强"
    elif score >= 55:
        tier = "中"
    else:
        tier = "弱"
    if main_net > 0:
        direction = "inflow"
    elif main_net < 0:
        direction = "outflow"
    else:
        direction = "flat"
    return direction, tier


def _load_db_tick_snaps(db) -> dict:
    """从 tick_capital_flow 读每股当日最新一行(逐笔口径)——治后端重启内存累加器清空、
    当日累积丢失→看板全回退富途口径的问题(数据本就每55s落库,只是累加器启动没读回)。

    表缺 cum_peak/大单计数:direction 退化为只判流入/流出/拉高出货(distribution 只需
    cum<0+股价涨,仍可判),"回落"(需真峰值)与大单买卖次数降级为0;内存累加器追上后由
    更丰富的 in-memory 快照覆盖。
    """
    if not db:
        return {}
    try:
        # 只取"今天"的逐笔兜底：原 MAX(trade_date) 会在非交易日把最近一个交易日(如周五/周六)
        # 的累积当成当前展示。看板语义是"今日主力资金",非交易日今天无行→返回空→看板自然为空。
        from ...utils.market_helper import MarketTimeHelper
        today = MarketTimeHelper.get_market_today('HK')
        d = db.execute_query(
            "SELECT MAX(trade_date) FROM tick_capital_flow WHERE trade_date = ?", (today,))
        trade_date = d[0][0] if d and d[0] else None
        if not trade_date:
            return {}
        rows = db.execute_query(
            "SELECT stock_code, cum_main_net, window_main_net, big_order_buy_ratio "
            "FROM tick_capital_flow WHERE id IN ("
            "  SELECT MAX(id) FROM tick_capital_flow WHERE trade_date=? GROUP BY stock_code)",
            (trade_date,))
        out = {}
        for r in (rows or []):
            code = r[0]
            cum = float(r[1] or 0.0)
            out[code] = {
                "stock_code": code, "trade_date": trade_date,
                "cum_main_net": cum,
                "window_main_net": float(r[2] or 0.0),
                "cum_peak": max(cum, 0.0),   # 库无峰值,近似 max(cum,0):不误判回落
                "big_buy_count": 0, "big_sell_count": 0,
            }
        return out
    except Exception as e:
        logger.debug(f"读 tick_capital_flow 兜底失败: {e}")
        return {}


def _slim_sniper(sig: dict) -> dict:
    """精简 sniper 信号给看板行内展示。"""
    return {
        "signal_type": sig.get("signal_type"),
        "strength": sig.get("strength", 0),
        "tier": sig.get("tier", ""),
        "time": sig.get("time"),
        "is_red": bool(sig.get("is_red")),
        "emoji": sig.get("emoji", ""),
    }


@router.get("/ranking")
async def get_capital_board_ranking(
    limit: int = Query(20, ge=1, le=50, description="返回条数"),
    include_sniper: bool = Query(True, description="是否行内并入今日 Sniper 信号"),
):
    """主力资金看板排行：全监控/订阅池 ∪ 持仓，按主力资金强度(只留真大单)排名。"""
    container = get_container()
    try:
        # 1. 取池：订阅 ∪ 持仓
        sub_mgr = getattr(container, "subscription_manager", None)
        subs = set(sub_mgr.subscribed_stocks) if sub_mgr else set()

        held_codes: set = set()
        fts = getattr(container, "futu_trade_service", None)
        if fts:
            try:
                loop = asyncio.get_running_loop()
                res = await loop.run_in_executor(None, fts.get_positions)
                if res and res.get("success"):
                    held_codes = {
                        p.get("stock_code", "") for p in res.get("positions", [])
                        if p.get("stock_code") and (p.get("qty", 0) or 0) > 0
                    }
            except Exception as e:
                logger.debug(f"取持仓失败: {e}")

        pool = subs | held_codes
        if not pool:
            return {"success": True, "data": {"ranking": [], "pool_size": 0,
                    "flow_source": "none"}, "message": "监控池为空"}

        # 2. 报价 map（盘前/收盘后用 get_last_quotes 兜底）
        qmap = {}
        try:
            from ...core import get_state_manager
            state = get_state_manager()
            quotes = state.get_cached_quotes() or state.get_last_quotes() or []
            qmap = {q.get("code"): q for q in quotes if q.get("code")}
        except Exception as e:
            logger.debug(f"取报价失败: {e}")

        # 3. 逐笔口径快照（主口径，内存）
        acc = getattr(container, "tick_capital_accumulator", None)
        tick_snaps = {}
        if acc and getattr(acc, "enabled", False):
            try:
                tick_snaps = acc.snapshot_all()
            except Exception as e:
                logger.debug(f"取逐笔快照失败: {e}")

        # 3b. DB 逐笔兜底：内存累加器没有的票(重启清空/未及累积)，读 tick_capital_flow
        #     当日最新行补回逐笔口径——避免重启后看板全回退富途口径、丢当日累积。
        db = getattr(container, "db_manager", None)
        db_tick_snaps = {}
        if db and any(c not in tick_snaps for c in pool):
            try:
                loop = asyncio.get_running_loop()
                db_tick_snaps = await loop.run_in_executor(None, _load_db_tick_snaps, db)
            except Exception as e:
                logger.debug(f"读 DB 逐笔兜底失败: {e}")

        # 4. 富途缓存口径（最末兜底，纯缓存不调 API）——内存+DB 两层逐笔都没有的票才用
        cache_map = {}
        analyzer = getattr(container, "capital_analyzer", None)
        cache_codes = [c for c in pool if c not in tick_snaps and c not in db_tick_snaps]
        if analyzer and cache_codes:
            try:
                loop = asyncio.get_running_loop()
                cache_map = await loop.run_in_executor(
                    None, analyzer.batch_read_cache_only, cache_codes)
            except Exception as e:
                logger.debug(f"批量读资金缓存失败: {e}")

        # 5. Sniper 今日信号按股聚合 + TOP 机会榜
        sniper_map = defaultdict(list)
        top_opp: set = set()
        if include_sniper:
            sniper = getattr(container, "intraday_sniper", None)
            if sniper:
                try:
                    for s in sniper.get_today_signals():
                        code = s.get("stock_code")
                        if code:
                            sniper_map[code].append(_slim_sniper(s))
                    top_opp = {x.get("stock_code")
                               for x in sniper.get_top_ranking().get("opportunity", [])}
                except Exception as e:
                    logger.debug(f"取 Sniper 信号失败: {e}")

        bs = getattr(container, "baseline_service", None)

        # 6. 组装每行
        big_rows = []       # 达标真大单
        sniper_only = []    # 未达门槛但有买入 sniper 信号
        # 候选 = 有任一口径资金数据的票（避免对全池算门槛）
        candidates = set(tick_snaps.keys()) | set(db_tick_snaps.keys()) | set(cache_map.keys())
        # 有 sniper 信号但无资金数据的票也纳入候选（走 sniper_only）
        candidates |= set(c for c in sniper_map.keys() if c in pool)
        for code in candidates:
            if code not in pool:
                continue
            q = qmap.get(code, {})
            last_price = q.get("last_price") or q.get("nominal_price") or 0
            prev_close = q.get("prev_close") or 0
            chg = 0.0
            if last_price and prev_close and prev_close > 0:
                chg = (float(last_price) - float(prev_close)) / float(prev_close) * 100.0
            else:
                chg = float(q.get("change_rate") or q.get("change_percent") or 0.0)
            name = (q.get("name") or q.get("stock_name") or code)

            tiers = (0.0, 0.0, 0.0)
            if bs:
                try:
                    tiers = bs.get_capital_tiers(code)
                except Exception:
                    pass
            large_thr = float(tiers[0]) if tiers and tiers[0] else 0.0
            scale = float(tiers[2]) if tiers and len(tiers) > 2 and tiers[2] else large_thr

            snip = sniper_map.get(code, [])
            has_buy_sniper = any(s.get("signal_type") in _BUY_SNIPER_TYPES for s in snip)

            snap = tick_snaps.get(code) or db_tick_snaps.get(code)
            net_amount = None
            strength_mult = None
            direction = "flat"
            strength = "弱"
            big_buy_count = 0
            big_sell_count = 0
            flow_source = None
            if snap:
                flow_source = "tick"
                net_amount = float(snap.get("cum_main_net") or 0.0)
                big_buy_count = int(snap.get("big_buy_count") or 0)
                big_sell_count = int(snap.get("big_sell_count") or 0)
                direction, strength, strength_mult = _derive_tick_state(
                    snap, large_thr, scale, chg)
            else:
                cf = cache_map.get(code)
                if cf:
                    flow_source = "cache"
                    net_amount = float(cf.get("main_net_inflow") or 0.0)
                    direction, strength = _derive_cache_state(cf)

            magnitude = abs(net_amount) if net_amount is not None else 0.0
            # 只留真大单：净额绝对值达该股自适应门槛（无门槛标定时不卡，避免冷启动全空）
            passes = (net_amount is not None
                      and (large_thr <= 0 or magnitude >= large_thr))

            is_resonance = (
                direction == "inflow" and strength in ("强", "中")
                and (has_buy_sniper or code in top_opp))

            row = {
                "stock_code": code,
                "stock_name": name,
                "last_price": round(float(last_price), 3) if last_price else 0,
                "intraday_pct": round(chg, 2),
                "net_amount": round(net_amount, 2) if net_amount is not None else None,
                "strength_mult": strength_mult,
                "strength": strength,
                "direction": direction,
                "big_buy_count": big_buy_count,
                "big_sell_count": big_sell_count,
                "big_order_threshold": round(large_thr, 2),
                "flow_source": flow_source,
                "sniper_signals": snip,
                "is_resonance": is_resonance,
                "held": code in held_codes,
                "sniper_only": False,
            }
            if passes:
                big_rows.append(row)
            elif has_buy_sniper:
                row["sniper_only"] = True
                sniper_only.append(row)

        # 7. 排序：达标大单按净额绝对值降序；仅狙击按最强 sniper 强度降序，置于其后
        big_rows.sort(key=lambda r: abs(r["net_amount"] or 0), reverse=True)
        sniper_only.sort(
            key=lambda r: max((s.get("strength", 0) for s in r["sniper_signals"]), default=0),
            reverse=True)
        ranking = (big_rows + sniper_only)[:limit]

        # 主口径标识：多数行是哪种口径
        src = "tick" if any(r["flow_source"] == "tick" for r in ranking) else (
            "cache" if ranking else "none")
        return {
            "success": True,
            "data": {
                "ranking": ranking,
                "pool_size": len(pool),
                "big_order_count": len(big_rows),
                "flow_source": src,
            },
            "message": f"主力资金看板：{len(ranking)} 只(达标大单 {len(big_rows)})",
        }
    except Exception as e:
        logger.error(f"主力资金看板排行失败: {e}", exc_info=True)
        return {"success": False, "data": {"ranking": []},
                "message": f"获取主力资金看板失败: {e}"}
