#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票池查询路由

包含股票池相关的查询接口：
- 获取监控池股票
- 通用数据查询
- 未订阅股票列表
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from ....core import get_state_manager
from ....core.exceptions import BusinessError, ValidationError
from ....dependencies import get_container
from ....schemas.common import APIResponse, PaginatedResponse


router = APIRouter(prefix="/api", tags=["股票池查询"])


@router.get("/stocks/plates")
async def get_plates(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    search: Optional[str] = Query(None, description="搜索板块代码或名称"),
    market: Optional[str] = Query(None, description="市场筛选 (HK/US)"),
    container=Depends(get_container)
):
    """获取板块列表（带分页和筛选）"""
    try:
        query_service = container.stock_pool_service.query_service
        all_plates = query_service.get_plates(is_target=True)

        # 筛选
        filtered = []
        for plate in all_plates:
            if market and plate.get('market') != market:
                continue
            if search:
                search_lower = search.lower()
                code = plate.get('code', '').lower()
                name = plate.get('name', '').lower()
                if search_lower not in code and search_lower not in name:
                    continue
            filtered.append({
                'id': plate['id'],
                'plate_code': plate['code'],
                'plate_name': plate['name'],
                'market': plate.get('market', ''),
                'stock_count': plate.get('stock_count', 0),
                'is_target': plate.get('is_target', False),
                'is_enabled': plate.get('is_enabled', True),
                'priority': plate.get('priority', 0),
            })

        # 分页
        total = len(filtered)
        start = (page - 1) * limit
        paginated = filtered[start:start + limit]

        return PaginatedResponse.create(
            data=paginated,
            page=page,
            page_size=limit,
            total=total,
            message=f"获取板块列表成功（共{total}个）"
        )
    except Exception as e:
        logging.error(f"获取板块列表失败: {e}", exc_info=True)
        raise BusinessError(message=f"获取板块列表失败: {str(e)}")


@router.get("/stocks/pool")
async def get_stock_pool(container=Depends(get_container)):
    """获取监控池股票 - 按交易时间筛选市场"""
    from ....utils.market_helper import MarketTimeHelper

    state = get_state_manager()

    active_markets = MarketTimeHelper.get_current_active_markets()
    market_info = MarketTimeHelper.get_market_status_info()
    is_monitoring = state.is_running()

    # 获取目标股票
    if is_monitoring:
        target_stocks = state.get_target_stocks()
        data_source = 'monitoring'
        if not target_stocks:
            pool_data = state.get_stock_pool()
            target_stocks = pool_data.get('stocks', [])
            data_source = 'pool_fallback'
    else:
        pool_data = state.get_stock_pool()
        target_stocks = pool_data.get('stocks', [])
        data_source = 'pool'

    # 获取缓存的报价和交易条件
    cached_quotes = state.get_cached_quotes()
    trading_conditions = state.get_trading_conditions()

    quotes_map = {q.get('code'): q for q in cached_quotes} if cached_quotes else {}
    conditions_map = {}
    if trading_conditions:
        for key, val in trading_conditions.items():
            if isinstance(val, dict):
                conditions_map[key] = val

    # 按活跃市场筛选并合并数据
    filtered_stocks = []
    for stock in target_stocks:
        if stock.get('market') not in active_markets:
            continue

        stock_data = dict(stock)
        stock_code = stock.get('code', '')

        # 合并报价数据
        if stock_code in quotes_map:
            quote = quotes_map[stock_code]
            stock_data.update({
                'cur_price': quote.get('last_price') or quote.get('current_price') or quote.get('cur_price'),
                'last_price': quote.get('last_price') or quote.get('current_price'),
                'price_change': quote.get('change_amount') or quote.get('price_change'),
                'change_rate': quote.get('change_percent') or quote.get('change_rate'),
                'turnover_rate': quote.get('turnover_rate'),
                'volume': quote.get('volume'),
                'turnover': quote.get('turnover'),
                'amplitude': quote.get('amplitude'),
                'high_price': quote.get('high_price'),
                'low_price': quote.get('low_price'),
                'open_price': quote.get('open_price'),
                'prev_close_price': quote.get('prev_close') or quote.get('prev_close_price')
            })

        # 合并交易条件
        if stock_code in conditions_map:
            condition = conditions_map[stock_code]
            stock_data['check_conditions'] = condition.get('reason', '')
            stock_data['trend_status'] = '满足条件' if condition.get('condition_passed') else '不满足'

            if condition.get('buy_signal'):
                stock_data['signal'] = {'type': 'buy'}
            elif condition.get('sell_signal'):
                stock_data['signal'] = {'type': 'sell'}

        filtered_stocks.append(stock_data)

    # 统计市场分布
    market_counts = {}
    for stock in filtered_stocks:
        market = stock.get('market', 'Unknown')
        market_counts[market] = market_counts.get(market, 0) + 1

    logging.info(f"监控池筛选: 数据来源={data_source}, 活跃市场={active_markets}, "
                 f"总股票={len(target_stocks)}, 筛选后={len(filtered_stocks)}")

    source_text = '监控中' if data_source == 'monitoring' else '全部股票池'
    message = f"获取{source_text}成功（当前市场: {', '.join(active_markets)}，{len(filtered_stocks)}只股票）"

    return APIResponse.ok(
        data={
            'stocks': filtered_stocks,
            'market_info': market_info,
            'market_counts': market_counts,
            'total_before_filter': len(target_stocks),
            'total_after_filter': len(filtered_stocks),
            'is_monitoring': is_monitoring,
            'data_source': data_source
        },
        message=message
    )


