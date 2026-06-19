#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易执行路由

包含交易信号、交易执行、持仓查询等接口
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from ...core.models import TradeSignal, StockInfo
from ...core.exceptions import BusinessError
from ...dependencies import get_container
from ...schemas.common import APIResponse
from ...utils.cache_helper import get_cache
from .trade_helpers import ExecuteTradeRequest, ensure_trade_service


router = APIRouter(prefix="/api/trading", tags=["交易执行"])


@router.get("/signals", response_model=APIResponse)
async def get_trading_signals(
    limit: int = Query(50, ge=1, le=200, description="返回数量限制"),
    container=Depends(get_container)
):
    """获取交易信号股票列表（异步数据库查询）"""
    # 使用异步数据库查询获取今日交易信号
    query = '''
        SELECT ts.id, ts.stock_id, ts.signal_type, ts.signal_price,
               ts.target_price, ts.stop_loss_price, ts.condition_text,
               ts.is_executed, ts.executed_time, ts.created_at,
               s.code, s.name, ts.strategy_id, ts.strategy_name
        FROM trade_signals ts
        JOIN stocks s ON ts.stock_id = s.id
        WHERE DATE(ts.created_at) = DATE('now', 'localtime')
          AND ts.id IN (
              SELECT MAX(id)
              FROM trade_signals
              WHERE DATE(created_at) = DATE('now', 'localtime')
              GROUP BY stock_id, signal_type, COALESCE(strategy_id, '')
          )
        ORDER BY ts.created_at DESC
        LIMIT ?
    '''
    rows = await container.db_manager.async_execute_query(query, (limit,))
    db_signals = [TradeSignal.from_db_row_with_stock(row) for row in rows]

    # 使用 TradeSignal.to_dict() 序列化，并补充路由特有的格式转换
    signal_list = []
    for signal in db_signals:
        d = signal.to_dict()
        # 此路由使用 signal_price 而非 price，且 signal_type 转小写
        d['signal_price'] = d.pop('price')
        d['signal_type'] = d['signal_type'].lower()
        signal_list.append(d)

    logging.info(f"获取到 {len(signal_list)} 个交易信号")

    return APIResponse(
        success=True,
        data=signal_list,
        message=f"获取到 {len(signal_list)} 个交易信号",
        meta={'count': len(signal_list)}
    )


@router.post("/execute", response_model=APIResponse)
async def execute_trade(
    request: ExecuteTradeRequest,
    container=Depends(get_container)
):
    """执行交易"""
    # 验证数量
    request.validate_quantity()

    trade_service = ensure_trade_service(container)

    # 构建 StockInfo 对象（execute_trade 需要 StockInfo 而非 stock_code）
    stock = StockInfo(code=request.stock_code, name="")
    # price=None 表示市价单，传 0 给服务层
    trade_price = request.price if request.price else 0.0

    result = await asyncio.to_thread(
        trade_service.execute_trade,
        stock=stock,
        trade_type=request.trade_type,
        price=trade_price,
        quantity=request.quantity,
        signal_id=request.signal_id
    )

    if not result['success']:
        raise BusinessError(result['message'])

    return APIResponse(
        success=True,
        data={
            'trade_record_id': result['trade_record_id'],
            'futu_order_id': result['futu_order_id'],
            'stock_code': request.stock_code,
            'trade_type': request.trade_type,
            'price': request.price,
            'quantity': request.quantity
        },
        message=result['message']
    )


