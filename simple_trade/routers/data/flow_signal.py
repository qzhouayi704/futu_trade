#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资金流向信号路由 — 规则总览 + 信号历史查询
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from ...dependencies import get_container
from ...schemas.common import APIResponse
from ...config.legacy_signal_policy import resolve_legacy_signal_policy

router = APIRouter(prefix="/api/flow-signals", tags=["资金流向信号"])
logger = logging.getLogger("router.flow_signal")


# ========== 规则描述映射（静态数据，与 flow_signal_rules.py 对应） ==========
RULE_DESCRIPTIONS = {
    "R1": {
        "rule_id": "R1",
        "rule_name": "资金净流入建仓",
        "signal_type": "BUY",
        "cooldown": 600,
        "condition": "主力净流入 ≥ 日均成交额3% + 股价处于日内低位（跌幅>1%或接近日低）",
        "suggestion": "分批建仓，散户获利出让中",
        "priority": "high",
    },
    "R2": {
        "rule_id": "R2",
        "rule_name": "资金净流出卖出",
        "signal_type": "SELL",
        "cooldown": 600,
        "condition": "主力净流出 ≥ 日均成交额2% + 涨幅 ≥ 3%",
        "suggestion": "逢高减仓，主力拉高出货中",
        "priority": "high",
    },
    "R3": {
        "rule_id": "R3",
        "rule_name": "流入不足逢高卖",
        "signal_type": "SELL",
        "cooldown": 600,
        "condition": "净流入 < 日均3% + 涨幅 ≥ 2%，上涨动力不足",
        "suggestion": "逢高减仓，上涨动力不足",
        "priority": "medium",
    },
    "R4": {
        "rule_id": "R4",
        "rule_name": "资金转正高抛",
        "signal_type": "ALERT",
        "cooldown": 1800,
        "condition": "资金由负转正但流入 < 日均3%，转正力度不足",
        "suggestion": "次日开盘考虑高抛，转正力度不足",
        "priority": "medium",
    },
    "R5": {
        "rule_id": "R5",
        "rule_name": "大升后平开买入",
        "signal_type": "BUY",
        "cooldown": 3600,
        "condition": "前日涨幅 ≥ 5% + 今日平开（变化 < 1%），获利盘抛压不大",
        "suggestion": "可轻仓买入，日内会有高抛位出手",
        "priority": "medium",
    },
    "R7": {
        "rule_id": "R7",
        "rule_name": "跌破均价线",
        "signal_type": "SELL",
        "cooldown": 900,
        "condition": "价格跌破VWAP持续 ≥ 6个周期未收回",
        "suggestion": "持仓减半或清仓，日内弱势",
        "priority": "high",
    },
    "R10": {
        "rule_id": "R10",
        "rule_name": "量价背离",
        "signal_type": "SELL",
        "cooldown": 900,
        "condition": "价格接近日高（≥98%）+ 成交额 < 日均70%，量价背离",
        "suggestion": "最可靠的阶段性顶部信号，即时减仓",
        "priority": "high",
    },
    "R11": {
        "rule_id": "R11",
        "rule_name": "资金持续流入",
        "signal_type": "BUY",
        "cooldown": 3600,
        "condition": "连续 ≥ 3日资金净流入 + 今日也净流入",
        "suggestion": "可中线持有，资金持续性比绝对值更重要",
        "priority": "medium",
    },
}


def _rules_for_runtime(engine_status: Optional[dict]) -> list:
    """给旧规则附加当前权限，观察模式不再展示操作指令。"""
    mode = (engine_status or {}).get("mode", "active")
    action_enabled = bool((engine_status or {}).get("action_enabled", mode == "active"))
    rules = []
    for item in RULE_DESCRIPTIONS.values():
        rule = dict(item)
        rule["runtime_mode"] = mode
        rule["action_enabled"] = action_enabled
        if not action_enabled:
            rule["legacy_suggestion"] = rule.get("suggestion", "")
            rule["suggestion"] = "仅保留检测与回测样本，不参与当前系统买卖决策"
        rules.append(rule)
    return rules