@router.get("/stocks/list")
async def get_stocks_list(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    plate_id: Optional[int] = Query(None, description="板块ID"),
    search: Optional[str] = Query(None, description="搜索关键词")
):
    """获取股票列表（带分页和筛选）"""
    state = get_state_manager()
    pool_data = state.get_stock_pool()
    stocks_data = pool_data['stocks']

    # 筛选
    filtered = []
    for stock in stocks_data:
        if plate_id:
            stock_plate_id = stock.get('plate_id')
            if not stock_plate_id or str(stock_plate_id) != str(plate_id):
                continue

        if search:
            search_lower = search.lower()
            code = str(stock.get('code', '')).lower()
            name = str(stock.get('name', '')).lower()
            if search_lower not in code and search_lower not in name:
                continue

        filtered.append(stock)

    total = len(filtered)
    start = (page - 1) * limit
    paginated = filtered[start:start + limit]

    stocks = [{
        'id': s.get('id', 0),
        'code': s.get('code', ''),
        'name': s.get('name', ''),
        'market': s.get('market', ''),
        'plate_name': s.get('plate_name', ''),
        'plate_names': s.get('plate_names', []),
        'is_manual': s.get('is_manual', False),
        'stock_priority': s.get('stock_priority', 0)
    } for s in paginated]

    return PaginatedResponse.create(
        data=stocks,
        page=page,
        page_size=limit,
        total=total,
        message="获取股票列表成功"
    )


