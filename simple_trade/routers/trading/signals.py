#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多维信号及拦截信号 API 路由
"""

import json
import logging
from datetime import date, datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, Query

from ...dependencies import get_container
from ...core.exceptions import BusinessError
from ...services.trading.decision.models import TradeSignalEvent

logger = logging.getLogger("signals_router")

router = APIRouter(prefix="/api/signals", tags=["多维信号"])


def get_single_stock_multi_dimensional(stock_code: str, container) -> Dict[str, Any]:
    """获取单只股票的三维信号聚合"""
    # 1. 基础信息获取
    price = 0.0
    quote_cache = getattr(container, 'quote_cache', None)
    if quote_cache:
        try:
            quotes = quote_cache.get_quotes_for_codes([stock_code])
            if stock_code in quotes:
                price = quotes[stock_code].get('price', 0.0)
        except Exception:
            pass

    stock_name = stock_code
    db = getattr(container, 'db_manager', None)
    if db:
        try:
            rows = db.execute_query("SELECT name FROM stocks WHERE code=?", (stock_code,))
            if rows:
                stock_name = rows[0][0]
        except Exception:
            pass

    # 2. V1 Sniper
    v1_data = None
    sniper = getattr(container, 'intraday_sniper', None)
    if sniper:
        try:
            stock_sigs = [s for s in sniper._today_signals if s.stock_code == stock_code]
            if stock_sigs:
                latest = stock_sigs[-1]
                ranking = 0
                for idx, r in enumerate(sniper._top_ranking.get('opportunity', [])):
                    if r['stock_code'] == stock_code:
                        ranking = idx + 1
                        break
                v1_data = {
                    "strength": latest.strength,
                    "label": latest.strength_label,
                    "ranking": ranking,
                    "signal_types": list(set(s.signal_type for s in stock_sigs))
                }
        except Exception as e:
            logger.debug(f"获取 V1 信号异常: {e}")

    # 3. V2 Scorer
    v2_data = None
    scorer = getattr(container, 'stock_scorer', None)
    if scorer:
        try:
            cached = scorer.get_score(stock_code)
            if cached:
                details = []
                for d in cached.details:
                    details.append({
                        "name": d.dimension,
                        "score": d.score,
                        "max": d.max_score
                    })
                v2_data = {
                    "score": cached.total_score,
                    "mode": getattr(cached, 'mode', 'TREND'),
                    "details": details
                }
        except Exception as e:
            logger.debug(f"获取 V2 评分异常: {e}")

    # 4. Momentum Engine
    m_data = None
    momentum = getattr(container, 'momentum_engine', None)
    if momentum and hasattr(momentum, 'resonance_detector'):
        try:
            detector = momentum.resonance_detector
            recent = detector._recent_signals.get(stock_code, {})
            dimensions = []
            for sig_type in recent.keys():
                if sig_type in ('BUY_MOMENTUM', 'RECOVERY', 'SELL_MOMENTUM', 'EXHAUSTION'):
                    dimensions.append('BSR')
                elif sig_type in ('DELTA_TURN_UP', 'DELTA_TURN_DOWN', 'BULLISH_DIVERGENCE', 'BEARISH_DIVERGENCE'):
                    dimensions.append('Delta')
                elif sig_type in ('ACCELERATE_BUY', 'ACCELERATE_SELL'):
                    dimensions.append('Velocity')
                elif sig_type in ('BIG_BUY_CLUSTER', 'BIG_SELL_CLUSTER'):
                    dimensions.append('BigOrder')
                elif sig_type in ('VWAP_BOUNCE', 'VWAP_BREAK'):
                    dimensions.append('VWAP')
                elif sig_type in ('ACCUMULATION', 'DISTRIBUTION'):
                    dimensions.append('Absorption')
            dimensions = list(set(dimensions))

            # 提取数据库最新共振判决
            verdict = None
            if db:
                rows = db.execute_query(
                    """SELECT strategy_id FROM trade_signals
                       WHERE stock_id = (SELECT id FROM stocks WHERE code=?)
                       AND strategy_name = '动量引擎'
                       ORDER BY id DESC LIMIT 1""",
                    (stock_code,)
                )
                if rows:
                    strategy_id = rows[0][0]
                    if strategy_id.startswith("momentum_"):
                        verdict = strategy_id.replace("momentum_", "")

            if verdict or dimensions:
                m_data = {
                    "verdict": verdict or "WATCH",
                    "resonance_count": len(dimensions),
                    "dimensions": dimensions
                }
        except Exception as e:
            logger.debug(f"获取动量引擎信号异常: {e}")

    # 5. 三维共识计算
    triggered_count = 0
    is_v1_buy = v1_data is not None and v1_data["strength"] >= 40
    is_v2_buy = v2_data is not None and v2_data["score"] >= 60
    is_m_buy = m_data is not None and m_data["verdict"] in ('STRONG_BUY', 'MODERATE_BUY')

    if is_v1_buy: triggered_count += 1
    if is_v2_buy: triggered_count += 1
    if is_m_buy: triggered_count += 1

    consensus_verdict = 'WATCH'
    if triggered_count == 3:
        consensus_verdict = 'STRONG_BUY'
    elif triggered_count == 2:
        consensus_verdict = 'BUY'
    elif triggered_count == 1:
        consensus_verdict = 'WATCH'

    is_v1_sell = v1_data is not None and any(t in ('mega_sell', 'sustained_out', 'reversal_bear') for t in v1_data["signal_types"])
    is_m_sell = m_data is not None and m_data["verdict"] in ('STRONG_SELL', 'MODERATE_SELL')
    if is_v1_sell or is_m_sell:
        consensus_verdict = 'SELL'

    confidence = 0.5
    if consensus_verdict == 'STRONG_BUY':
        confidence = 0.85
    elif consensus_verdict == 'BUY':
        confidence = 0.70
    elif consensus_verdict == 'SELL':
        confidence = 0.80

    consensus = {
        "verdict": consensus_verdict,
        "confidence": confidence,
        "triggered_dimensions": triggered_count
    }

    return {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "current_price": price,
        "v1_sniper": v1_data,
        "v2_scorer": v2_data,
        "momentum_engine": m_data,
        "consensus": consensus
    }


@router.get("/multi-dimensional/{stock_code}")
async def get_multi_dimensional_signal(stock_code: str, container=Depends(get_container)):
    """获取单只股票的三维信号聚合状态"""
    try:
        data = get_single_stock_multi_dimensional(stock_code, container)
        return {
            "success": True,
            "data": data
        }
    except Exception as e:
        logger.error(f"获取单股多维信号失败: {e}")
        raise BusinessError(message=f"获取单股多维信号失败: {str(e)}")


@router.get("/multi-dimensional/list")
async def get_multi_dimensional_signal_list(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    container=Depends(get_container)
):
    """获取今日所有产生过信号股票的多维聚合列表"""
    try:
        stock_codes = set()

        # 1. V1
        sniper = getattr(container, 'intraday_sniper', None)
        if sniper:
            stock_codes.update(s.stock_code for s in sniper._today_signals)

        # 2. V2
        scorer = getattr(container, 'stock_scorer', None)
        if scorer:
            stock_codes.update(scorer._scored_cache.keys())

        # 3. Momentum
        momentum = getattr(container, 'momentum_engine', None)
        if momentum and hasattr(momentum, 'resonance_detector'):
            stock_codes.update(momentum.resonance_detector._recent_signals.keys())

        # 4. 从 DB 获取今日有信号的其它股票（兜底）
        db = getattr(container, 'db_manager', None)
        if db:
            try:
                today = date.today().isoformat()
                rows = db.execute_query(
                    "SELECT DISTINCT stock_code FROM sniper_signals WHERE trade_date = ?",
                    (today,)
                )
                stock_codes.update(r[0] for r in rows)
            except Exception:
                pass

        stock_list = sorted(list(stock_codes))
        total = len(stock_list)

        # 分页
        start = (page - 1) * limit
        end = start + limit
        paginated_codes = stock_list[start:end]

        results = []
        for code in paginated_codes:
            results.append(get_single_stock_multi_dimensional(code, container))

        return {
            "success": True,
            "data": {
                "total": total,
                "page": page,
                "limit": limit,
                "list": results
            }
        }
    except Exception as e:
        logger.error(f"获取多维信号列表失败: {e}")
        raise BusinessError(message=f"获取多维信号列表失败: {str(e)}")


@router.get("/rejected")
async def get_rejected_signals(
    limit: int = Query(50, ge=1, le=200),
    date_str: str = Query("", description="日期 YYYY-MM-DD，默认今天"),
    container=Depends(get_container)
):
    """获取被拦截的交易信号记录（final_action = 'rejected'）"""
    try:
        db = getattr(container, 'db_manager', None)
        if not db:
            return {"success": False, "message": "数据库未挂载", "data": []}

        if not date_str:
            date_str = date.today().isoformat()

        rows = db.execute_query(
            '''SELECT id, trade_date, timestamp, stock_code, stock_name,
                      source, direction, strength, resonance_result,
                      guard_result, final_action, final_reason, raw_detail
               FROM signal_pipeline
               WHERE trade_date = ? AND final_action = 'rejected'
               ORDER BY id DESC LIMIT ?''',
            (date_str, limit),
        )

        records = []
        for r in rows:
            records.append({
                'id': r[0], 'trade_date': r[1], 'timestamp': r[2],
                'stock_code': r[3], 'stock_name': r[4],
                'source': r[5], 'direction': r[6], 'strength': r[7],
                'resonance': json.loads(r[8]) if r[8] else {},
                'guard': json.loads(r[9]) if r[9] else {},
                'final_action': r[10], 'final_reason': r[11],
                'raw_detail': json.loads(r[12]) if r[12] else {},
            })

        return {
            "success": True,
            "data": records
        }
    except Exception as e:
        logger.error(f"获取拦截信号列表失败: {e}")
        raise BusinessError(message=f"获取拦截信号列表失败: {str(e)}")
