#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
买入前快速检查 API
输入股票代码，秒出资金面评分 + GO/CAUTION/STOP 综合判定
"""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query

from ...dependencies import get_container
from ...schemas.common import APIResponse

router = APIRouter(prefix="/api/pre-trade-check", tags=["买入前检查"])
logger = logging.getLogger("router.pre_trade_check")


def _find_position(trade_service, stock_code: str):
    """从富途持仓中找到该股的持仓 dict；失败/无持仓返回 None。"""
    try:
        if not trade_service:
            return None
        res = trade_service.get_positions()
        if not res or not res.get("success"):
            return None
        for p in res.get("positions", []):
            if p.get("stock_code") == stock_code and float(p.get("qty", 0) or 0) > 0:
                return p
    except Exception:
        return None
    return None


@router.get("/recommendations", response_model=APIResponse)
async def get_recommendations(container=Depends(get_container)):
    """
    获取当前所有适合买入/卖出的股票推荐列表。
    聚合资金流信号、大单追踪、策略信号，按评分排序。
    """
    db = getattr(container, 'db_manager', None)
    if not db:
        return APIResponse(success=False, data=None, message="数据库不可用")

    from ...config.legacy_signal_policy import resolve_legacy_signal_policy
    legacy_policy = resolve_legacy_signal_policy()
    if not legacy_policy.action_enabled:
        return APIResponse(success=True, data={
            "buy_recommendations": [],
            "sell_recommendations": [],
            "total_signals": 0,
            "generated_at": datetime.now().isoformat(),
            "legacy_mode": legacy_policy.mode.value,
        }, message="旧版推荐已转为观察模式，请使用 V2 候选池与正式预警")

    try:
        # 1. 今日所有资金流信号
        flow_rows = db.execute_query("""
            SELECT cfs.stock_code, s.name, cfs.rule_id, cfs.rule_name,
                   cfs.signal_type, cfs.confidence, cfs.reason, cfs.price,
                   cfs.created_at
            FROM capital_flow_signals cfs
            LEFT JOIN stocks s ON s.code = cfs.stock_code
            WHERE date(cfs.created_at) = date('now')
            ORDER BY cfs.created_at DESC
        """)

        # 2. 今日最新大单数据（每只股票取最新）
        big_rows = db.execute_query("""
            SELECT stock_code, buy_sell_ratio, order_strength, big_buy_amount,
                   big_sell_amount, created_at
            FROM big_order_tracking
            WHERE date(created_at) = date('now')
            AND id IN (
                SELECT MAX(id) FROM big_order_tracking
                WHERE date(created_at) = date('now')
                GROUP BY stock_code
            )
        """)
        big_map = {}
        for r in (big_rows or []):
            big_map[r[0]] = {
                "buy_sell_ratio": float(r[1] or 0),
                "order_strength": float(r[2] or 0),
                "big_buy_amount": float(r[3] or 0),
                "big_sell_amount": float(r[4] or 0),
                "snapshot_time": r[5],
            }

        # 3. 今日策略信号
        ts_rows = db.execute_query("""
            SELECT s.code, s.name, ts.signal_type, ts.strategy_name,
                   ts.signal_price, ts.created_at
            FROM trade_signals ts
            JOIN stocks s ON ts.stock_id = s.id
            WHERE date(ts.created_at) = date('now', 'localtime')
            ORDER BY ts.created_at DESC
        """)

        # 聚合按股票分组
        stock_data = {}  # code -> {signals, big_order, strategies, ...}

        for r in (flow_rows or []):
            code = r[0]
            if code not in stock_data:
                stock_data[code] = {
                    "stock_code": code,
                    "stock_name": r[1] or "",
                    "flow_signals": [],
                    "strategies": [],
                    "big_order": None,
                }
            stock_data[code]["flow_signals"].append({
                "rule_id": r[2], "rule_name": r[3],
                "signal_type": r[4], "confidence": float(r[5] or 0),
                "reason": r[6], "price": r[7], "time": r[8],
            })

        for r in (ts_rows or []):
            code = r[0]
            if code not in stock_data:
                stock_data[code] = {
                    "stock_code": code,
                    "stock_name": r[1] or "",
                    "flow_signals": [],
                    "strategies": [],
                    "big_order": None,
                }
            stock_data[code]["strategies"].append({
                "signal_type": r[2], "strategy": r[3],
                "price": r[4], "time": r[5],
            })

        # 填入大单数据（已有信号的股票）
        for code, big in big_map.items():
            if code in stock_data:
                stock_data[code]["big_order"] = big
            else:
                # 没有资金流/策略信号，但有大单数据的股票也纳入推荐
                # 获取股票名称
                name = db.stock_queries.get_stock_name(code)
                stock_data[code] = {
                    "stock_code": code,
                    "stock_name": name,
                    "flow_signals": [],
                    "strategies": [],
                    "big_order": big,
                }

        # 预查询 K线数据（批量，一次查完）
        all_codes = list(stock_data.keys())
        kline_map = {}  # code -> {position, change_5d, avg_turnover}
        if all_codes:
            today = datetime.now().strftime("%Y-%m-%d")
            for code in all_codes:
                try:
                    krows = db.execute_query("""
                        SELECT close_price, high_price, low_price, turnover_rate
                        FROM kline_data WHERE stock_code = ? AND time_key < ?
                        ORDER BY time_key DESC LIMIT 20
                    """, (code, today))
                    if krows and len(krows) >= 5:
                        latest = float(krows[0][0])
                        highs = [float(r[1]) for r in krows]
                        lows = [float(r[2]) for r in krows]
                        max_h, min_l = max(highs), min(lows)
                        position = (latest - min_l) / (max_h - min_l) if max_h != min_l else 0.5
                        change_5d = (float(krows[0][0]) - float(krows[4][0])) / float(krows[4][0]) * 100
                        avg_turnover = sum(float(r[3] or 0) for r in krows[:5]) / 5
                        kline_map[code] = {
                            "position": position,
                            "change_5d": change_5d,
                            "avg_turnover": avg_turnover,
                        }
                except Exception:
                    pass

        # 评估每只股票，生成推荐
        buy_list = []
        sell_list = []

        for code, data in stock_data.items():
            score = 50
            reasons = []
            action = None

            # === 维度 1: 资金流信号 (权重 20%) ===
            has_sustained = False
            for sig in data["flow_signals"]:
                if sig["signal_type"] == "SELL" and sig["confidence"] >= 0.6:
                    score -= int(sig["confidence"] * 20)
                    reasons.append(f"🔴 {sig['rule_name']}")
                elif sig["signal_type"] == "BUY" and sig["confidence"] >= 0.6:
                    score += int(sig["confidence"] * 12)
                    reasons.append(f"🟢 {sig['rule_name']}")
                    if sig["rule_id"] == "R11":
                        has_sustained = True

            # === 维度 2: 大单强度 (权重 30%) ===
            big = data.get("big_order") or big_map.get(code)
            if big:
                data["big_order"] = big
                strength = big["order_strength"]
                ratio = big.get("buy_sell_ratio", 1.0)
                if strength >= 0.3 and ratio >= 1.5:
                    score += 15
                    reasons.append(f"🟢 大单强买 str={strength:+.2f}")
                elif strength >= 0.15:
                    score += 8
                    reasons.append(f"🟢 大单偏买 str={strength:+.2f}")
                elif strength <= -0.2 and ratio <= 0.7:
                    score -= 18
                    reasons.append(f"🔴 大单强卖 str={strength:+.2f}")
                elif strength <= -0.1:
                    score -= 8
                    reasons.append(f"🟡 大单偏卖 str={strength:+.2f}")

            # === 维度 3: 策略信号 (权重 10%) ===
            buy_strats = [s for s in data["strategies"] if s["signal_type"] == "BUY"]
            sell_strats = [s for s in data["strategies"] if s["signal_type"] == "SELL"]
            if buy_strats:
                score += 5 * min(len(buy_strats), 2)
                reasons.append(f"📈 {len(buy_strats)}个策略BUY")
            if sell_strats:
                score -= 8 * min(len(sell_strats), 2)
                reasons.append(f"📉 {len(sell_strats)}个策略SELL")

            # === 维度 4: K线位置 (权重 20%) ===
            kinfo = kline_map.get(code)
            if kinfo:
                pos = kinfo["position"]
                if pos <= 0.25:
                    score += 10
                    reasons.append(f"📊 K线低位 {pos*100:.0f}%")
                elif pos >= 0.75:
                    score -= 12
                    reasons.append(f"📊 K线高位 {pos*100:.0f}% 追高风险")
                # 不在极端位置不加减分

            # === 维度 5: 近期趋势 (权重 10%) ===
            if kinfo:
                chg = kinfo["change_5d"]
                if -15 <= chg <= -5:
                    score += 5  # 适度回调，可能是买点
                    reasons.append(f"📉 5日回调{chg:.1f}%")
                elif chg < -15:
                    score -= 8  # 暴跌，风险大
                    reasons.append(f"📉 5日暴跌{chg:.1f}%")
                elif chg > 10:
                    score -= 5  # 涨太多追高风险
                    reasons.append(f"📈 5日涨{chg:.1f}% 注意追高")

            # === 维度 6: 流动性 (权重 10%) ===
            if kinfo:
                turnover = kinfo["avg_turnover"]
                if turnover < 0.3:
                    score -= 10
                    reasons.append(f"⚠️ 换手率{turnover:.2f}% 流动性差")
                elif turnover >= 3.0:
                    score += 5
                    reasons.append(f"✅ 换手率{turnover:.1f}% 流动充沛")

            # 持有建议
            holding = "scalp_only"
            if has_sustained:
                holding = "trailing_stop"
            elif big and big["order_strength"] >= 0.3:
                holding = "swing"

            score = max(0, min(100, score))

            # 数据新鲜度（P1）
            data_age = None
            big_time = (data.get("big_order") or {}).get("snapshot_time", "")
            if big_time:
                try:
                    snap_dt = datetime.fromisoformat(str(big_time))
                    data_age = int((datetime.now() - snap_dt).total_seconds())
                except Exception:
                    pass

            # 入场价建议（P2）
            entry_info = None
            if kinfo:
                entry_info = {
                    "kline_position_pct": round(kinfo["position"] * 100, 1),
                    "change_5d": round(kinfo["change_5d"], 1),
                    "avg_turnover": round(kinfo["avg_turnover"], 2),
                }

            rec = {
                "stock_code": code,
                "stock_name": data["stock_name"],
                "score": score,
                "reasons": reasons,
                "holding_type": holding,
                "big_order": data.get("big_order"),
                "kline_info": entry_info,
                "data_age_seconds": data_age,
                "data_fresh": data_age is not None and data_age < 120,
                "latest_signal_time": (
                    data["flow_signals"][0]["time"] if data["flow_signals"]
                    else data["strategies"][0]["time"] if data["strategies"]
                    else ""
                ),
            }

            if score >= 60:
                rec["action"] = "BUY"
                buy_list.append(rec)
            elif score <= 35:
                rec["action"] = "SELL"
                sell_list.append(rec)

        # 按分数排序
        buy_list.sort(key=lambda x: x["score"], reverse=True)
        sell_list.sort(key=lambda x: x["score"])

        # P3: 记录推荐日志用于反馈闭环
        try:
            db.execute_update("""
                CREATE TABLE IF NOT EXISTS recommendation_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT, stock_name TEXT, action TEXT,
                    score INTEGER, reasons TEXT,
                    strength REAL, ratio REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            for rec in (buy_list[:5] + sell_list[:5]):
                big = rec.get("big_order") or {}
                db.execute_update("""
                    INSERT INTO recommendation_log
                    (stock_code, stock_name, action, score, reasons, strength, ratio)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    rec["stock_code"], rec["stock_name"], rec.get("action", ""),
                    rec["score"], "|".join(rec.get("reasons", [])),
                    big.get("order_strength"), big.get("buy_sell_ratio"),
                ))
        except Exception as e:
            logger.debug(f"记录推荐日志失败: {e}")

        return APIResponse(success=True, data={
            "buy_recommendations": buy_list[:20],
            "sell_recommendations": sell_list[:20],
            "total_signals": len(stock_data),
            "generated_at": datetime.now().isoformat(),
        })

    except Exception as e:
        logger.error(f"获取推荐列表异常: {e}")
        return APIResponse(success=False, data=None, message=str(e))


@router.get("/{stock_code}", response_model=APIResponse)
async def pre_trade_check(
    stock_code: str,
    trade_type: str = Query("buy"),
    price: float | None = Query(None, description="拟下单价格(可选)，用于追买更贵/成本摊薄判定"),
    container=Depends(get_container),
):
    """
    交易前综合检查：聚合资金流、大单、仲裁、预警等多维度数据，
    给出 GO / CAUTION / STOP 判定。

    trade_type 控制评分方向：
    - buy（建仓）：看多信号利好（加分）。
    - sell（卖出）：看多信号利空（应继续持有、不卖，扣分），方向取反。
    """
    # 规范化股票代码
    if not stock_code.startswith("HK."):
        stock_code = f"HK.{stock_code}"

    is_sell = str(trade_type).lower() == "sell"

    db = getattr(container, 'db_manager', None)
    if not db:
        return APIResponse(success=False, data=None, message="数据库不可用")

    result = {
        "stock_code": stock_code,
        "stock_name": "",
        "verdict": "UNKNOWN",       # GO / CAUTION / STOP
        "verdict_reason": "",
        "score": 0,                  # 0-100, 越高越安全
        "checks": [],                # 各项检查结果
        "capital_flow_signals": [],  # 资金流信号
        "big_order_summary": None,   # 大单摘要
        "arbiter_summary": None,     # 仲裁摘要
        "trade_signals": [],         # 策略信号
        "warnings": [],              # 预警信息
        "holding_strategy": None,    # 持有策略建议
        "intraday": None,            # 日内盘口：追高/洗盘判定
    }

    score = 50  # 基础分
    checks = []
    warnings = []

    # 把"看多强度"按交易方向折算成实际加减分：
    # 买入时看多=利好(加分)，卖出时看多=利空(应继续持有、不卖，扣分)。
    def _signed(bullishness):
        return int(bullishness) if not is_sell else -int(bullishness)

    def _status(signed):
        if signed > 0:
            return "GOOD"
        if signed < 0:
            return "DANGER"
        return "NEUTRAL"

    try:
        # ---- 1. 股票名称 ----
        result["stock_name"] = db.stock_queries.get_stock_name(stock_code)

        # ---- 2. 资金流信号（今日） ----
        flow_rows = db.execute_query("""
            SELECT rule_id, rule_name, signal_type, price, reason,
                   confidence, priority, created_at
            FROM capital_flow_signals
            WHERE stock_code = ? AND date(created_at) = date('now')
            ORDER BY created_at DESC
        """, (stock_code,))

        flow_signals = []
        has_sell_signal = False
        has_buy_signal = False
        has_sustained_inflow = False  # R11: 多日持续流入
        sustained_inflow_reason = ""
        max_sell_conf = 0
        max_buy_conf = 0
        validated_sell = []   # 已回测有边际的卖出/警示规则(R10/R3/R2)命中的 reason

        # 已验证有边际的卖出/警示规则: 逆高减/出货/量价背离
        # 口径: EOD命中率 vs 同股同日随机对照, +19~20pp(到收盘下跌概率约2×随机),
        # retLift +0.4~1.2%; 注意是"偏收盘"边际, 盘中30min内无明显优势(2026-06 复核)
        VALIDATED_SELL_RULES = {"R2", "R3", "R10"}

        # 仅参考规则(回测无边际, 默认 R4/R11/R12)：仍展示在 flow_signals，但不计入评分/门控
        try:
            from ...services.analysis.flow.capital_flow_signal_engine import ADVISORY_RULE_IDS
        except Exception:
            ADVISORY_RULE_IDS = set()

        for r in (flow_rows or []):
            advisory = (r[0] or "").upper() in ADVISORY_RULE_IDS
            sig = {
                "rule_id": r[0], "rule_name": r[1], "signal_type": r[2],
                "price": r[3], "reason": r[4], "confidence": r[5],
                "priority": r[6], "created_at": r[7], "advisory": advisory,
            }
            flow_signals.append(sig)
            if advisory:
                continue  # 仅参考: 不影响 GO/CAUTION/STOP 评分, 也不出持有建议
            if r[2] == "SELL":
                has_sell_signal = True
                max_sell_conf = max(max_sell_conf, float(r[5] or 0))
                if (r[0] or "").upper() in VALIDATED_SELL_RULES:
                    validated_sell.append(f"{r[1]}: {r[4] or ''}")
            elif r[2] == "BUY":
                has_buy_signal = True
                max_buy_conf = max(max_buy_conf, float(r[5] or 0))
                # R11: 资金持续流入信号
                if r[0] == "R11":
                    has_sustained_inflow = True
                    sustained_inflow_reason = r[4] or ""

        result["capital_flow_signals"] = flow_signals

        if validated_sell:
            # 已验证有边际的逆高减/出货/量价背离(R10/R3/R2)单列；诚实表述为概率性偏移
            signed = _signed(-22)
            score += signed
            checks.append({
                "name": "逆高减/出货警示",
                "status": "DANGER",
                "detail": (f"{validated_sell[0][:48]}（回测有边际·偏收盘：到收盘下跌概率"
                           f"≈2×随机、平均多跌~0.5%；盘中30min无即时优势，"
                           f"作逢高减/别追的过滤器，非必跌）"),
                "impact": f"{signed:+d}",
            })
            warnings.append(f"⚠️ 逆高减/出货警示(回测有边际·偏收盘)：{validated_sell[0][:60]}")
            if is_sell:
                warnings.append("（卖出方向：该警示支持你的减仓判断）")
        elif has_sell_signal:
            signed = _signed(-int(max_sell_conf * 30))
            score += signed
            checks.append({
                "name": "资金流卖出信号",
                "status": _status(signed),
                "detail": f"存在 SELL 信号（最高置信度 {max_sell_conf:.0%}）",
                "impact": f"{signed:+d}",
            })
        elif has_buy_signal:
            signed = _signed(int(max_buy_conf * 15))
            score += signed
            checks.append({
                "name": "资金流买入信号",
                "status": _status(signed),
                "detail": f"存在 BUY 信号（最高置信度 {max_buy_conf:.0%}）",
                "impact": f"{signed:+d}",
            })
        else:
            checks.append({
                "name": "资金流信号",
                "status": "NEUTRAL",
                "detail": "今日无资金流信号",
                "impact": "0",
            })

        # ---- 3. 大单追踪（最新快照） ----
        big_rows = db.execute_query("""
            SELECT big_buy_count, big_sell_count, big_buy_amount,
                   big_sell_amount, buy_sell_ratio, order_strength, created_at
            FROM big_order_tracking
            WHERE stock_code = ? AND date(created_at) = date('now')
            ORDER BY created_at DESC LIMIT 1
        """, (stock_code,))

        if big_rows:
            r = big_rows[0]
            strength = float(r[5] or 0)
            ratio = float(r[4] or 0)
            big_summary = {
                "big_buy_count": r[0], "big_sell_count": r[1],
                "big_buy_amount": float(r[2] or 0),
                "big_sell_amount": float(r[3] or 0),
                "buy_sell_ratio": ratio,
                "order_strength": strength,
                "snapshot_time": r[6],
            }
            result["big_order_summary"] = big_summary

            # 评分（strength 即看多强度：正=主力在买，负=主力在卖）
            if strength < -0.2:
                signed = _signed(-int(abs(strength) * 40))
                score += signed
                checks.append({
                    "name": "大单强度",
                    "status": _status(signed),
                    "detail": f"大单强度 {strength:.2f}（主力在卖，买卖比 {ratio:.2f}）",
                    "impact": f"{signed:+d}",
                })
                if signed < 0:
                    warnings.append(f"⚠️ 大单净卖出，强度 {strength:.2f}，主力资金在撤离")
            elif strength < 0.1:
                # 方向不明确：无论买卖，不确定性都是一种风险
                signed = _signed(-5)
                score += signed
                checks.append({
                    "name": "大单强度",
                    "status": "WARNING",
                    "detail": f"大单强度 {strength:.2f}（方向不明确，买卖比 {ratio:.2f}）",
                    "impact": f"{signed:+d}",
                })
                warnings.append(f"⚠️ 大单强度仅 {strength:.2f}，资金方向不明确")
            elif strength >= 0.2:
                signed = _signed(int(strength * 20))
                score += signed
                checks.append({
                    "name": "大单强度",
                    "status": _status(signed),
                    "detail": f"大单强度 {strength:.2f}（主力在买，买卖比 {ratio:.2f}）",
                    "impact": f"{signed:+d}",
                })
                if is_sell and signed < 0:
                    warnings.append(f"⚠️ 大单强度 {strength:.2f}，主力仍在买，卖出可能踏空")
            else:
                checks.append({
                    "name": "大单强度",
                    "status": "NEUTRAL",
                    "detail": f"大单强度 {strength:.2f}（偏弱）",
                    "impact": "0",
                })
        else:
            checks.append({
                "name": "大单追踪",
                "status": "NEUTRAL",
                "detail": "今日无大单数据",
                "impact": "0",
            })

        # ---- 4. 仲裁信号 ----
        try:
            arbiter = getattr(container, 'signal_arbiter', None)
            if arbiter and hasattr(arbiter, 'get_latest_verdict'):
                verdict = arbiter.get_latest_verdict(stock_code)
                if verdict:
                    result["arbiter_summary"] = verdict
                    arb_score = verdict.get('score', 50)
                    if arb_score < 40:
                        signed = _signed(-int((50 - arb_score) * 0.5))
                        score += signed
                        checks.append({
                            "name": "信号仲裁",
                            "status": _status(signed),
                            "detail": f"仲裁评分 {arb_score}（偏空：多{verdict.get('bull',0)}/空{verdict.get('bear',0)}）",
                            "impact": f"{signed:+d}",
                        })
                    elif arb_score >= 60:
                        signed = _signed(int((arb_score - 50) * 0.3))
                        score += signed
                        checks.append({
                            "name": "信号仲裁",
                            "status": _status(signed),
                            "detail": f"仲裁评分 {arb_score}（偏多）",
                            "impact": f"{signed:+d}",
                        })
        except Exception as e:
            logger.debug(f"仲裁查询异常: {e}")

        # ---- 5. 策略信号（今日） ----
        ts_rows = db.execute_query("""
            SELECT ts.signal_type, ts.signal_price, ts.strategy_name,
                   ts.condition_text, ts.created_at
            FROM trade_signals ts
            JOIN stocks s ON ts.stock_id = s.id
            WHERE s.code = ? AND date(ts.created_at) = date('now', 'localtime')
            ORDER BY ts.created_at DESC
        """, (stock_code,))

        trade_signals = []
        for r in (ts_rows or []):
            trade_signals.append({
                "signal_type": r[0], "price": r[1],
                "strategy": r[2], "condition": r[3], "time": r[4],
            })
        result["trade_signals"] = trade_signals

        buy_strategies = [s for s in trade_signals if s["signal_type"] == "BUY"]
        sell_strategies = [s for s in trade_signals if s["signal_type"] == "SELL"]
        if buy_strategies:
            signed = _signed(5)
            score += signed
            checks.append({
                "name": "策略信号",
                "status": _status(signed),
                "detail": f"{len(buy_strategies)} 个策略发出 BUY 信号",
                "impact": f"{signed:+d}",
            })
        if sell_strategies:
            signed = _signed(-10)
            score += signed
            checks.append({
                "name": "策略信号",
                "status": _status(signed),
                "detail": f"{len(sell_strategies)} 个策略发出 SELL 信号",
                "impact": f"{signed:+d}",
            })

        # ---- 5.5 日内盘口：追高(买) / 洗盘(卖) 判定 ----
        # 复用 IntradaySniper 的分钟级 tape，拦"在日内高位接盘"和"在低位恐慌割肉"。
        try:
            sniper = getattr(container, 'intraday_sniper', None)
            tape = sniper.analyze_intraday_tape(stock_code) if sniper else None
        except Exception as e:
            logger.debug(f"日内盘口分析失败: {e}")
            tape = None

        if tape and tape.get("available"):
            result["intraday"] = tape
            if not is_sell:
                # 买入方向：追高风险（评分越高越安全，追高扣分）
                chase = tape.get("chase")
                reason = tape.get("chase_reason", "")
                if chase == "high":
                    score -= 28
                    checks.append({
                        "name": "日内追高", "status": "DANGER",
                        "detail": reason, "impact": "-28",
                    })
                    warnings.append(f"🔴 追高风险：{reason}")
                elif chase == "caution":
                    score -= 10
                    checks.append({
                        "name": "日内追高", "status": "WARNING",
                        "detail": reason, "impact": "-10",
                    })
                    warnings.append(f"🟡 {reason}")
                else:
                    checks.append({
                        "name": "日内位置", "status": "GOOD",
                        "detail": f"日内位置 {tape.get('position_pct')}%，非追高区",
                        "impact": "0",
                    })
            else:
                # 卖出方向：洗盘=不该卖(压低卖出分→STOP)，出货=支持卖出(加分)
                so = tape.get("selloff") or {}
                v_so = so.get("verdict")
                reason = so.get("reason", "")
                if v_so == "shakeout":
                    score -= 22
                    checks.append({
                        "name": "砸盘力度·洗盘", "status": "DANGER",
                        "detail": reason, "impact": "-22",
                    })
                    warnings.append(f"🟢 非卖点(洗盘)：{reason}")
                elif v_so == "distribution":
                    score += 12
                    checks.append({
                        "name": "砸盘力度·出货", "status": "GOOD",
                        "detail": reason, "impact": "+12",
                    })
                    warnings.append(f"🔴 {reason}")
                elif so.get("in_dip"):
                    checks.append({
                        "name": "砸盘力度", "status": "WARNING",
                        "detail": reason, "impact": "0",
                    })

        # ---- 5.6 交易纪律（基于真实富途成交 + 持仓，拦过度交易/反向/追买更贵/成本摊薄）----
        try:
            from ...services.trading.discipline import analyze_discipline, DisciplineThresholds
            tsvc = getattr(container, 'futu_trade_service', None)
            om = getattr(tsvc, 'order_manager', None) if tsvc else None
            today_deals = om.get_today_deals(stock_code).get('deals', []) if om else []
            pos = _find_position(tsvc, stock_code)
            th = DisciplineThresholds()
            guard_cfg = getattr(getattr(container, 'trade_frequency_guard', None), 'config', None)
            if guard_cfg:
                th.overtrade_buys = getattr(guard_cfg, 'max_same_stock_buys', th.overtrade_buys)
                th.reverse_cool_min = getattr(guard_cfg, 'min_rotation_interval_min', th.reverse_cool_min)
                th.min_hold_seconds = getattr(guard_cfg, 'min_hold_seconds', th.min_hold_seconds)
            disc = analyze_discipline(stock_code, trade_type, price, today_deals, pos, th)
            if disc.get("available"):
                result["discipline"] = disc
                for f in disc.get("findings", []):
                    score += int(f.get("impact", 0))
                    checks.append({
                        "name": f["name"], "status": f["status"],
                        "detail": f["detail"], "impact": f"{int(f.get('impact', 0)):+d}",
                    })
                    if f.get("warning"):
                        warnings.append(f["warning"])
        except Exception as e:
            logger.debug(f"交易纪律检查失败: {e}")

        # ---- 6. 预警（提取对当前操作不利的资金流信号） ----
        # 买入：SELL 信号是风险；卖出：BUY 信号(主力仍在买)才是踏空风险
        adverse_type = "BUY" if is_sell else "SELL"
        for sig in flow_signals:
            if sig["signal_type"] == adverse_type:
                warnings.append(
                    f"🔴 {sig['rule_name']}: {sig['reason']}"
                )
            elif sig["signal_type"] == "ALERT":
                warnings.append(
                    f"🟡 {sig['rule_name']}: {sig['reason']}"
                )

        result["warnings"] = warnings

        # ---- 综合判定 ----
        score = max(0, min(100, score))
        result["score"] = score

        if score >= 65:
            result["verdict"] = "GO"
            result["verdict_reason"] = (
                "资金转弱、主力流出，适合卖出落袋" if is_sell
                else "资金面和技术面整体偏多，可以考虑买入"
            )
        elif score >= 40:
            result["verdict"] = "CAUTION"
            result["verdict_reason"] = (
                "信号不够明确，可分批减仓或继续观察" if is_sell
                else "信号不够明确，建议观望或小仓位试探"
            )
        else:
            result["verdict"] = "STOP"
            result["verdict_reason"] = (
                "主力仍在买入、技术面偏多，暂不建议卖出" if is_sell
                else "多个维度发出负面信号，不建议买入"
            )

        # 日内盘口判定优先体现在结论上（更贴近当下该不该动手）：
        # 明确的洗盘 → 卖出硬拦截(STOP，让用户二次确认)；明确的追高顶 → 绝不显示为可买。
        _intra = result.get("intraday") or {}
        if is_sell and (_intra.get("selloff") or {}).get("verdict") == "shakeout":
            result["verdict"] = "STOP"
            result["verdict_reason"] = "日内洗盘有承接、未见巨量出货——非卖点，别被恐慌甩下车"
        elif (not is_sell) and _intra.get("chase") == "high":
            if result["verdict"] == "GO":
                result["verdict"] = "CAUTION"
            result["verdict_reason"] = _intra.get("chase_reason") or result["verdict_reason"]

        # 过度交易（churn）：被反复交易的票，绝不显示为绿色"可买/可卖"
        if (result.get("discipline") or {}).get("churn") and result["verdict"] == "GO":
            result["verdict"] = "CAUTION"
            result["verdict_reason"] = (
                f"今日已在该股成交{result['discipline'].get('trade_count')}笔，"
                + ("先停手别再来回折腾" if not is_sell else "别在来回交易里追涨杀跌")
            )

        result["checks"] = checks

        # ---- 7. 持有策略建议 ----
        big = result.get("big_order_summary")
        current_strength = big["order_strength"] if big else 0

        if has_sustained_inflow:
            result["holding_strategy"] = {
                "type": "reduce_partial" if is_sell else "trailing_stop",
                "label": "分批减仓 + 保留底仓" if is_sell else "持有 + 移动止盈",
                "icon": "🏦",
                "color": "emerald",
                "reason": (
                    "检测到多日持续资金流入，主力中线仍在建仓，不必急于清仓。"
                    "建议分批减仓、保留底仓跟随趋势。"
                    if is_sell else
                    "检测到多日持续资金流入信号，机构中线建仓特征明显。"
                    "建议设置移动止盈（触发6%/回撤2%），不要急于止盈。"
                ),
                "detail": sustained_inflow_reason,
            }
        elif current_strength >= 0.3:
            result["holding_strategy"] = {
                "type": "hold_partial" if is_sell else "swing",
                "label": "暂缓卖出 / 分批" if is_sell else "短线持有（1-3日）",
                "icon": "📈",
                "color": "blue",
                "reason": (
                    f"当前大单强度 {current_strength:.2f} 较强，主力仍在买，"
                    f"可分批减仓、保留部分仓位等待更明确的转弱信号。"
                    if is_sell else
                    f"当前大单强度 {current_strength:.2f} 较强，"
                    f"可短线持有，但需密切关注 strength 变化。"
                ),
                "detail": (
                    "如 strength 跌破 0.1，再考虑加快减仓。" if is_sell
                    else "如 strength 降至 0.1 以下，应立即止盈退出。"
                ),
            }
        elif score >= 40:
            result["holding_strategy"] = {
                "type": "reduce_on_rally" if is_sell else "scalp_only",
                "label": "可逢高减仓" if is_sell else "仅适合超短线",
                "icon": "⚡",
                "color": "amber",
                "reason": (
                    "资金方向不够明确，可在反弹时分批减仓控制风险，不必一次清仓。"
                    if is_sell else
                    "资金方向不够明确，只适合10分钟级别的快进快出。"
                    "一旦盈利2-3%应立即止盈，不要贪。"
                ),
                "detail": (
                    "若随后转弱明显，再加快减仓节奏。" if is_sell
                    else "如果你打算持仓过夜，请等待更强的确认信号。"
                ),
            }
        else:
            result["holding_strategy"] = {
                "type": "exit_all" if is_sell else "no_entry",
                "label": "建议清仓离场" if is_sell else "不建议入场",
                "icon": "🚪" if is_sell else "🚫",
                "color": "red",
                "reason": (
                    "多个维度显示负面信号、主力撤离，建议尽快清仓离场。"
                    if is_sell else
                    "多个维度显示负面信号，无论短线还是中线都不建议买入。"
                ),
                "detail": "",
            }

    except Exception as e:
        logger.error(f"买入前检查异常: {e}")
        return APIResponse(success=False, data=None, message=f"检查异常: {e}")

    return APIResponse(success=True, data=result, message=f"检查完成: {result['verdict']}")