@router.get("/rules", response_model=APIResponse)
async def get_flow_signal_rules(container=Depends(get_container)):
    """获取所有操盘规则总览"""
    # 尝试从引擎获取运行时状态
    engine_status = None
    try:
        engine = getattr(container, 'capital_flow_signal_engine', None)
        if engine:
            engine_status = engine.get_status()
    except Exception:
        pass

    rules = _rules_for_runtime(engine_status)

    return APIResponse(
        success=True,
        data={
            "rules": rules,
            "engine_enabled": engine_status.get("enabled", False) if engine_status else False,
            "runtime_mode": engine_status.get("mode", "active") if engine_status else "active",
            "action_enabled": engine_status.get("action_enabled", True) if engine_status else True,
            "vwap_tracking": engine_status.get("vwap_tracking", 0) if engine_status else 0,
        },
        message=f"获取 {len(rules)} 条操盘规则",
    )


@router.get("/all-rules", response_model=APIResponse)
async def get_all_trading_rules(container=Depends(get_container)):
    """获取系统全部交易规则（三大体系）"""
    # 1. 资金流向信号规则
    engine_status = None
    try:
        engine = getattr(container, 'capital_flow_signal_engine', None)
        if engine:
            engine_status = engine.get_status()
    except Exception:
        pass

    flow_rules = _rules_for_runtime(engine_status)

    # 2. 风险管理规则（静态描述）
    risk_rules = {
        "basic_rules": [
            {
                "name": "目标止盈",
                "type": "take_profit",
                "description": "盈利达到目标值时自动卖出",
                "default_value": "8%",
                "urgency": 8,
                "liquidity_adaptive": {
                    "A": "6%", "B": "8%", "C": "10%"
                },
            },
            {
                "name": "移动止盈",
                "type": "trailing_take_profit",
                "description": "盈利≥触发值后，从高点回撤超过阈值时卖出",
                "default_value": "触发6% / 回撤2%",
                "urgency": 7,
                "liquidity_adaptive": {
                    "A": "触发5% / 回撤1.5%",
                    "B": "触发6% / 回撤2%",
                    "C": "触发8% / 回撤3%",
                },
            },
            {
                "name": "固定止损",
                "type": "stop_loss",
                "description": "亏损超过阈值时强制卖出",
                "default_value": "-5%",
                "urgency": 10,
                "liquidity_adaptive": {
                    "A": "-4%", "B": "-5%", "C": "-7%"
                },
            },
            {
                "name": "快速止损",
                "type": "quick_stop_loss",
                "description": "亏损≥3%且板块走弱(排名>5或强度<70)时卖出",
                "default_value": "-3% + 板块弱势",
                "urgency": 9,
                "liquidity_adaptive": None,
            },
            {
                "name": "板块止损",
                "type": "plate_stop_loss",
                "description": "板块跌出强势排名时卖出",
                "default_value": "排名>5",
                "urgency": 6,
                "liquidity_adaptive": None,
            },
            {
                "name": "时间止损",
                "type": "time_stop_loss",
                "description": "持有超过N天且盈利未达标时卖出",
                "default_value": "1天 / 2%",
                "urgency": 5,
                "liquidity_adaptive": None,
            },
        ],
        "coordinator_levels": [
            {"priority": 1, "name": "PriceMonitorService", "description": "目标价买卖监控", "urgency": 9},
            {"priority": 2, "name": "DynamicStopLossStrategy", "description": "动态止损（五维度自适应）", "urgency": 8},
            {"priority": 3, "name": "LotTakeProfitService", "description": "分仓止盈", "urgency": 7},
            {"priority": 4, "name": "LotOrderTakeProfitService", "description": "单笔订单止盈", "urgency": 6},
            {"priority": 5, "name": "ScreeningEngine", "description": "策略趋势止损", "urgency": 5},
        ],
        "dynamic_stop_loss": {
            "dimensions": [
                {"name": "市场热度", "weight": "30%", "description": "热度高放宽止损，低收紧"},
                {"name": "资金流向", "weight": "25%", "description": "流入放宽，流出收紧"},
                {"name": "大单强度", "weight": "20%", "description": "买入放宽，卖出收紧"},
                {"name": "换手率", "weight": "10%", "description": "异常高收紧，极度缩量放宽"},
                {"name": "流动性等级", "weight": "15%", "description": "A级收紧止损，C级放宽止损"},
            ],
            "safety_bounds": {
                "swing": {"stop_loss": "-2%~-8%（B级）", "take_profit": "5%~12%（B级）"},
                "intraday": {"stop_loss": "-1%~-3%", "take_profit": "N/A"},
            },
            "liquidity_bounds": {
                "A": {"stop_loss": "-2%~-6%", "take_profit": "4%~10%", "label": "高流动性"},
                "B": {"stop_loss": "-2%~-8%", "take_profit": "5%~12%", "label": "中等流动性"},
                "C": {"stop_loss": "-3%~-10%", "take_profit": "6%~15%", "label": "低流动性"},
            },
        },
    }

    # 3. 趋势反转策略规则（从策略服务获取，fallback 静态数据）
    strategy_rules = _get_strategy_rules(container)

    return APIResponse(
        success=True,
        data={
            "flow_rules": flow_rules,
            "risk_rules": risk_rules,
            "strategy_rules": strategy_rules,
            "engine_enabled": engine_status.get("enabled", False) if engine_status else False,
        },
        message="获取全部交易规则成功",
    )