@router.get("/data")
async def get_data(
    data_type: str = Query(default="stock-pool", description="数据类型"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
    plate_id: Optional[int] = Query(None, description="板块ID"),
    search: Optional[str] = Query(None, description="搜索关键词")
):
    """通用数据接口 - 从状态管理器获取数据"""
    state = get_state_manager()

    if data_type == 'stock-pool':
        pool_data = state.get_stock_pool()
        return APIResponse.ok(
            data={
                'plates': pool_data['plates'],
                'stocks': pool_data['stocks'],
                'initialized': pool_data['initialized'],
                'last_update': pool_data['last_update']
            },
            message="获取股票池数据成功"
        )

    elif data_type == 'plates':
        pool_data = state.get_stock_pool()
        all_plates = pool_data['plates']
        target_plates = [p for p in all_plates if p.get('is_target', False)]
        target_plates.sort(key=lambda x: x.get('priority', 0), reverse=True)

        total = len(target_plates)
        start = (page - 1) * limit
        paginated = target_plates[start:start + limit]

        plates = [{
            'id': p['id'],
            'plate_code': p['code'],
            'plate_name': p['name'],
            'market': p['market'],
            'stock_count': p['stock_count'],
            'is_target': p['is_target'],
            'is_enabled': p.get('is_enabled', True),
            'priority': p.get('priority', 0)
        } for p in paginated]

        return PaginatedResponse.create(
            data=plates,
            page=page,
            page_size=limit,
            total=total,
            message="获取目标板块列表成功"
        )

    elif data_type == 'stocks':
        pool_data = state.get_stock_pool()
        stocks_data = pool_data['stocks']

        # 筛选
        filtered = []
        for stock in stocks_data:
            if plate_id:
                stock_plate_id = stock.get('plate_id')
                if not stock_plate_id or str(stock_plate_id) != str(plate_id):
                    continue

            if search:
                search_lower = search.lower()
                code = str(stock.get('code', '')).lower()
                name = str(stock.get('name', '')).lower()
                if search_lower not in code and search_lower not in name:
                    continue

            filtered.append(stock)

        total = len(filtered)
        start = (page - 1) * limit
        paginated = filtered[start:start + limit]

        stocks = [{
            'id': s.get('id', 0),
            'code': s.get('code', ''),
            'name': s.get('name', ''),
            'market': s.get('market', ''),
            'plate_name': s.get('plate_name', ''),
            'plate_names': s.get('plate_names', []),
            'is_manual': s.get('is_manual', False),
            'stock_priority': s.get('stock_priority', 0)
        } for s in paginated]

        return PaginatedResponse.create(
            data=stocks,
            page=page,
            page_size=limit,
            total=total,
            message="获取股票列表成功"
        )

    else:
        raise ValidationError(
            message="无效的数据类型",
            details="支持: stock-pool, plates, stocks"
        )


@router.get("/stocks/unsubscribed")
async def get_unsubscribed_stocks(
    market: Optional[str] = Query(None, description="市场筛选 (HK/US)"),
    search: Optional[str] = Query(None, description="搜索股票代码或名称"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    container=Depends(get_container)
):
    """获取未订阅的股票列表

    返回股票池中存在但未被订阅的股票，包含活跃度信息
    支持按市场筛选和搜索股票代码/名称
    """
    try:
        state = get_state_manager()

        # 获取股票池中的所有股票
        pool_data = state.get_stock_pool()
        all_stocks = pool_data.get('stocks', [])

        # 获取已订阅的股票代码
        subscribed_codes = set(container.subscription_manager.subscribed_stocks)

        # 筛选未订阅的股票
        unsubscribed_stocks = []
        for stock in all_stocks:
            stock_code = stock.get('code', '')
            if stock_code not in subscribed_codes:
                # 按市场筛选
                if market and stock.get('market') != market:
                    continue

                # 按搜索关键词筛选（股票代码或名称）
                if search:
                    search_lower = search.lower()
                    stock_name = stock.get('name', '').lower()
                    if search_lower not in stock_code.lower() and search_lower not in stock_name:
                        continue

                unsubscribed_stocks.append(stock)

        # 查询活跃度信息
        stock_codes = [s['code'] for s in unsubscribed_stocks]
        activity_map = {}

        if stock_codes:
            # 从数据库查询活跃度缓存
            placeholders = ','.join(['?' for _ in stock_codes])
            sql = f'''
                SELECT stock_code, is_active, turnover_rate, turnover_amount,
                       check_date
                FROM daily_active_stocks
                WHERE stock_code IN ({placeholders})
                AND date(check_date) = date('now', 'localtime')
            '''
            rows = await container.db_manager.async_execute_query(sql, tuple(stock_codes))

            for row in rows:
                # 生成不活跃原因
                inactive_reason = None
                if row[1] == 0:  # is_active = 0
                    reasons = []
                    if row[2] is not None and row[2] < 0.3:
                        reasons.append(f"换手率{row[2]:.2f}% < 0.3%")
                    if row[3] is not None and row[3] < 10000000:
                        reasons.append(f"成交额{row[3]/10000:.0f}万 < 1000万")
                    inactive_reason = ", ".join(reasons) if reasons else "不满足活跃度条件"

                activity_map[row[0]] = {
                    'is_active': bool(row[1]),
                    'turnover_rate': row[2],
                    'turnover_amount': row[3],
                    'check_date': row[4],
                    'inactive_reason': inactive_reason
                }

        # 合并活跃度信息
        enriched_stocks = []
        for stock in unsubscribed_stocks:
            stock_code = stock['code']
            stock_data = dict(stock)

            # 添加活跃度信息
            if stock_code in activity_map:
                activity = activity_map[stock_code]
                stock_data.update({
                    'is_active': activity['is_active'],
                    'turnover_rate': activity['turnover_rate'],
                    'turnover_amount': activity['turnover_amount'],
                    'activity_check_date': activity['check_date'],
                    'inactive_reason': activity['inactive_reason']
                })
            else:
                stock_data.update({
                    'is_active': None,
                    'turnover_rate': None,
                    'turnover_amount': None,
                    'activity_check_date': None,
                    'inactive_reason': '未检查'
                })

            enriched_stocks.append(stock_data)

        # 排序：不活跃的在前，活跃的在后，未检查的最后
        def sort_key(s):
            if s['is_active'] is None:
                return (2, s.get('name', ''))
            elif s['is_active']:
                return (1, s.get('name', ''))
            else:
                return (0, s.get('name', ''))

        enriched_stocks.sort(key=sort_key)

        # 统计信息
        total = len(enriched_stocks)
        active_count = sum(1 for s in enriched_stocks if s['is_active'] is True)
        inactive_count = sum(1 for s in enriched_stocks if s['is_active'] is False)
        unchecked_count = sum(1 for s in enriched_stocks if s['is_active'] is None)

        # 市场分布统计
        market_counts = {}
        for stock in enriched_stocks:
            m = stock.get('market', 'Unknown')
            market_counts[m] = market_counts.get(m, 0) + 1

        # 分页
        start = (page - 1) * limit
        paginated = enriched_stocks[start:start + limit]

        return PaginatedResponse.create(
            data=paginated,
            page=page,
            page_size=limit,
            total=total,
            message=f"获取未订阅股票成功（共{total}只，不活跃{inactive_count}只，活跃{active_count}只，未检查{unchecked_count}只）",
            extra={
                'subscribed_count': len(subscribed_codes),
                'total_in_pool': len(all_stocks),
                'unsubscribed_count': total,
                'active_count': active_count,
                'inactive_count': inactive_count,
                'unchecked_count': unchecked_count,
                'market_counts': market_counts
            }
        )

    except Exception as e:
        logging.error(f"获取未订阅股票失败: {e}", exc_info=True)
        raise BusinessError(message=f"获取未订阅股票失败: {str(e)}")


@router.get("/stocks/pool-capital-flow")
async def get_pool_capital_flow(container=Depends(get_container)):
    """批量获取股票池所有股票的逐笔成交资金数据（来自 daily_order_accumulator）"""
    try:
        from datetime import datetime as _dt

        state = get_state_manager()
        pool_data = state.get_stock_pool()
        all_stocks = pool_data.get('stocks', [])
        stock_codes = [s.get('code', '') for s in all_stocks if s.get('code')]

        if not stock_codes:
            return APIResponse.ok(data={'flows': {}, 'total': 0}, message="股票池为空")

        db = container.db_manager
        trade_date = _dt.now().strftime("%Y-%m-%d")
        placeholders = ','.join(['?' for _ in stock_codes])

        rows = db.execute_query(f"""
            SELECT stock_code,
                   super_large_buy_amt, super_large_sell_amt,
                   large_buy_amt, large_sell_amt
            FROM daily_order_accumulator
            WHERE stock_code IN ({placeholders}) AND trade_date = ?
        """, tuple(stock_codes) + (trade_date,))

        flows = {}
        for row in (rows or []):
            code = row[0]
            big_buy = float(row[1] or 0) + float(row[3] or 0)
            big_sell = float(row[2] or 0) + float(row[4] or 0)
            net_amount = big_buy - big_sell
            ratio = big_buy / big_sell if big_sell > 0 else (999.0 if big_buy > 0 else 1.0)
            flows[code] = {
                'stock_code': code,
                'big_buy_amount': big_buy,
                'big_sell_amount': big_sell,
                'net_amount': net_amount,
                'buy_sell_ratio': round(ratio, 2),
                'is_net_inflow': net_amount > 0,
                'flow_signal': None,
                'flow_signal_label': None,
                'flow_signal_detail': None,
            }

        # 合并 high_turnover_cache 中的资金流信号
        ht_cache = state.high_turnover_cache.get_all()
        for code in stock_codes:
            cached = ht_cache.get(code)
            if not cached:
                continue
            signal = cached.get('flow_signal')
            if not signal:
                continue
            if code not in flows:
                flows[code] = {
                    'stock_code': code,
                    'big_buy_amount': 0, 'big_sell_amount': 0,
                    'net_amount': 0, 'buy_sell_ratio': 1.0,
                    'is_net_inflow': False,
                }
            flows[code]['flow_signal'] = signal
            flows[code]['flow_signal_label'] = cached.get('flow_signal_label', '')
            flows[code]['flow_signal_detail'] = cached.get('flow_signal_detail', '')

        return APIResponse.ok(
            data={'flows': flows, 'total': len(flows), 'pool_size': len(stock_codes)},
            message=f"获取 {len(flows)}/{len(stock_codes)} 只股票逐笔成交数据"
        )
    except Exception as e:
        logging.error(f"获取股票池逐笔成交数据失败: {e}", exc_info=True)
        raise BusinessError(message=f"获取股票池逐笔成交数据失败: {str(e)}")

