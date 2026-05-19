#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
热门股票路由 - FastAPI Router

包含热门股票列表、非热门股票、热度状态等接口
"""

import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, Query

from ...core import get_state_manager
from ...dependencies import get_container
from ...schemas.common import APIResponse
from ...schemas.stock_response import build_stock_response
from ...utils.converters import get_last_price


router = APIRouter(prefix="/api", tags=["热门股票"])


async def _get_capital_flow_map(container, stock_codes: list) -> dict:
    """从缓存读取资金流向数据（纯读取，不调 API）

    资金流数据由 HighTurnoverEnricher 后台定时填充缓存，
    此处仅从 DB 缓存读取，避免在 API 请求链路中阻塞。
    """
    try:
        capital_analyzer = getattr(container, 'capital_analyzer', None)
        if not capital_analyzer:
            return {}
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, capital_analyzer.batch_read_cache_only, stock_codes
        )
        return result
    except Exception as e:
        logging.warning(f"读取资金流向缓存失败: {e}")
        return {}


@router.get("/stocks/heat-status", response_model=APIResponse)
async def get_heat_status(container=Depends(get_container)):
    """获取热度数据状态"""
    status = container.data_initializer.get_hot_stock_status()
    return APIResponse(
        success=True,
        data=status,
        message="获取热度状态成功"
    )


@router.get("/stocks/heat-progress", response_model=APIResponse)
async def get_heat_progress(container=Depends(get_container)):
    """获取热度分析进度"""
    hot_service = container.hot_stock_service
    progress = hot_service.get_analysis_progress() if hasattr(hot_service, 'get_analysis_progress') else {}
    return APIResponse(
        success=True,
        data=progress,
        message="获取分析进度成功"
    )


@router.get("/stocks/top-hot", response_model=APIResponse)
async def get_top_hot_stocks(
    limit: int = Query(100, ge=1, le=500, description="返回数量限制"),
    market: Optional[str] = Query(None, description="市场过滤(HK/US)"),
    search: Optional[str] = Query(None, description="搜索关键词"),
    container=Depends(get_container)
):
    """获取热门前N只股票（基于实时数据排序）"""
    import time as _time
    _t0 = _time.monotonic()
    from ...utils.market_helper import MarketTimeHelper

    state = get_state_manager()
    search_lower = search.strip().lower() if search else ""

    pool_data = state.get_stock_pool()
    stocks_data = pool_data.get('stocks', [])

    # 获取持仓股票列表（需在订阅过滤前获取，确保持仓股票始终可见）
    query_service = container.hot_stock_query_service
    position_codes = query_service.get_position_codes(
        futu_trade_service=getattr(container, 'futu_trade_service', None)
    )

    # 只显示已订阅的股票 + 持仓股票（持仓即使未订阅也要显示）
    subscribed_codes = container.subscription_manager.subscribed_stocks
    if subscribed_codes:
        visible_codes = subscribed_codes | position_codes
        stocks_data = [s for s in stocks_data if s['code'] in visible_codes]

    # 确保持仓股票存在于 stocks_data 中（即使不在股票池中也要显示）
    existing_codes = {s['code'] for s in stocks_data}
    missing_in_pool = position_codes - existing_codes
    if missing_in_pool:
        for code in missing_in_pool:
            stock_market = 'HK' if code.startswith('HK.') else 'US'
            stocks_data.append({'code': code, 'name': '', 'market': stock_market, 'id': 0})

    active_markets = MarketTimeHelper.get_current_active_markets()
    market_info = MarketTimeHelper.get_market_status_info()

    # 获取实时报价（优先新鲜数据，收盘/重启后 fallback 到最后已知报价）
    cached_quotes = state.get_cached_quotes()
    if not cached_quotes:
        cached_quotes = state.quote_cache.get_last_quotes() or []
    # 第二层 fallback：重启后内存为空，从 DB 最后一天 K 线获取收盘价
    if not cached_quotes:
        db = getattr(container, 'db_manager', None)
        if db:
            try:
                kl_rows = db.execute_query("""
                    SELECT k.stock_code, s.name, k.close_price, k.open_price,
                           k.high_price, k.low_price, k.volume, k.turnover,
                           k.turnover_rate, k2.close_price as prev_close
                    FROM kline_data k
                    JOIN (SELECT stock_code, MAX(time_key) as max_time
                          FROM kline_data GROUP BY stock_code) latest
                        ON k.stock_code = latest.stock_code AND k.time_key = latest.max_time
                    LEFT JOIN stocks s ON k.stock_code = s.code
                    LEFT JOIN kline_data k2
                        ON k2.stock_code = k.stock_code
                        AND k2.time_key = (SELECT MAX(time_key) FROM kline_data
                                           WHERE stock_code = k.stock_code AND time_key < k.time_key)
                """)
                if kl_rows:
                    for r in kl_rows:
                        code, name = r[0], r[1] or ''
                        close, open_p, high, low = r[2] or 0, r[3] or 0, r[4] or 0, r[5] or 0
                        vol, turnover, tr = r[6] or 0, r[7] or 0, r[8] or 0
                        prev_close = r[9] or close
                        chg = ((close - prev_close) / prev_close * 100) if prev_close > 0 else 0
                        cached_quotes.append({
                            'code': code, 'name': name,
                            'last_price': close, 'cur_price': close,
                            'open_price': open_p, 'high_price': high, 'low_price': low,
                            'prev_close_price': prev_close,
                            'change_rate': round(chg, 2),
                            'volume': vol, 'turnover': turnover,
                            'turnover_rate': tr,
                        })
                    logging.info(f"【TopHot】从 K 线补充 {len(cached_quotes)} 只股票盘前报价")
            except Exception as e:
                logging.warning(f"【TopHot】K 线 fallback 失败: {e}")
    quotes_map = {q.get('code'): q for q in cached_quotes if isinstance(q, dict)}

    # 确保持仓股票存在于 quotes_map 中（即使没有实时订阅也要显示）
    missing_position_codes = position_codes - set(quotes_map.keys())
    if missing_position_codes:
        # 尝试从交易API获取持仓股票的现价信息
        _position_price_map = {}
        try:
            if hasattr(container, 'futu_trade_service') and container.futu_trade_service:
                pos_result = container.futu_trade_service.get_positions()
                if pos_result.get('success'):
                    for pos in pos_result.get('positions', []):
                        if pos.get('qty', 0) > 0:
                            _position_price_map[pos['stock_code']] = {
                                'last_price': pos.get('nominal_price', 0),
                                'name': pos.get('stock_name', ''),
                            }
        except Exception:
            pass

        for code in missing_position_codes:
            pool_stock = next((s for s in stocks_data if s.get('code') == code), {})
            pos_info = _position_price_map.get(code, {})
            quotes_map[code] = {
                'code': code,
                'name': pos_info.get('name', '') or pool_stock.get('name', ''),
                'last_price': pos_info.get('last_price', 0),
                'turnover_rate': 0,
                'change_percent': 0,
                'volume': 0,
                'turnover': 0,
            }

    # 获取交易条件
    trading_conditions = state.get_trading_conditions() or {}
    conditions_map = {c.get('stock_code'): c for c in trading_conditions.values() if isinstance(c, dict)}

    # 读取筛选配置
    filter_config = getattr(container.config, 'realtime_hot_filter', None) or {}
    min_stock_price = getattr(container.config, 'min_stock_price', None) or {'HK': 1.0, 'US': 0}

    # 从 HotStockService 读取已缓存的热度分
    hot_service = container.hot_stock_service
    cached_heat_scores = hot_service.get_cached_heat_scores() if hot_service else {}

    # 过滤和排序股票
    top_stocks, filter_summary = query_service.filter_and_sort_stocks(
        stocks_data=stocks_data,
        quotes_map=quotes_map,
        cached_heat_scores=cached_heat_scores,
        filter_config=filter_config,
        min_stock_price=min_stock_price,
        market_filter=market,
        search_filter=search_lower,
        limit=limit,
        position_codes=position_codes,
    )

    logging.info(f"【TopHot性能】filter_and_sort: {_time.monotonic()-_t0:.2f}s")
    _t1 = _time.monotonic()

    # 后台补充缺失K线（波动率过滤依赖K线数据）
    all_codes = {s['code'] for s in stocks_data}
    query_service.trigger_kline_download_for_missing(
        all_codes, query_service._stocks_with_kline
    )

    # 批量获取资金流向缓存
    capital_flow_map = await _get_capital_flow_map(
        container, [s['code'] for s in top_stocks]
    )

    logging.info(f"【TopHot性能】capital_flow_map: {_time.monotonic()-_t1:.2f}s")
    _t2 = _time.monotonic()

    # 批量获取20日价格区间（用于价格位置分析）
    from ...services.analysis.price_position import (
        batch_get_price_range, analyze_price_position,
    )
    stock_codes_list = [s['code'] for s in top_stocks]
    price_range_map = batch_get_price_range(
        getattr(container, 'db_manager', None), stock_codes_list, days=20,
    )

    # 批量查询板块信息
    plates_map = await _batch_query_plates(container, stock_codes_list)

    # 从 HighTurnoverCache 读取预计算的量比
    ht_cache = state.high_turnover_cache.get_all()

    logging.info(f"【TopHot性能】price_range+plates+ht_cache: {_time.monotonic()-_t2:.2f}s")
    _t3 = _time.monotonic()

    # 构建响应数据
    from ...services.analysis.signal import SignalArbiter, StrategyVote
    from ...services.strategy.stock_scorer import StockScorer
    arbiter = SignalArbiter()
    _scorer = StockScorer()

    # ===== 批量预查询 K线数据（消除逐只 DB 查询瓶颈）=====
    import datetime as _dt
    _today = _dt.datetime.now().strftime('%Y-%m-%d')
    _kline_cache: dict = {}  # {stock_code: [row, ...]}  每行=(time_key, open, high, low, close, volume, turnover_rate)
    db = getattr(container, 'db_manager', None)
    if db and stock_codes_list:
        try:
            _placeholders = ",".join(["?"] * len(stock_codes_list))
            _kl_rows = db.execute_query(f"""
                SELECT stock_code, time_key, open_price, high_price, low_price,
                       close_price, volume, turnover_rate
                FROM kline_data
                WHERE stock_code IN ({_placeholders}) AND date(time_key) < ?
                ORDER BY stock_code, time_key DESC
            """, tuple(stock_codes_list) + (_today,))
            # 按 stock_code 分组，每只最多取25条
            _code_count: dict = {}
            for r in (_kl_rows or []):
                code = r[0]
                cnt = _code_count.get(code, 0)
                if cnt >= 25:
                    continue
                _code_count[code] = cnt + 1
                _kline_cache.setdefault(code, []).append(r[1:])  # 去掉 stock_code
            # 反转为时间升序
            for code in _kline_cache:
                _kline_cache[code].reverse()
        except Exception as e:
            logging.warning(f"【TopHot】批量K线预查询失败: {e}")

    logging.info(f"【TopHot性能】kline_batch_prequery: {_time.monotonic()-_t3:.2f}s")
    _t4 = _time.monotonic()

    result_stocks = []
    for stock in top_stocks:
        stock_code = stock['code']
        quote = quotes_map.get(stock_code, {})
        condition = conditions_map.get(stock_code)

        # 价格位置分析
        cf_data = capital_flow_map.get(stock_code)
        capital_score = cf_data['capital_score'] if cf_data else 50.0
        change_rate = quote.get('change_percent') or quote.get('change_rate', 0)
        cur_price = get_last_price(quote)

        pp_result = analyze_price_position(
            current_price=cur_price,
            change_rate=change_rate,
            price_range=price_range_map.get(stock_code),
            capital_score=capital_score,
        )

        # 量比：优先 quote，其次 Enricher 缓存
        vr = quote.get('volume_ratio', 0) or 0
        cached = ht_cache.get(stock_code)
        if vr == 0 and cached:
            vr = cached.get('volume_ratio', 0)

        # 股票标签：优先从 Enricher 缓存读取，否则实时计算
        stock_tag = None
        if cached and cached.get('stock_tag_label'):
            stock_tag = {
                'label': cached.get('stock_tag_label', '正常'),
                'phase': cached.get('stock_tag_phase', ''),
                'risk_note': cached.get('stock_tag_risk', ''),
            }
        elif not stock_tag:
            # Fallback: 从批量预查询的 K线缓存计算（enricher 未跑时）
            try:
                from ...services.market_data.stock_profile_tagger import StockProfileTagger
                _tagger = StockProfileTagger()
                _rows = _kline_cache.get(stock_code, [])[:15]
                if len(_rows) >= 5:
                    _cols = ["time_key","open_price","high_price","low_price",
                             "close_price","volume","turnover_rate"]
                    _klines = [dict(zip(_cols, r)) for r in _rows]
                    _tag = _tagger.tag_stock(stock_code, _klines, cur_price)
                    if _tag.label != '正常':
                        stock_tag = {
                            'label': _tag.label,
                            'phase': _tag.phase,
                            'risk_note': _tag.risk_note,
                        }
            except Exception:
                pass

        # 多策略共识信号 — 基于 StockScorer 回测6维评分体系
        consensus_data = None
        try:
            # 从 Enricher 缓存或 DB K线获取评分所需指标
            _kline_indicators = {}
            if cached:
                # Enricher 缓存有预计算数据
                _kline_indicators = {
                    'change_5d': cached.get('change_5d'),
                    'kline_pos_20d': cached.get('kline_position_20d'),
                    'day_amplitude': cached.get('amplitude') or (quote.get('amplitude', 0)),
                    'vol_ratio': vr if vr > 0 else cached.get('volume_ratio'),
                    'prev_day_change': cached.get('prev_day_change'),
                    'flow_ratio': cf_data.get('net_inflow_ratio', 0) if cf_data else 0,
                }
            if not _kline_indicators.get('change_5d'):
                # Fallback: 从批量预查询的 K线缓存计算
                _rows = _kline_cache.get(stock_code, [])
                if len(_rows) >= 5:
                    _klines = _rows  # 已经是时间升序
                    # 5日涨幅
                    if len(_klines) >= 6:
                        c_now, c_5d = _klines[-1][4], _klines[-6][4]
                        _kline_indicators['change_5d'] = round((c_now - c_5d) / c_5d * 100, 2) if c_5d else 0
                    # K线20日位置
                    recent = _klines[-min(20, len(_klines)):]
                    highs = [r[2] for r in recent]
                    lows = [r[3] for r in recent]
                    h, l = max(highs), min(lows)
                    _kline_indicators['kline_pos_20d'] = round((cur_price - l) / (h - l), 4) if h != l else 0.5
                    # 前日涨幅
                    if len(_klines) >= 3:
                        c_prev, c_prev2 = _klines[-2][4], _klines[-3][4]
                        _kline_indicators['prev_day_change'] = round((c_prev - c_prev2) / c_prev2 * 100, 2) if c_prev2 else 0
                    # 日振幅
                    amp = quote.get('amplitude', 0)
                    if not amp and cur_price > 0:
                        day_high = quote.get('high_price', 0) or _klines[-1][2]
                        day_low = quote.get('low_price', 0) or _klines[-1][3]
                        amp = round((day_high - day_low) / cur_price * 100, 2) if cur_price else 0
                    _kline_indicators.setdefault('day_amplitude', amp)
                    _kline_indicators.setdefault('vol_ratio', vr)
                    _kline_indicators.setdefault('flow_ratio', cf_data.get('net_inflow_ratio', 0) if cf_data else 0)

            # 调用 StockScorer 6维评分
            scoring_result = _scorer.score_stock(stock_code, stock.get('name', ''), _kline_indicators)

            # 把6维评分转为 votes（用于 SignalArbiter 共识计算）
            votes = []
            for detail in scoring_result.details:
                normalized = round(detail.score / detail.max_score * 100, 1) if detail.max_score > 0 else 50
                signal = "bullish" if normalized >= 60 else ("bearish" if normalized < 40 else "neutral")
                votes.append(StrategyVote(
                    strategy_name=detail.dimension,
                    score=normalized,
                    signal=signal,
                ))

            # ── 追加其他引擎的投票 ──

            # 价格位置引擎（Price Position）
            pp_vote = None
            if pp_result:
                pp_signal = "bullish" if pp_result.entry_signal in ("opportunity", "momentum") else (
                    "bearish" if pp_result.entry_signal == "risky" else "neutral"
                )
                pp_norm = 80 if pp_result.entry_signal == "opportunity" else (
                    70 if pp_result.entry_signal == "momentum" else (
                    30 if pp_result.entry_signal == "risky" else 50
                ))
                votes.append(StrategyVote(strategy_name="价格位置", score=pp_norm, signal=pp_signal))
                pp_vote = {
                    'name': '价格位置',
                    'score': pp_norm,
                    'max_score': 100,
                    'signal': pp_signal,
                    'details': [
                        {'label': '20日位置', 'value': f"{pp_result.position:.0f}%"},
                        {'label': '入场信号', 'value': pp_result.entry_label or '-'},
                        {'label': '日线信号', 'value': pp_result.daily_label or '-'},
                    ],
                }

            # 资金流向引擎（Capital Flow）
            cf_vote = None
            if cf_data:
                net_inflow = cf_data.get('main_net_inflow', 0)
                big_ratio = cf_data.get('big_order_buy_ratio', 0.5)
                cf_norm = round(capital_score, 1)
                cf_signal = "bullish" if capital_score >= 60 else ("bearish" if capital_score < 45 else "neutral")
                votes.append(StrategyVote(strategy_name="资金流向", score=cf_norm, signal=cf_signal))
                inflow_str = f"{net_inflow/1e8:.2f}亿" if abs(net_inflow) >= 1e8 else f"{net_inflow/1e4:.0f}万"
                cf_vote = {
                    'name': '资金流向',
                    'score': cf_norm,
                    'max_score': 100,
                    'signal': cf_signal,
                    'details': [
                        {'label': '资金评分', 'value': f'{capital_score:.0f}'},
                        {'label': '主力净流入', 'value': inflow_str},
                        {'label': '大单买比', 'value': f"{big_ratio*100:.1f}%"},
                    ],
                }

            # 风控标签引擎（Risk Control）
            risk_vote = None
            if stock_tag and stock_tag.get('label', '正常') != '正常':
                risk_labels = {'锁仓控盘': 25, '暴量拉升': 35, '仙股炒作': 15, '明星高波动': 55}
                risk_score = risk_labels.get(stock_tag['label'], 40)
                votes.append(StrategyVote(strategy_name="风控标签", score=risk_score, signal="bearish"))
                risk_vote = {
                    'name': '风控标签',
                    'score': risk_score,
                    'max_score': 100,
                    'signal': 'bearish',
                    'details': [
                        {'label': '标签', 'value': stock_tag['label']},
                        {'label': '风险', 'value': stock_tag.get('risk_note', '-')},
                    ],
                }

            consensus = arbiter.arbitrate(stock_code, stock.get('name', ''), votes)

            # 构建 votes 列表：StockScorer 6维 + 其他引擎
            vote_list = [
                {
                    'name': detail.dimension,
                    'score': detail.score,
                    'max_score': detail.max_score,
                    'signal': 'bullish' if detail.score >= detail.max_score * 0.6 else (
                        'bearish' if detail.score < detail.max_score * 0.4 else 'neutral'),
                    'details': [
                        {'label': '指标值', 'value': f'{detail.value:.2f}' if detail.value is not None else '无数据'},
                        {'label': '得分', 'value': f'{detail.score}/{detail.max_score}'},
                    ] + ([{'label': '备注', 'value': detail.note}] if detail.note else []),
                }
                for detail in scoring_result.details
            ]
            # 追加其他引擎
            for extra in [pp_vote, cf_vote, risk_vote]:
                if extra:
                    vote_list.append(extra)

            consensus_data = {
                'verdict': consensus.verdict.value,
                'verdict_label': consensus.verdict_label,
                'score': round(consensus.consensus_score, 1),
                'confidence': round(consensus.confidence, 2),
                'total_score': scoring_result.total_score,
                'passed': scoring_result.passed,
                'veto_reason': scoring_result.veto_reason or None,
                'votes': vote_list,
            }
        except Exception:
            pass

        result_stocks.append(build_stock_response(
            stock=stock,
            quote=quote,
            condition=condition,
            is_position=stock_code in position_codes,
            capital_flow_data=cf_data,
            price_position_result=pp_result,
            plates=plates_map.get(stock_code, []),
            volume_ratio=vr,
            stock_tag=stock_tag,
            consensus_data=consensus_data,
        ))

    logging.info(f"【TopHot性能】for_loop({len(top_stocks)}只): {_time.monotonic()-_t4:.2f}s | 总计: {_time.monotonic()-_t0:.2f}s")

    # 计算数据就绪状态
    # 用订阅数量作为基准，而非全局股票池
    expected_count = len(subscribed_codes) if subscribed_codes else sum(
        1 for s in stocks_data if s.get('market') in active_markets
    )
    stock_codes_set = {s['code'] for s in stocks_data}
    cached_quotes_count = len([q for q in cached_quotes if q.get('code') in stock_codes_set])
    ready_percent = (cached_quotes_count / expected_count * 100) if expected_count > 0 else 0
    data_ready = ready_percent >= 80

    cache_timestamp = datetime.now().isoformat()

    return APIResponse(
        success=True,
        data={
            'stocks': result_stocks,
            'market_info': market_info,
            'active_markets': active_markets,
            'filter_config': filter_config,
            'data_ready_status': {
                'data_ready': data_ready,
                'cached_count': cached_quotes_count,
                'expected_count': expected_count,
                'ready_percent': round(ready_percent, 1)
            },
            'cache_timestamp': cache_timestamp,
            'cache_duration': 3600
        },
        message=f"获取热门股票成功，共{len(top_stocks)}只"
        + (f"（已过滤: {', '.join(filter_summary)}）" if filter_summary else "")
    )


@router.get("/stocks/non-hot", response_model=APIResponse)
async def get_non_hot_stocks(
    page: int = Query(1, ge=1, description="页码"),
    limit: int = Query(20, ge=1, le=200, description="每页数量"),
    market: Optional[str] = Query(None, description="市场过滤(HK/US)"),
    search: Optional[str] = Query(None, description="搜索关键词"),
    hot_limit: int = Query(100, ge=1, le=500, description="热门股票数量阈值"),
    container=Depends(get_container)
):
    """获取未入选热门的股票"""
    from ...utils.market_helper import MarketTimeHelper

    state = get_state_manager()
    search_lower = search.strip().lower() if search else ""

    pool_data = state.get_stock_pool()
    stocks_data = pool_data.get('stocks', [])

    # 获取持仓股票列表（需在订阅过滤前获取，确保持仓股票始终可见）
    query_service = container.hot_stock_query_service
    position_codes = query_service.get_position_codes(
        futu_trade_service=getattr(container, 'futu_trade_service', None)
    )

    # 只显示已订阅的股票 + 持仓股票（持仓即使未订阅也要显示）
    subscribed_codes = container.subscription_manager.subscribed_stocks
    if subscribed_codes:
        visible_codes = subscribed_codes | position_codes
        stocks_data = [s for s in stocks_data if s['code'] in visible_codes]

    active_markets = MarketTimeHelper.get_current_active_markets()

    # 获取实时报价
    cached_quotes = state.get_cached_quotes() or []
    quotes_map = {q.get('code'): q for q in cached_quotes if isinstance(q, dict)}

    # 获取交易条件
    trading_conditions = state.get_trading_conditions() or {}
    conditions_map = {c.get('stock_code'): c for c in trading_conditions.values() if isinstance(c, dict)}

    # 读取筛选配置
    filter_config = getattr(container.config, 'realtime_hot_filter', None) or {}
    min_stock_price = getattr(container.config, 'min_stock_price', None) or {'HK': 1.0, 'US': 0}

    # 从 HotStockService 读取已缓存的热度分
    hot_service = container.hot_stock_service
    cached_heat_scores = hot_service.get_cached_heat_scores() if hot_service else {}

    # 获取热门股票代码
    hot_stocks, _ = filter_and_sort_stocks(
        stocks_data=stocks_data,
        quotes_map=quotes_map,
        cached_heat_scores=cached_heat_scores,
        filter_config=filter_config,
        min_stock_price=min_stock_price,
        market_filter=None,
        search_filter="",
        limit=hot_limit,
        position_codes=position_codes,
    )
    hot_codes = {s['code'] for s in hot_stocks}

    # 过滤非热门股票
    non_hot_stocks = []
    for stock in stocks_data:
        stock_code = stock['code']
        stock_market = stock.get('market', '')

        # 跳过热门股票
        if stock_code in hot_codes:
            continue

        # 市场过滤
        if market and stock_market != market:
            continue

        # 搜索过滤
        if search_lower and search_lower not in stock_code.lower() \
                and search_lower not in stock.get('name', '').lower():
            continue

        non_hot_stocks.append(stock)

    # 分页
    total = len(non_hot_stocks)
    start = (page - 1) * limit
    end = start + limit
    page_stocks = non_hot_stocks[start:end]

    # 批量获取资金流向缓存
    capital_flow_map = await _get_capital_flow_map(
        container, [s['code'] for s in page_stocks]
    )

    # 构建响应数据
    result_stocks = []
    for stock in page_stocks:
        stock_code = stock['code']
        quote = quotes_map.get(stock_code, {})
        condition = conditions_map.get(stock_code)

        result_stocks.append(build_stock_response(
            stock=stock,
            quote=quote,
            condition=condition,
            is_position=stock_code in position_codes,
            capital_flow_data=capital_flow_map.get(stock_code),
        ))

    return APIResponse(
        success=True,
        data={
            'stocks': result_stocks,
            'pagination': {
                'page': page,
                'limit': limit,
                'total': total,
                'pages': (total + limit - 1) // limit
            }
        },
        message=f"获取非热门股票成功，共{total}只"
    )


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
        logging.warning(f"批量查询板块信息失败: {e}")

    for code in stock_codes:
        if code not in result:
            result[code] = []

    return result


logging.info("热门股票路由已注册")