def _get_strategy_rules(container) -> dict:
    """获取策略规则，优先从 strategy_monitor_service 获取，fallback 静态数据"""
    try:
        sms = getattr(container, 'strategy_monitor_service', None)
        if sms:
            indicators = sms.get_strategy_indicators()
            if indicators:
                return {
                    "strategy_name": indicators.get('strategy_name', '趋势反转策略'),
                    "preset_name": indicators.get('preset_name', ''),
                    "buy_conditions": indicators.get('buy_conditions', []),
                    "sell_conditions": indicators.get('sell_conditions', []),
                    "stop_loss_conditions": indicators.get('stop_loss_conditions', []),
                    "parameters": indicators.get('parameters', {}),
                }
    except Exception as e:
        logger.warning(f"获取策略指标失败，使用静态数据: {e}")

    # Fallback 静态数据
    return {
        "strategy_name": "趋势反转策略",
        "preset_name": "",
        "buy_conditions": [
            "近10日下跌天数占比 ≥ 60%",
            "【核心】距期间最高点跌幅 ≥ 8%",
            "【核心】反弹信号（距最低点涨幅）≥ 2%",
            "今日K线为阳线（反转确认）",
            "反弹日成交量 ≥ 下跌日均量 × 1.2（放量确认）",
            "换手率 ≥ 0.1%（流动性确认）",
        ],
        "sell_conditions": [
            "近10日上涨天数占比 ≥ 60%",
            "【核心】距期间最低点涨幅 ≥ 10%",
            "【核心】回落信号（距最高点跌幅）≥ 2%",
            "今日K线为阴线（反转确认）",
        ],
        "stop_loss_conditions": [
            "固定止损：收益率 ≤ -10%",
            "市场环境加速止损：大盘跌>2%时阈值收紧50%",
            "T+5趋势未延续：持有5天后收益为负且阳线<1天",
            "追踪止盈：涨幅≥8%激活，从峰值回撤3%卖出",
            "高抛兜底：今日最高<昨日最高且昨日最高=近期最高",
            "超时退出：持有≥15天",
        ],
        "parameters": {
            "lookback_days": 10, "min_drop_pct": 8.0, "min_rise_pct": 10.0,
            "min_reversal_pct": 2.0, "stop_loss_pct": -10.0, "stop_loss_days": 5,
        },
    }