@router.get("/kline", response_model=APIResponse)
async def get_kline_data(
    stock_code: str = Query(..., min_length=1, description="股票代码"),
    container=Depends(get_container)
):
    """获取K线数据（异步版本）"""
    # 使用异步数据库查询
    kline_data = await container.db_manager.async_execute_query('''
        SELECT time_key, open_price, close_price, high_price, low_price, volume
        FROM kline_data
        WHERE stock_code = ?
        ORDER BY time_key DESC
        LIMIT 100
    ''', (stock_code,))

    if not kline_data:
        return APIResponse(
            success=True,
            data=[],
            message="暂无K线数据"
        )

    formatted_data = []
    for record in reversed(kline_data):
        time_key, open_price, close_price, high_price, low_price, volume = record
        formatted_data.append({
            'date': time_key,
            'open': float(open_price) if open_price else 0,
            'close': float(close_price) if close_price else 0,
            'high': float(high_price) if high_price else 0,
            'low': float(low_price) if low_price else 0,
            'volume': int(volume) if volume else 0
        })

    return APIResponse(
        success=True,
        data=formatted_data,
        message=f"获取到 {len(formatted_data)} 条K线数据",
        meta={'count': len(formatted_data)}
    )


@router.get("/records", response_model=APIResponse)
async def get_trade_records(
    limit: int = Query(50, ge=1, le=200, description="返回数量限制"),
    status: Optional[str] = Query(None, description="状态过滤"),
    container=Depends(get_container)
):
    """获取交易记录"""
    trade_service = ensure_trade_service(container)

    records = await asyncio.to_thread(trade_service.get_trade_records, limit=limit, status=status)

    return APIResponse(
        success=True,
        data=records,
        message=f"获取到 {len(records)} 条交易记录",
        meta={'count': len(records)}
    )


@router.get("/status", response_model=APIResponse)
async def get_trade_status(container=Depends(get_container)):
    """获取交易连接状态"""
    trade_service = ensure_trade_service(container)

    status = await asyncio.to_thread(trade_service.get_trade_status)

    return APIResponse(
        success=True,
        data=status,
        message="获取交易状态成功"
    )


@router.get("/positions", response_model=APIResponse)
async def get_positions(container=Depends(get_container)):
    """获取持仓信息（带缓存优化）"""
    # 尝试从缓存获取
    cache = get_cache()
    cache_key = "positions:data"
    cached_data = cache.get(cache_key, max_age=30)  # 缓存30秒

    if cached_data:
        logging.debug("持仓数据从缓存返回")
        return APIResponse(
            success=True,
            data=cached_data['positions'],
            message=f"获取到 {len(cached_data['positions'])} 个持仓（缓存）",
            meta={'count': len(cached_data['positions']), 'from_cache': True}
        )

    # 从API获取
    trade_service = ensure_trade_service(container)
    result = await asyncio.to_thread(trade_service.get_positions)

    if not result['success']:
        # 如果获取失败，返回空列表而不是抛出错误
        logging.warning(f"获取持仓失败: {result.get('message')}")
        return APIResponse(
            success=True,
            data=[],
            message=f"获取持仓失败: {result.get('message', '未知错误')}",
            meta={'count': 0, 'error': True}
        )

    # 存入缓存
    cache.set(cache_key, {'positions': result['positions']})

    return APIResponse(
        success=True,
        data=result['positions'],
        message=f"获取到 {len(result['positions'])} 个持仓",
        meta={'count': len(result['positions']), 'from_cache': False}
    )


