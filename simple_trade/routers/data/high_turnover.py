#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
活跃个股路由 - 高换手率股票排行

提供按换手率排序的活跃股票列表 API，
复用 state_manager 中的实时报价缓存数据。
"""

import asyncio
import logging
from dataclasses import asdict
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query

from ...core import get_state_manager
from ...dependencies import get_container
from ...schemas.common import APIResponse
from .helpers.ticker_summary_builder import build_ticker_summary


router = APIRouter(prefix="/api", tags=["活跃个股"])
logger = logging.getLogger(__name__)

# ==================== 批量分析配置 ====================

MAX_CONCURRENT_ANALYSIS = 10
"""并发分析上限"""

SINGLE_ANALYSIS_TIMEOUT = 5
"""单只股票分析超时（秒）"""

VOLUME_RATIO_KLINE_DAYS = 5
"""量比计算使用的历史K线天数"""


# ==================== 批量分析函数 ====================


async def batch_ticker_analysis(
    stock_codes: list[str],
    container,
) -> dict[str, dict | None]:
    """批量获取成交分析摘要

    使用 Semaphore 控制并发上限，每只股票设置独立超时。
    任何单只股票分析失败不影响其他股票结果。

    Args:
        stock_codes: 股票代码列表
        container: 服务容器

    Returns:
        {stock_code: ticker_summary_dict | None}，长度等于输入列表长度
    """
    if not stock_codes:
        return {}

    from .ticker.helpers import get_ticker_analyzer
    analyzer = get_ticker_analyzer(container)

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_ANALYSIS)
    results: dict[str, dict | None] = {}

    async def analyze_one(code: str):
        async with semaphore:
            try:
                analysis = await asyncio.wait_for(
                    analyzer.analyze(code),
                    timeout=SINGLE_ANALYSIS_TIMEOUT,
                )
                summary = build_ticker_summary(analysis)
                results[code] = asdict(summary) if summary else None
            except asyncio.TimeoutError:
                logger.warning(f"成交分析超时 {code}")
                results[code] = None
            except Exception as e:
                logger.warning(f"成交分析失败 {code}: {e}")
                results[code] = None

    await asyncio.gather(*[analyze_one(code) for code in stock_codes])
    return results


@router.get("/stocks/high-turnover", response_model=APIResponse)
async def get_high_turnover_stocks(
    limit: int = Query(50, ge=1, le=200, description="返回数量限制"),
    market: Optional[str] = Query(None, description="市场过滤(HK/US)"),
    min_turnover_rate: float = Query(0, ge=0, description="最低换手率阈值"),
    min_liquidity_score: Optional[float] = Query(None, ge=0, le=100, description="最低流动性评分"),
    liquidity_level: Optional[str] = Query(None, regex="^(A|B|C)$", description="流动性等级筛选(A/B/C)"),
    search: Optional[str] = Query(None, description="搜索关键词(代码/名称)"),
    include_ticker_analysis: bool = Query(False, description="是否附加成交分析摘要"),
    container=Depends(get_container),
):
    """获取按换手率排序的活跃股票列表"""
    state = get_state_manager()

    # 获取持仓股票列表
    query_service = container.hot_stock_query_service
    position_codes = query_service.get_position_codes(
        futu_trade_service=getattr(container, 'futu_trade_service', None)
    )

    # 获取自选股列表（与持仓同等对待：不过滤、始终显示）
    watchlist_codes = getattr(state, 'get_watchlist', lambda: set())()
    protected_codes = position_codes | watchlist_codes

    # 获取实时报价缓存
    cached_quotes = state.get_cached_quotes()
    if not cached_quotes:
        return APIResponse(
            success=True,
            data={"stocks": [], "total": 0, "update_time": None},
            message="实时报价数据未就绪，请稍后再试",
        )

    # 构建报价映射
    quotes_map = {q["code"]: q for q in cached_quotes if isinstance(q, dict) and q.get("code")}

    # 获取股票池基础信息，用于补充 name/market
    pool_data = state.get_stock_pool()
    stocks_data = pool_data.get("stocks", [])
    stocks_info_map = {s["code"]: s for s in stocks_data if isinstance(s, dict) and s.get("code")}

    # 确保受保护股票（持仓+自选）存在于 quotes_map 中
    missing_protected = protected_codes - set(quotes_map.keys())
    if missing_protected:
        logger.info(f"注入 {len(missing_protected)} 只无报价的受保护股票（持仓+自选）")

        # 1. 通过 get_market_snapshot 获取所有缺失股票的完整实时报价（无需订阅）
        _snapshot_quote_map = {}
        try:
            futu_client = getattr(container, 'futu_client', None)
            if futu_client and futu_client.is_available():
                ret, snapshot_df = futu_client.client.get_market_snapshot(list(missing_protected))
                if ret == 0 and snapshot_df is not None and not snapshot_df.empty:
                    for _, row in snapshot_df.iterrows():
                        _snapshot_quote_map[row['code']] = {
                            'last_price': row.get('last_price', 0),
                            'name': row.get('stock_name', ''),
                            'change_percent': row.get('price_change_rate', 0),
                            'turnover_rate': row.get('turnover_rate', 0),
                            'volume': row.get('volume', 0),
                            'turnover': row.get('turnover', 0),
                            'amplitude': row.get('amplitude', 0),
                        }
                    logger.info(f"通过 get_market_snapshot 获取到 {len(_snapshot_quote_map)} 只受保护股票报价")
        except Exception as e:
            logger.warning(f"获取受保护股票报价失败: {e}")

        # 2. 从交易API获取持仓股票的名称作为备用（snapshot 可能缺名称）
        _position_name_map = {}
        try:
            if hasattr(container, 'futu_trade_service') and container.futu_trade_service:
                pos_result = container.futu_trade_service.get_positions()
                if pos_result.get('success'):
                    for pos in pos_result.get('positions', []):
                        if pos.get('qty', 0) > 0:
                            _position_name_map[pos['stock_code']] = {
                                'last_price': pos.get('nominal_price', 0),
                                'name': pos.get('stock_name', ''),
                            }
        except Exception:
            pass

        for code in missing_protected:
            stock_info = stocks_info_map.get(code, {})
            snap_info = _snapshot_quote_map.get(code, {})
            pos_info = _position_name_map.get(code, {})
            quotes_map[code] = {
                "code": code,
                "name": snap_info.get("name", "") or pos_info.get("name", "") or stock_info.get("name", ""),
                "last_price": snap_info.get("last_price", 0) or pos_info.get("last_price", 0),
                "turnover_rate": snap_info.get("turnover_rate", 0),
                "change_percent": snap_info.get("change_percent", 0),
                "volume": snap_info.get("volume", 0),
                "turnover": snap_info.get("turnover", 0),
                "volume_ratio": 0,
                "amplitude": snap_info.get("amplitude", 0),
            }

    # 获取最低价格配置
    min_stock_price = getattr(container.config, "min_stock_price", None) or {"HK": 1.0, "US": 0}

    search_lower = search.strip().lower() if search else ""

    # 提前读取缓存数据（用于流动性筛选）
    ht_cache = state.high_turnover_cache.get_all()

    # 过滤和排序
    filtered_stocks = []
    for code, quote in quotes_map.items():
        stock_info = stocks_info_map.get(code, {})
        stock_market = stock_info.get("market", "") or _detect_market(code)
        stock_name = quote.get("name", "") or stock_info.get("name", "")
        turnover_rate = quote.get("turnover_rate", 0) or 0
        last_price = quote.get("last_price", 0) or 0

        # 市场过滤
        if market and stock_market != market:
            continue

        # 搜索过滤（代码或名称）
        if search_lower:
            if search_lower not in code.lower() and search_lower not in stock_name.lower():
                continue

        is_pos = code in position_codes
        is_watch = code in watchlist_codes
        is_protected = is_pos or is_watch

        # 受保护股票（持仓+自选）跳过活跃度筛选条件，始终显示
        if not is_protected:
            # 换手率阈值过滤
            if turnover_rate < min_turnover_rate:
                continue

            # 最低价格过滤
            min_price = min_stock_price.get(stock_market, 0)
            if min_price > 0 and 0 < last_price < min_price:
                continue

            # 流动性筛选（新增）
            if min_liquidity_score is not None or liquidity_level is not None:
                cached = ht_cache.get(code)
                if cached:
                    liq_score = cached.get("liquidity_score", 50)
                    liq_level = cached.get("liquidity_level", "B")

                    # 最低流动性评分筛选
                    if min_liquidity_score is not None and liq_score < min_liquidity_score:
                        continue

                    # 流动性等级筛选
                    if liquidity_level is not None and liq_level != liquidity_level:
                        continue
                else:
                    # 没有流动性数据时，如果设置了筛选条件则过滤掉
                    if min_liquidity_score is not None or liquidity_level is not None:
                        continue

        filtered_stocks.append({
            "code": code,
            "name": stock_name,
            "market": stock_market,
            "turnover_rate": turnover_rate,
            "change_rate": quote.get("change_percent", 0) or 0,
            "last_price": last_price,
            "volume": quote.get("volume", 0) or 0,
            "turnover": quote.get("turnover", 0) or 0,
            "volume_ratio": quote.get("volume_ratio", 0) or 0,
            "amplitude": quote.get("amplitude", 0) or 0,
            "is_position": is_pos,
            "is_watchlist": is_watch,
        })

    # 排序：受保护股（持仓/自选）置顶，其余按换手率降序
    filtered_stocks.sort(key=lambda s: (
        not s["is_position"], not s["is_watchlist"], -s["turnover_rate"]
    ))

    total = len(filtered_stocks)

    # 应用 limit
    result_stocks = filtered_stocks[:limit]

    # 批量查询板块信息
    stock_plates_map = await _batch_query_plates(container, [s["code"] for s in result_stocks])

    # 构建最终响应
    for rank, stock in enumerate(result_stocks, 1):
        stock["rank"] = rank
        stock["plates"] = stock_plates_map.get(stock["code"], [])

    # 成交分析：通过 futu API 批量分析（昂贵，仅显式开启时使用）
    if include_ticker_analysis:
        analysis_codes = [s["code"] for s in result_stocks]
        analysis_results = await batch_ticker_analysis(analysis_codes, container)
        for stock in result_stocks:
            stock["ticker_summary"] = analysis_results.get(stock["code"])

    # 轻量级 ticker 摘要：从 DB ticker_data 表批量计算（<0.1s）
    # 为没有 ticker_summary 的股票提供力量比和方向数据
    _need_ticker = [s["code"] for s in result_stocks if not s.get("ticker_summary")]
    if _need_ticker:
        try:
            from datetime import datetime as _dt
            _today = _dt.now().strftime('%Y-%m-%d')
            db_manager = container.db_manager
            if db_manager:
                _ph = ",".join(["?"] * len(_need_ticker))
                _rows = db_manager.execute_query(f"""
                    SELECT stock_code,
                           SUM(CASE WHEN direction='BUY' THEN turnover ELSE 0 END) as buy_amt,
                           SUM(CASE WHEN direction='SELL' THEN turnover ELSE 0 END) as sell_amt,
                           SUM(turnover) as total_amt,
                           COUNT(*) as tick_count
                    FROM ticker_data
                    WHERE stock_code IN ({_ph}) AND trade_date = ?
                    GROUP BY stock_code
                """, tuple(_need_ticker) + (_today,))
                _ticker_map = {}
                for r in (_rows or []):
                    code, buy_amt, sell_amt = r[0], r[1] or 0, r[2] or 0
                    ratio = round(buy_amt / sell_amt, 2) if sell_amt > 0 else (2.0 if buy_amt > 0 else 1.0)
                    net = round((buy_amt - sell_amt) / 10000, 2)  # 万元
                    score = min(100, max(-100, round((ratio - 1) * 50, 1)))
                    if score > 20 and ratio > 1.5:
                        bias, bias_label = "strong_bullish", "强买"
                    elif score > 20:
                        bias, bias_label = "bullish", "偏多"
                    elif score < -20:
                        bias, bias_label = "bearish", "偏空"
                    else:
                        bias, bias_label = "neutral", "中性"
                    signal = "bullish" if score > 20 else ("bearish" if score < -20 else "neutral")
                    label = "看涨" if score > 20 else ("看跌" if score < -20 else "中性")
                    _ticker_map[code] = {
                        "score": score, "signal": signal, "label": label,
                        "buy_sell_ratio": ratio, "net_turnover": net,
                        "bias": bias, "bias_label": bias_label,
                        "big_order_pct": 0, "big_buy_turnover": 0, "big_sell_turnover": 0,
                    }
                for stock in result_stocks:
                    if not stock.get("ticker_summary") and stock["code"] in _ticker_map:
                        stock["ticker_summary"] = _ticker_map[stock["code"]]
        except Exception as e:
            logger.warning(f"DB ticker 摘要计算失败: {e}")

    # 从后台预计算缓存读取大单、量比和流动性数据（不再在请求链路中实时计算）
    for stock in result_stocks:
        cached = ht_cache.get(stock["code"])
        if cached:
            if stock.get("volume_ratio", 0) == 0 and cached.get("volume_ratio", 0) > 0:
                stock["volume_ratio"] = cached["volume_ratio"]
            if "verified_big_buy_amount" in cached:
                stock["verified_big_buy_amount"] = cached["verified_big_buy_amount"]
                stock["verified_big_sell_amount"] = cached.get("verified_big_sell_amount", 0)
                stock["verified_buy_sell_ratio"] = cached.get("verified_buy_sell_ratio", 1.0)
            # 资金背离标签
            if "capital_divergence" in cached:
                stock["capital_divergence"] = cached["capital_divergence"]
            # 大单动量趋势
            if "big_order_momentum" in cached:
                stock["big_order_momentum"] = cached["big_order_momentum"]
            # 数据源标记
            if "big_order_data_source" in cached:
                stock["big_order_data_source"] = cached["big_order_data_source"]
            # 流动性数据（新增）
            if "liquidity_score" in cached:
                stock["liquidity_score"] = cached["liquidity_score"]
                stock["liquidity_level"] = cached.get("liquidity_level", "B")
                stock["is_volume_anomaly"] = cached.get("is_volume_anomaly", False)
                stock["kline_data_missing"] = cached.get("kline_data_missing", False)
                stock["volume_score"] = cached.get("volume_score", 0)
                stock["turnover_rate_score"] = cached.get("turnover_rate_score", 0)
                stock["amount_score"] = cached.get("amount_score", 0)
                stock["amplitude_score"] = cached.get("amplitude_score", 0)
                stock["stability_score"] = cached.get("stability_score", 0)

    # ===== 最终 fallback: 从 ht_cache 的 verified_buy_sell_ratio 构造 ticker_summary =====
    for stock in result_stocks:
        if stock.get("ticker_summary"):
            continue
        ratio = stock.get("verified_buy_sell_ratio", 0)
        if ratio > 0:
            score = min(100, max(-100, round((ratio - 1) * 50, 1)))
            if score > 20 and ratio > 1.5:
                bias, bias_label = "strong_bullish", "强买"
            elif score > 20:
                bias, bias_label = "bullish", "偏多"
            elif score < -20:
                bias, bias_label = "bearish", "偏空"
            else:
                bias, bias_label = "neutral", "中性"
            signal = "bullish" if score > 20 else ("bearish" if score < -20 else "neutral")
            label = "看涨" if score > 20 else ("看跌" if score < -20 else "中性")
            buy_amt = stock.get("verified_big_buy_amount", 0)
            sell_amt = stock.get("verified_big_sell_amount", 0)
            net = round((buy_amt - sell_amt) / 10000, 2) if (buy_amt or sell_amt) else 0
            stock["ticker_summary"] = {
                "score": score, "signal": signal, "label": label,
                "buy_sell_ratio": ratio, "net_turnover": net,
                "bias": bias, "bias_label": bias_label,
                "big_order_pct": 0, "big_buy_turnover": buy_amt, "big_sell_turnover": sell_amt,
            }

    # ==================== 价格位置分析（日线 + 当日双时间框架） ====================
    from ...services.analysis.price_position import (
        batch_get_price_range, analyze_price_position,
    )
    result_codes = [s["code"] for s in result_stocks]
    price_range_map = _get_cached_price_range(
        container.db_manager, result_codes, days=20,
    )

    # 批量获取资金分数（从缓存读取，不触发新的 API 调用）
    capital_score_map = {}
    try:
        capital_analyzer = getattr(container, 'capital_analyzer', None)
        if capital_analyzer:
            cf_data = capital_analyzer.batch_read_cache_only(result_codes)
            for code, data in cf_data.items():
                capital_score_map[code] = data.get('capital_score', 50.0)
    except Exception:
        pass

    for stock in result_stocks:
        code = stock["code"]
        cap_score = capital_score_map.get(code, 50.0)

        pp = analyze_price_position(
            current_price=stock.get("last_price", 0),
            change_rate=stock.get("change_rate", 0),
            price_range=price_range_map.get(code),
            capital_score=cap_score,
        )
        stock["price_position"] = pp.position
        stock["price_level"] = pp.level
        stock["daily_signal"] = pp.daily_signal
        stock["daily_label"] = pp.daily_label
        stock["intraday_signal"] = pp.intraday_signal
        stock["intraday_label"] = pp.intraday_label
        stock["entry_signal"] = pp.entry_signal
        stock["entry_label"] = pp.entry_label
        stock["warnings"] = pp.warnings

    return APIResponse(
        success=True,
        data={
            "stocks": result_stocks,
            "total": total,
            "update_time": datetime.now().isoformat(),
        },
        message=f"获取活跃个股成功，共{len(result_stocks)}只",
    )


def _detect_market(code: str) -> str:
    """根据股票代码前缀推断市场"""
    if code.startswith("HK."):
        return "HK"
    elif code.startswith("US."):
        return "US"
    return ""


async def _batch_query_plates(container, stock_codes: list) -> dict:
    """批量查询股票的板块信息

    Returns:
        {stock_code: [{"plate_code": "...", "plate_name": "..."}]}
    """
    if not stock_codes:
        return {}

    result = {}
    db_manager = container.db_manager
    if not db_manager:
        return {code: [] for code in stock_codes}

    try:
        placeholders = ",".join(["?"] * len(stock_codes))
        query = f"""
            SELECT s.code, p.plate_code, p.plate_name
            FROM stocks s
            INNER JOIN stock_plates sp ON s.id = sp.stock_id
            INNER JOIN plates p ON sp.plate_id = p.id
            WHERE s.code IN ({placeholders})
            ORDER BY s.code, p.priority DESC
        """
        rows = await db_manager.async_execute_query(query, tuple(stock_codes))

        for row in rows:
            code = row[0]
            if code not in result:
                result[code] = []
            result[code].append({
                "plate_code": row[1],
                "plate_name": row[2],
            })
    except Exception as e:
        logger.warning(f"批量查询板块信息失败: {e}")

    # 确保所有股票都有板块列表（即使为空）
    for code in stock_codes:
        if code not in result:
            result[code] = []

    return result


# ==================== 价格位置 TTL 缓存 ====================

_price_range_cache: dict = {}
_price_range_cache_ts: float = 0
_PRICE_RANGE_TTL = 60  # 秒，20日高低价一天才变一次，60秒完全足够


def _get_cached_price_range(db_manager, stock_codes, days=20):
    """带 TTL 缓存的价格区间查询，避免每次 API 请求都查 DB"""
    import time as _time
    from ...services.analysis.price_position import batch_get_price_range

    global _price_range_cache, _price_range_cache_ts
    now = _time.time()

    if now - _price_range_cache_ts < _PRICE_RANGE_TTL and _price_range_cache:
        missing = [c for c in stock_codes if c not in _price_range_cache]
        if not missing:
            return _price_range_cache

    result = batch_get_price_range(db_manager, stock_codes, days)
    _price_range_cache = result
    _price_range_cache_ts = now
    return result