@router.get("/history", response_model=APIResponse)
async def get_flow_signal_history(
    limit: int = Query(50, ge=1, le=200, description="返回数量"),
    signal_type: Optional[str] = Query(None, description="信号类型: BUY/SELL/ALERT"),
    stock_code: Optional[str] = Query(None, description="股票代码过滤"),
    container=Depends(get_container),
):
    """查询信号触发历史"""
    db = getattr(container, 'db_manager', None)
    if not db:
        return APIResponse(success=True, data={"signals": [], "total": 0}, message="数据库不可用")

    # 构建查询
    where_clauses = []
    params = []

    if signal_type:
        where_clauses.append("signal_type = ?")
        params.append(signal_type.upper())

    if stock_code:
        where_clauses.append("stock_code = ?")
        params.append(stock_code)

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    try:
        legacy_policy = resolve_legacy_signal_policy()
        # 查询总数
        count_rows = db.execute_query(
            f"SELECT COUNT(*) FROM capital_flow_signals{where_sql}",
            tuple(params),
        )
        total = count_rows[0][0] if count_rows else 0

        # 查询记录（按 stock_code + rule_id + 分钟级时间 去重）
        rows = db.execute_query(
            f"""SELECT MIN(id), rule_id, rule_name, stock_code, stock_name,
                       signal_type, price, reason, confidence,
                       priority, action_suggestion, created_at
                FROM capital_flow_signals{where_sql}
                GROUP BY stock_code, rule_id, strftime('%Y-%m-%d %H:%M', created_at)
                ORDER BY created_at DESC LIMIT ?""",
            tuple(params) + (limit,),
        )

        signals = []
        for r in (rows or []):
            signal = {
                "id": r[0],
                "rule_id": r[1],
                "rule_name": r[2],
                "stock_code": r[3],
                "stock_name": r[4],
                "signal_type": r[5],
                "price": r[6],
                "reason": r[7],
                "confidence": r[8],
                "priority": r[9],
                "action_suggestion": r[10],
                "created_at": r[11],
                "advisory": not legacy_policy.action_enabled,
                "runtime_mode": legacy_policy.mode.value,
            }
            if not legacy_policy.action_enabled:
                signal["legacy_action_suggestion"] = signal["action_suggestion"]
                signal["action_suggestion"] = "历史样本，仅供复盘，不参与当前买卖决策"
            signals.append(signal)

        return APIResponse(
            success=True,
            data={"signals": signals, "total": total},
            message=f"获取 {len(signals)} 条信号记录",
        )
    except Exception as e:
        logger.warning(f"查询信号历史失败: {e}")
        return APIResponse(
            success=True,
            data={"signals": [], "total": 0},
            message="信号表尚未创建或为空（系统启动后会自动创建）",
        )