@router.get("/positions/standalone", response_model=APIResponse)
async def get_positions_standalone(container=Depends(get_container)):
    """独立获取持仓信息（自动连接交易API，带缓存）

    此接口不依赖监控状态，会自动尝试连接交易API。
    适用于系统启动后、监控未启动时获取持仓数据。
    """
    # 尝试从缓存获取
    cache = get_cache()
    cache_key = "positions:standalone:data"
    cached_data = cache.get(cache_key, max_age=30)  # 缓存30秒

    if cached_data:
        logging.debug("独立持仓数据从缓存返回")
        return APIResponse(
            success=True,
            data=cached_data,
            message=f"获取到 {len(cached_data['positions'])} 个持仓（缓存）",
            meta={'count': len(cached_data['positions']), 'from_cache': True}
        )

    trade_service = ensure_trade_service(container)
    auto_connected = False

    # 检查交易API是否已连接，如未连接则尝试自动连接
    if not trade_service.is_trade_ready():
        logging.info("【独立持仓】交易API未连接，尝试自动连接...")
        connect_result = await asyncio.to_thread(trade_service.connect_trade_api)

        if not connect_result['success']:
            # 连接失败，返回空列表
            logging.warning(f"【独立持仓】交易API连接失败: {connect_result['message']}")
            return APIResponse(
                success=True,
                data={'positions': [], 'auto_connected': False, 'trade_api_status': {'is_connected': False, 'is_unlocked': False}},
                message=f"交易API连接失败: {connect_result['message']}",
                meta={'count': 0, 'error': True}
            )

        auto_connected = True
        logging.info("【独立持仓】交易API自动连接成功")

    # 获取持仓
    result = await asyncio.to_thread(trade_service.get_positions)

    if not result['success']:
        # 获取失败，返回空列表
        logging.warning(f"【独立持仓】获取持仓失败: {result['message']}")
        return APIResponse(
            success=True,
            data={'positions': [], 'auto_connected': auto_connected, 'trade_api_status': {'is_connected': trade_service.is_trade_ready(), 'is_unlocked': False}},
            message=result['message'],
            meta={'count': 0, 'error': True}
        )

    result_data = {
        'positions': result['positions'],
        'auto_connected': auto_connected,
        'trade_api_status': {
            'is_connected': trade_service.is_trade_ready(),
            'is_unlocked': getattr(trade_service, 'is_unlocked', False)
        }
    }

    # 存入缓存
    cache.set(cache_key, result_data)

    return APIResponse(
        success=True,
        data=result_data,
        message=f"获取到 {len(result['positions'])} 个持仓",
        meta={'count': len(result['positions']), 'from_cache': False}
    )


@router.post("/connect", response_model=APIResponse)
async def connect_trade_api(container=Depends(get_container)):
    """连接富途交易API"""
    trade_service = ensure_trade_service(container)

    result = await asyncio.to_thread(trade_service.connect_trade_api)

    if not result['success']:
        raise BusinessError(result['message'])

    return APIResponse(
        success=True,
        data={
            'is_connected': result['is_connected'],
            'is_unlocked': result['is_unlocked']
        },
        message=result['message']
    )


