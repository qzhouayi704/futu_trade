#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
买入前快速检查 API
输入股票代码，秒出资金面评分 + GO/CAUTION/STOP 综合判定
"""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends

from ...dependencies import get_container
from ...schemas.common import APIResponse

router = APIRouter(prefix="/api/pre-trade-check", tags=["买入前检查"])
logger = logging.getLogger("router.pre_trade_check")


@router.get("/recommendations", response_model=APIResponse)
async def get_recommendations(container=Depends(get_container)):
    """
    获取当前所有适合买入/卖出的股票推荐列表。
    聚合资金流信号、大单追踪、策略信号，按评分排序。
    """
    db = getattr(container, 'db_manager', None)
    if not db:
        return APIResponse(success=False, data=None, message="数据库不可用")

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
                name = ""
                try:
                    name_row = db.execute_query(
                        "SELECT name FROM stocks WHERE code = ?", (code,)
                    )
                    name = name_row[0][0] if name_row else ""
                except Exception:
                    pass
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
async def pre_trade_check(stock_code: str, container=Depends(get_container)):
    """
    买入前综合检查：聚合资金流、大单、仲裁、预警等多维度数据，
    给出 GO / CAUTION / STOP 判定。
    """
    # 规范化股票代码
    if not stock_code.startswith("HK."):
        stock_code = f"HK.{stock_code}"

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
    }

    score = 50  # 基础分
    checks = []
    warnings = []

    try:
        # ---- 1. 股票名称 ----
        name_rows = db.execute_query(
            "SELECT name FROM stocks WHERE code = ? LIMIT 1", (stock_code,)
        )
        if name_rows:
            result["stock_name"] = name_rows[0][0]

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

        for r in (flow_rows or []):
            sig = {
                "rule_id": r[0], "rule_name": r[1], "signal_type": r[2],
                "price": r[3], "reason": r[4], "confidence": r[5],
                "priority": r[6], "created_at": r[7],
            }
            flow_signals.append(sig)
            if r[2] == "SELL":
                has_sell_signal = True
                max_sell_conf = max(max_sell_conf, float(r[5] or 0))
            elif r[2] == "BUY":
                has_buy_signal = True
                max_buy_conf = max(max_buy_conf, float(r[5] or 0))
                # R11: 资金持续流入信号
                if r[0] == "R11":
                    has_sustained_inflow = True
                    sustained_inflow_reason = r[4] or ""

        result["capital_flow_signals"] = flow_signals

        if has_sell_signal:
            penalty = int(max_sell_conf * 30)
            score -= penalty
            checks.append({
                "name": "资金流卖出信号",
                "status": "DANGER",
                "detail": f"存在 SELL 信号（最高置信度 {max_sell_conf:.0%}）",
                "impact": f"-{penalty}",
            })
        elif has_buy_signal:
            bonus = int(max_buy_conf * 15)
            score += bonus
            checks.append({
                "name": "资金流买入信号",
                "status": "GOOD",
                "detail": f"存在 BUY 信号（最高置信度 {max_buy_conf:.0%}）",
                "impact": f"+{bonus}",
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

            # 评分
            if strength < -0.2:
                penalty = int(abs(strength) * 40)
                score -= penalty
                checks.append({
                    "name": "大单强度",
                    "status": "DANGER",
                    "detail": f"大单强度 {strength:.2f}（主力在卖，买卖比 {ratio:.2f}）",
                    "impact": f"-{penalty}",
                })
                warnings.append(f"⚠️ 大单净卖出，强度 {strength:.2f}，主力资金在撤离")
            elif strength < 0.1:
                checks.append({
                    "name": "大单强度",
                    "status": "WARNING",
                    "detail": f"大单强度 {strength:.2f}（方向不明确，买卖比 {ratio:.2f}）",
                    "impact": "-5",
                })
                score -= 5
                warnings.append(f"⚠️ 大单强度仅 {strength:.2f}，资金方向不明确")
            elif strength >= 0.2:
                bonus = int(strength * 20)
                score += bonus
                checks.append({
                    "name": "大单强度",
                    "status": "GOOD",
                    "detail": f"大单强度 {strength:.2f}（主力在买，买卖比 {ratio:.2f}）",
                    "impact": f"+{bonus}",
                })
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
                        penalty = int((50 - arb_score) * 0.5)
                        score -= penalty
                        checks.append({
                            "name": "信号仲裁",
                            "status": "DANGER",
                            "detail": f"仲裁评分 {arb_score}（偏空：多{verdict.get('bull',0)}/空{verdict.get('bear',0)}）",
                            "impact": f"-{penalty}",
                        })
                    elif arb_score >= 60:
                        bonus = int((arb_score - 50) * 0.3)
                        score += bonus
                        checks.append({
                            "name": "信号仲裁",
                            "status": "GOOD",
                            "detail": f"仲裁评分 {arb_score}（偏多）",
                            "impact": f"+{bonus}",
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
            score += 5
            checks.append({
                "name": "策略信号",
                "status": "GOOD",
                "detail": f"{len(buy_strategies)} 个策略发出 BUY 信号",
                "impact": "+5",
            })
        if sell_strategies:
            score -= 10
            checks.append({
                "name": "策略信号",
                "status": "DANGER",
                "detail": f"{len(sell_strategies)} 个策略发出 SELL 信号",
                "impact": "-10",
            })

        # ---- 6. 预警（从日志/信号提取跌幅预警） ----
        # 检查该股是否有资金流卖出的特定规则
        for sig in flow_signals:
            if sig["signal_type"] == "SELL":
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
            result["verdict_reason"] = "资金面和技术面整体偏多，可以考虑买入"
        elif score >= 40:
            result["verdict"] = "CAUTION"
            result["verdict_reason"] = "信号不够明确，建议观望或小仓位试探"
        else:
            result["verdict"] = "STOP"
            result["verdict_reason"] = "多个维度发出负面信号，不建议买入"

        result["checks"] = checks

        # ---- 7. 持有策略建议 ----
        big = result.get("big_order_summary")
        current_strength = big["order_strength"] if big else 0

        if has_sustained_inflow:
            result["holding_strategy"] = {
                "type": "trailing_stop",
                "label": "持有 + 移动止盈",
                "icon": "🏦",
                "color": "emerald",
                "reason": f"检测到多日持续资金流入信号，机构中线建仓特征明显。"
                          f"建议设置移动止盈（触发6%/回撤2%），不要急于止盈。",
                "detail": sustained_inflow_reason,
            }
        elif current_strength >= 0.3:
            result["holding_strategy"] = {
                "type": "swing",
                "label": "短线持有（1-3日）",
                "icon": "📈",
                "color": "blue",
                "reason": f"当前大单强度 {current_strength:.2f} 较强，"
                          f"可短线持有，但需密切关注 strength 变化。",
                "detail": "如 strength 降至 0.1 以下，应立即止盈退出。",
            }
        elif score >= 40:
            result["holding_strategy"] = {
                "type": "scalp_only",
                "label": "仅适合超短线",
                "icon": "⚡",
                "color": "amber",
                "reason": "资金方向不够明确，只适合10分钟级别的快进快出。"
                          "一旦盈利2-3%应立即止盈，不要贪。",
                "detail": "如果你打算持仓过夜，请等待更强的确认信号。",
            }
        else:
            result["holding_strategy"] = {
                "type": "no_entry",
                "label": "不建议入场",
                "icon": "🚫",
                "color": "red",
                "reason": "多个维度显示负面信号，无论短线还是中线都不建议买入。",
                "detail": "",
            }

    except Exception as e:
        logger.error(f"买入前检查异常: {e}")
        return APIResponse(success=False, data=None, message=f"检查异常: {e}")

    return APIResponse(success=True, data=result, message=f"检查完成: {result['verdict']}")