@router.get("/today-batch", response_model=APIResponse)
async def get_today_signals_batch(container=Depends(get_container)):
    """获取当天所有信号，按股票代码分组（供市场扫描页面使用）"""
    db = getattr(container, 'db_manager', None)
    if not db:
        return APIResponse(success=True, data={}, message="数据库不可用")

    try:
        legacy_policy = resolve_legacy_signal_policy()
        # 每个股票每条规则只保留最新一条（避免同一天同一规则的矛盾信号堆叠）
        rows = db.execute_query("""
            SELECT rule_id, rule_name, stock_code, stock_name,
                   signal_type, price, reason, confidence,
                   priority, action_suggestion, MAX(created_at) as created_at
            FROM capital_flow_signals
            WHERE date(created_at) = date('now')
            GROUP BY stock_code, rule_id
            ORDER BY created_at DESC
        """)

        # 按股票代码分组（已按时间倒序，最新信号在前）
        signals_by_stock = {}
        for r in (rows or []):
            code = r[2]
            if code not in signals_by_stock:
                signals_by_stock[code] = []
            signal = {
                "rule_id": r[0],
                "rule_name": r[1],
                "signal_type": r[4],
                "price": r[5],
                "reason": r[6],
                "confidence": r[7],
                "priority": r[8],
                "action_suggestion": r[9],
                "created_at": r[10],
                "advisory": not legacy_policy.action_enabled,
                "runtime_mode": legacy_policy.mode.value,
            }
            if not legacy_policy.action_enabled:
                signal["legacy_action_suggestion"] = signal["action_suggestion"]
                signal["action_suggestion"] = "历史样本，仅供复盘，不参与当前买卖决策"
            signals_by_stock[code].append(signal)

        # 冲突解决：同一只股票有 BUY 和 SELL 时，只保留最新方向的信号
        for code, signals in signals_by_stock.items():
            types = {s["signal_type"] for s in signals}
            if "BUY" in types and "SELL" in types:
                # 最新信号在前（ORDER BY created_at DESC），取其方向
                latest_type = signals[0]["signal_type"]
                signals_by_stock[code] = [
                    s for s in signals
                    if s["signal_type"] == latest_type or s["signal_type"] == "ALERT"
                ]

        return APIResponse(
            success=True,
            data=signals_by_stock,
            message=f"获取 {sum(len(v) for v in signals_by_stock.values())} 条当日信号",
        )
    except Exception as e:
        logger.warning(f"查询当日批量信号失败: {e}")
        return APIResponse(success=True, data={}, message="信号表尚未创建")


@router.get("/trade-signals-batch", response_model=APIResponse)
async def get_trade_signals_batch(container=Depends(get_container)):
    """获取当天所有日线级策略信号（按股票代码分组）

    供市场扫描页面"判定"列使用，策略信号优先级高于 QuickScan。
    """
    db = getattr(container, 'db_manager', None)
    if not db:
        return APIResponse(success=True, data={}, message="数据库不可用")

    legacy_policy = resolve_legacy_signal_policy()
    if not legacy_policy.action_enabled:
        return APIResponse(
            success=True,
            data={},
            message="旧版日线策略已转为观察模式，请使用 V2 决策结果",
        )

    try:
        rows = db.execute_query("""
            SELECT ts.signal_type, ts.signal_price, ts.condition_text,
                   ts.strategy_id, ts.strategy_name, ts.created_at,
                   s.code, s.name
            FROM trade_signals ts
            JOIN stocks s ON ts.stock_id = s.id
            WHERE DATE(ts.created_at) = DATE('now', 'localtime')
              AND ts.id IN (
                  SELECT MAX(id) FROM trade_signals
                  WHERE DATE(created_at) = DATE('now', 'localtime')
                  GROUP BY stock_id, signal_type, COALESCE(strategy_id, '')
              )
            ORDER BY ts.created_at DESC
        """)

        signals_by_stock = {}
        for r in (rows or []):
            code = r[6]
            if code not in signals_by_stock:
                signals_by_stock[code] = []
            signals_by_stock[code].append({
                "signal_type": r[0],
                "signal_price": r[1],
                "condition_text": r[2],
                "strategy_id": r[3] or "",
                "strategy_name": r[4] or r[3] or "",
                "created_at": r[5],
                "stock_name": r[7],
            })

        # 冲突解决：同一只股票有 BUY 和 SELL 时，只保留最新方向
        for code, signals in signals_by_stock.items():
            types = {s["signal_type"] for s in signals}
            if "BUY" in types and "SELL" in types:
                latest_type = signals[0]["signal_type"]
                signals_by_stock[code] = [
                    s for s in signals if s["signal_type"] == latest_type
                ]

        return APIResponse(
            success=True,
            data=signals_by_stock,
            message=f"获取 {len(signals_by_stock)} 只股票的策略信号",
        )
    except Exception as e:
        logger.warning(f"查询当日策略信号失败: {e}")
        return APIResponse(success=True, data={}, message="信号表尚未创建")


logging.info("资金流向信号路由已注册")