@router.get("/positions/capital-flow", response_model=APIResponse)
async def get_positions_capital_flow(container=Depends(get_container)):
    """获取持仓股票的资金流向数据"""
    trade_service = ensure_trade_service(container)

    # 1. 获取持仓列表
    result = await asyncio.to_thread(trade_service.get_positions)
    if not result['success'] or not result.get('positions'):
        return APIResponse(
            success=True,
            data=[],
            message="无持仓数据",
            meta={'count': 0}
        )

    positions = result['positions']
    stock_codes = [p['stock_code'] for p in positions]

    # 2. 批量获取资金流向（带缓存，60秒TTL）
    capital_data = {}
    try:
        analyzer = container.capital_analyzer
        if analyzer:
            capital_data = await asyncio.to_thread(
                analyzer.fetch_capital_flow_data,
                stock_codes,
                True,  # use_cache
                60,    # cache_ttl
            )
    except Exception as e:
        logging.warning(f"获取资金流向失败: {e}")

    # 2.5 批量获取逐笔 BSR（主动买卖力量比）
    ticker_bsr_map = {}
    try:
        from datetime import date
        today = date.today().strftime('%Y-%m-%d')
        placeholders = ','.join(['?'] * len(stock_codes))
        # 从 ticker_data 表按股票汇总当日主动买/卖金额
        bsr_rows = await container.db_manager.async_execute_query(f"""
            SELECT stock_code,
                   SUM(CASE WHEN direction = 'BUY' THEN turnover ELSE 0 END) as buy_turnover,
                   SUM(CASE WHEN direction = 'SELL' THEN turnover ELSE 0 END) as sell_turnover,
                   COUNT(*) as tick_count
            FROM ticker_data
            WHERE stock_code IN ({placeholders}) AND trade_date = ?
            GROUP BY stock_code
        """, (*stock_codes, today))
        if bsr_rows:
            for row in bsr_rows:
                code, buy_t, sell_t, cnt = row[0], row[1] or 0, row[2] or 0, row[3] or 0
                bsr = round(buy_t / sell_t, 3) if sell_t > 0 else 0
                ticker_bsr_map[code] = {
                    'bsr': bsr,
                    'ticker_power': round(bsr - 1.0, 3) if bsr > 0 else 0,
                    'buy_turnover': buy_t,
                    'sell_turnover': sell_t,
                    'tick_count': cnt,
                }
    except Exception as e:
        logging.debug(f"获取逐笔BSR失败: {e}")

    # 2.6 获取持仓股票的狙击手信号
    sniper_signals_map = {}
    try:
        sniper = getattr(container, 'intraday_sniper', None)
        if sniper:
            all_signals = sniper.get_today_signals()
            for sig in all_signals:
                code = sig.get('stock_code', '')
                if code in stock_codes:
                    if code not in sniper_signals_map:
                        sniper_signals_map[code] = []
                    sniper_signals_map[code].append(sig)
    except Exception as e:
        logging.debug(f"获取狙击手信号失败: {e}")

    # 3. 合并持仓 + 资金流向 + 逐笔BSR + 狙击手信号
    merged = []
    for pos in positions:
        code = pos['stock_code']
        flow = capital_data.get(code, {})
        ticker = ticker_bsr_map.get(code, {})
        merged.append({
            'stock_code': code,
            'stock_name': pos.get('stock_name', ''),
            'qty': pos.get('qty', 0),
            'cost_price': pos.get('cost_price', 0),
            'nominal_price': pos.get('nominal_price', 0),
            'market_val': pos.get('market_val', 0),
            'pl_val': pos.get('pl_val', 0),
            'pl_ratio': pos.get('pl_ratio', 0),
            # 资金流向字段（富途API）
            'main_net_inflow': flow.get('main_net_inflow', 0),
            'net_inflow_ratio': flow.get('net_inflow_ratio', 0),
            'capital_score': flow.get('capital_score', 0),
            'big_order_buy_ratio': flow.get('big_order_buy_ratio', 0),
            'super_large_inflow': flow.get('super_large_inflow', 0),
            'super_large_outflow': flow.get('super_large_outflow', 0),
            'large_inflow': flow.get('large_inflow', 0),
            'large_outflow': flow.get('large_outflow', 0),
            'medium_inflow': flow.get('medium_inflow', 0),
            'medium_outflow': flow.get('medium_outflow', 0),
            'small_inflow': flow.get('small_inflow', 0),
            'small_outflow': flow.get('small_outflow', 0),
            'inflow_change': flow.get('inflow_change', 0),
            'has_flow_data': bool(flow),
            # 逐笔 BSR 字段（基于实际成交方向）
            'ticker_bsr': ticker.get('bsr', 0),
            'ticker_power': ticker.get('ticker_power', 0),
            'ticker_buy_turnover': ticker.get('buy_turnover', 0),
            'ticker_sell_turnover': ticker.get('sell_turnover', 0),
            'ticker_count': ticker.get('tick_count', 0),
            'has_ticker_data': bool(ticker),
            # 狙击手信号（盘中巨量抢筹/砸盘等）
            'sniper_signals': sniper_signals_map.get(code, []),
            'has_sniper_alerts': len(sniper_signals_map.get(code, [])) > 0,
        })

    return APIResponse(
        success=True,
        data=merged,
        message=f"获取 {len(merged)} 只持仓的资金流向",
        meta={'count': len(merged)}
    )


@router.get("/positions/advice", response_model=APIResponse)
async def get_positions_advice(container=Depends(get_container)):
    """获取持仓股票的盘后操作建议"""
    try:
        from ...services.analysis.position_advisor import PositionAdvisor
        advisor = PositionAdvisor(container.db_manager, container)
        advices = advisor.get_latest_advice()

        return APIResponse(
            success=True,
            data=advices,
            message=f"获取 {len(advices)} 只持仓的操作建议",
            meta={'count': len(advices)}
        )
    except Exception as e:
        logging.error(f"获取持仓建议失败: {e}")
        return APIResponse(
            success=True,
            data=[],
            message=f"获取失败: {str(e)}",
            meta={'count': 0, 'error': True}
        )


@router.get("/positions/coach", response_model=APIResponse)
async def get_positions_coach(container=Depends(get_container)):
    """持仓教练卡：每只真实持仓 → 今日成交计数(churn)/成本漂移/盈亏/持有规则/洗盘别割。

    纯咨询：基于真实富途成交 + 持仓，专治盈利持仓上的来回交易/追涨杀跌。
    """
    try:
        from ...services.trading.discipline import (
            analyze_discipline, build_coach, DisciplineThresholds,
        )
        trade_service = ensure_trade_service(container)

        def _compute():
            pos_res = trade_service.get_positions()
            if not pos_res.get('success'):
                return None, pos_res.get('message', '')
            om = getattr(trade_service, 'order_manager', None)
            all_deals = om.get_today_deals('').get('deals', []) if om else []
            by_code = {}
            for d in all_deals:
                c = d.get('stock_code', '')
                if c and not str(c).startswith('HK.'):
                    c = f"HK.{c}"
                by_code.setdefault(c, []).append(d)

            th = DisciplineThresholds()
            guard_cfg = getattr(getattr(container, 'trade_frequency_guard', None), 'config', None)
            if guard_cfg:
                th.overtrade_buys = getattr(guard_cfg, 'max_same_stock_buys', th.overtrade_buys)
                th.reverse_cool_min = getattr(guard_cfg, 'min_rotation_interval_min', th.reverse_cool_min)
                th.min_hold_seconds = getattr(guard_cfg, 'min_hold_seconds', th.min_hold_seconds)

            sniper = getattr(container, 'intraday_sniper', None)
            out = []
            for p in pos_res.get('positions', []):
                if float(p.get('qty', 0) or 0) <= 0:
                    continue
                code = p.get('stock_code', '')
                disc = analyze_discipline(code, None, None, by_code.get(code, []), p, th)
                try:
                    tape = sniper.analyze_intraday_tape(code) if sniper else None
                except Exception:
                    tape = None
                out.append(build_coach(p, disc, th, tape))

            # 已验证有边际(回测+20~24pp)的逆高减/出货警示(R10/R3/R2): 为每只持仓附今日最新一条
            try:
                db = getattr(container, 'db_manager', None)
                codes = [c["stock_code"] for c in out]
                if db and codes:
                    ph = ",".join("?" for _ in codes)
                    rows = db.execute_query(
                        f"""SELECT stock_code, rule_id, rule_name, reason FROM capital_flow_signals
                            WHERE stock_code IN ({ph}) AND rule_id IN ('R2','R3','R10')
                              AND signal_type='SELL' AND date(created_at)=date('now')
                            ORDER BY created_at DESC""", codes)
                    fw = {}
                    for rr in (rows or []):
                        fw.setdefault(rr[0], f"{rr[2] or rr[1]}: {(rr[3] or '')[:42]}")
                    for c in out:
                        c["flow_warning"] = fw.get(c["stock_code"])
            except Exception:
                pass
            return out, None

        data, err = await asyncio.to_thread(_compute)
        if data is None:
            return APIResponse(success=True, data=[], message=f"获取持仓失败: {err}",
                               meta={'count': 0, 'error': True})
        return APIResponse(success=True, data=data, message=f"{len(data)} 只持仓教练卡",
                           meta={'count': len(data)})
    except Exception as e:
        logging.error(f"获取持仓教练卡失败: {e}")
        return APIResponse(success=True, data=[], message=f"获取失败: {str(e)}",
                           meta={'count': 0, 'error': True})

