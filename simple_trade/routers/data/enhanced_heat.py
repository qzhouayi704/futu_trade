#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强热度分析 API 路由

提供市场热度、资金流向、大单追踪、三级筛选等接口。
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, Query

from ...core.exceptions import BusinessError
from ...dependencies import get_container
from ...schemas.common import APIResponse
from .helpers.enhanced_heat_helpers import (
    get_realtime_data as _get_realtime_data,
    merge_quotes as _merge_quotes,
    load_kline_data_batch as _load_kline_data_batch,
)


router = APIRouter(prefix="/api/enhanced-heat", tags=["增强热度分析"])


# ==================== 市场热度接口 ====================

@router.get("/market-heat", response_model=APIResponse)
async def get_market_heat(container=Depends(get_container)):
    """获取市场整体热度（基于实时报价数据）"""
    try:
        monitor = container.market_heat_monitor
        quotes_list, quotes_map, plates_monitor, _, all_stock_codes = _get_realtime_data(
            container=container, heat_quote_svc=container.heat_quote_service
        )

        market_heat = monitor.calculate_market_heat(quotes_list)
        sentiment = monitor.detect_market_sentiment(market_heat)
        position_ratio = monitor.recommend_position_ratio(market_heat)
        hot_plates = monitor.get_hot_plates(plates_monitor, quotes_map, top_n=5)

        # 计算全市场统计
        total = len(quotes_list) if quotes_list else 0
        up_count = sum(1 for q in (quotes_list or []) if q.get('change_pct', 0) > 0)
        avg_change = (sum(q.get('change_pct', 0) for q in quotes_list) / total) if total else 0.0

        # 计算报价覆盖率：有报价股票数 / 股票池总数
        pool_size = len(all_stock_codes) if all_stock_codes else 0
        quote_coverage = round(len(quotes_map) / pool_size, 4) if pool_size > 0 else 0.0

        return APIResponse(
            success=True,
            data={
                'market_heat': market_heat,
                'sentiment': sentiment,
                'recommended_position_ratio': position_ratio,
                'hot_plates': hot_plates,
                'up_stock_ratio': round(up_count / total, 4) if total else 0.0,
                'avg_change_pct': round(avg_change, 2),
                'quote_coverage': quote_coverage,
            },
            message=f"市场热度: {market_heat:.1f} ({sentiment})"
        )
    except Exception as e:
        logging.error(f"获取市场热度失败: {e}")
        raise BusinessError(f"获取市场热度失败: {str(e)}")


# ==================== 龙头股接口 ====================

@router.get("/leader-stocks", response_model=APIResponse)
async def get_leader_stocks(
    max_total: int = Query(10, ge=1, le=50, description="最多返回数量"),
    container=Depends(get_container)
):
    """获取龙头股列表（统一筛选流程：活跃度→热门股票→龙头股）"""
    try:
        from ...services.analysis.heat.heat_score_engine import HeatScoreEngine
        from ...services.market_data.hot_stock.hot_stock_filter import HotStockFilter
        from ...services.market_data.hot_stock.leader_stock_identifier import LeaderStockIdentifier

        _, quotes_map, _, plates_filter, all_stock_codes = _get_realtime_data(
            container=container, heat_quote_svc=container.heat_quote_service
        )

        # 股票池未初始化时，从数据库查询活跃股票作为兜底
        if not all_stock_codes:
            loop = asyncio.get_event_loop()
            rows = await loop.run_in_executor(
                None, container.db_manager.execute_query,
                'SELECT code FROM stocks WHERE is_low_activity = 0'
            )
            all_stock_codes = {r[0] for r in rows} if rows else set()

        score_engine = HeatScoreEngine()

        # 第一步：热门股票筛选（活跃度筛选 + 板块内筛选）
        hot_filter = HotStockFilter(score_engine=score_engine)
        hot_stocks_by_plate = hot_filter.get_all_hot_stocks(plates_filter, quotes_map)
        hot_stock_count = sum(len(v) for v in hot_stocks_by_plate.values())

        # 第二步：批量加载 K 线数据（同步数据库查询，放到线程池）
        hot_codes = {s.stock_code for stocks in hot_stocks_by_plate.values() for s in stocks}
        loop = asyncio.get_event_loop()
        kline_data_map = await loop.run_in_executor(
            None, _load_kline_data_batch, container.db_manager, hot_codes
        )

        # 第三步：龙头股识别
        leader_identifier = LeaderStockIdentifier(score_engine=score_engine)
        leaders = leader_identifier.get_all_leaders(
            hot_stocks_by_plate=hot_stocks_by_plate,
            kline_data=kline_data_map,
            quotes_map=quotes_map,
            max_total=max_total,
        )

        # 筛选漏斗统计
        active_count = sum(
            1 for code in all_stock_codes
            if code in quotes_map and (quotes_map[code].get('volume', 0) or 0) > 0
        )
        # 有报价数据的股票数量
        quoted_count = sum(1 for code in all_stock_codes if code in quotes_map)
        screening_stats = {
            'total_count': len(all_stock_codes),
            'level1_count': active_count,
            'level2_count': hot_stock_count,
            'level3_count': len(leaders),
            'quoted_count': quoted_count,
        }

        return APIResponse(
            success=True,
            data={
                'leaders': [l.to_dict() for l in leaders],
                'total': len(leaders),
                'screening_stats': screening_stats,
                'data_ready': len(quotes_map) > 0,
            },
            message=f"获取龙头股成功，共{len(leaders)}只"
        )
    except Exception as e:
        logging.error(f"获取龙头股失败: {e}")
        raise BusinessError(f"获取龙头股失败: {str(e)}")

# ==================== 分时图接口 ====================

@router.get("/intraday-timeline/{stock_code}", response_model=APIResponse)
async def get_intraday_timeline(stock_code: str, container=Depends(get_container)):
    """获取股票当天的分时折线数据"""
    try:
        futu_client = container.futu_client
        timeline_data = []
        is_fallback = False
        
        # 1. 尝试从 Futu API 获取数据
        if futu_client.is_available():
            ret, df = futu_client.get_rt_data(stock_code)
            if ret == 0 and df is not None and not df.empty:
                # 成功获取，将其持久化保存到数据库中
                container.db_manager.rt_data_queries.batch_upsert_rt_data(stock_code, df)
                
                # 转换为前端所需格式
                for _, row in df.iterrows():
                    timeline_data.append({
                        "time": row["time"],
                        "price": float(row["cur_price"]),
                        "avg_price": float(row["avg_price"]),
                        "volume": float(row["volume"]),
                        "turnover": float(row["turnover"])
                    })
                    
        # 2. 如果 API 获取失败、未连接或返回空数据，启用数据库兜底查询
        if not timeline_data:
            timeline_data = container.db_manager.rt_data_queries.get_rt_data(stock_code)
            is_fallback = True
            
        if not timeline_data:
            return APIResponse(success=True, data=[], message="无分时数据")
            
        msg = "获取分时数据成功 (历史缓存)" if is_fallback else "获取分时数据成功"
        return APIResponse(
            success=True,
            data=timeline_data,
            message=msg
        )
    except Exception as e:
        logging.error(f"获取分时数据失败: {stock_code}, {e}")
        raise BusinessError(f"获取分时数据失败: {str(e)}")


@router.get("/capital-flow-timeline/{stock_code}", response_model=APIResponse)
async def get_capital_flow_timeline(stock_code: str, container=Depends(get_container)):
    """获取日内逐笔买卖力量时间线（每分钟一个点）

    优先使用 ticker_data 表（Lee-Ready 方向）聚合真实主动买卖，
    无逐笔数据时降级到旧版富途资金流 API。
    """
    try:
        from datetime import datetime, date as _date
        db = getattr(container, 'db_manager', None)
        today_str = _date.today().isoformat()

        # ====== 1. 尝试从 ticker_data 构建逐笔时间线 ======
        ticker_rows = None
        if db:
            try:
                ticker_rows = db.execute_query("""
                    SELECT
                        substr(datetime(timestamp/1000, 'unixepoch', '+8 hours'), 12, 5) as minute,
                        direction,
                        SUM(turnover) as total_turnover,
                        SUM(volume) as total_volume,
                        AVG(price) as avg_price,
                        COUNT(*) as tick_count
                    FROM ticker_data
                    WHERE stock_code = ? AND trade_date = ?
                    GROUP BY minute, direction
                    ORDER BY minute
                """, (stock_code, today_str))
            except Exception as e:
                logging.debug(f"[逐笔时间线] 查询 ticker_data 失败: {e}")

        if ticker_rows and len(ticker_rows) > 5:
            # 按分钟聚合买/卖
            minute_data: dict = {}  # {minute: {buy_turnover, sell_turnover, avg_price, volume}}
            for row in ticker_rows:
                minute, direction, turnover, volume, avg_price, _ = row
                if minute not in minute_data:
                    minute_data[minute] = {
                        'buy_turnover': 0, 'sell_turnover': 0,
                        'total_volume': 0, 'price_sum': 0, 'price_count': 0
                    }
                entry = minute_data[minute]
                turnover_val = float(turnover or 0)
                if direction == 'BUY':
                    entry['buy_turnover'] += turnover_val
                elif direction == 'SELL':
                    entry['sell_turnover'] += turnover_val
                entry['total_volume'] += int(volume or 0)
                if avg_price and float(avg_price) > 0:
                    entry['price_sum'] += float(avg_price)
                    entry['price_count'] += 1

            # 补充 RT_DATA 股价（更精确）
            price_map = {}
            try:
                rt_rows = db.execute_query("""
                    SELECT substr(time, 12, 5) as t, cur_price
                    FROM rt_data
                    WHERE stock_code = ? AND trade_date = ?
                    ORDER BY time
                """, (stock_code, today_str))
                if rt_rows:
                    for r in rt_rows:
                        if r[1] and float(r[1]) > 0:
                            price_map[r[0]] = float(r[1])
            except Exception:
                pass

            # 构建时间线
            timeline = []
            cum_buy = 0.0
            cum_sell = 0.0
            for minute in sorted(minute_data.keys()):
                entry = minute_data[minute]
                buy_t = entry['buy_turnover']
                sell_t = entry['sell_turnover']
                cum_buy += buy_t
                cum_sell += sell_t
                net_buy = buy_t - sell_t  # 本分钟净主动买入
                cum_net = cum_buy - cum_sell  # 累计净主动买入

                point: dict = {
                    'time': minute,
                    'buy_in': round(buy_t / 10000, 1),     # 本分钟主动买入（万）
                    'sell_in': round(-sell_t / 10000, 1),   # 本分钟主动卖出（万，负值）
                    'net_buy': round(net_buy / 10000, 1),   # 本分钟净主动买入（万）
                    'cum_net': round(cum_net / 10000, 1),   # 累计净主动买入（万）
                    'main_in': round(cum_net / 10000, 1),   # 兼容旧字段
                    'retail_in': 0,                          # 逐笔模式无散户分类
                    'volume': entry['total_volume'],
                }
                # 价格：优先 RT_DATA，其次逐笔均价
                if minute in price_map:
                    point['price'] = round(price_map[minute], 3)
                elif entry['price_count'] > 0:
                    point['price'] = round(entry['price_sum'] / entry['price_count'], 3)

                timeline.append(point)

            return APIResponse(
                success=True,
                data=timeline,
                message=f"逐笔买卖力量时间线 ({len(timeline)} 点)"
            )

        # ====== 2. 降级：旧版富途资金流 API ======
        futu_client = getattr(container, 'futu_client', None)
        if not futu_client or not futu_client.is_available():
            return APIResponse(success=True, data=[], message="无逐笔数据且富途API不可用")

        from futu import RET_OK, PeriodType
        ret, df = futu_client.client.get_capital_flow(stock_code, period_type=PeriodType.INTRADAY)
        if ret != RET_OK:
            return APIResponse(success=True, data=[], message=f"获取资金流数据失败: {df}")

        # 获取分时价格
        price_map = {}
        try:
            rt_ret, rt_df = futu_client.get_rt_data(stock_code)
            if rt_ret == 0 and rt_df is not None and not rt_df.empty:
                for _, rt_row in rt_df.iterrows():
                    rt_time = str(rt_row.get('time', ''))
                    rt_price = float(rt_row.get('cur_price', 0))
                    if len(rt_time) >= 16 and rt_price > 0:
                        price_map[rt_time[11:16]] = rt_price
        except Exception:
            pass

        timeline = []
        for _, row in df.iterrows():
            time_str = str(row.get('capital_flow_item_time', ''))
            time_short = time_str[11:16] if len(time_str) >= 16 else time_str

            super_in = float(row.get('super_in_flow', 0) or 0)
            big_in = float(row.get('big_in_flow', 0) or 0)
            mid_in = float(row.get('mid_in_flow', 0) or 0)
            sml_in = float(row.get('sml_in_flow', 0) or 0)

            main_in = super_in + big_in
            retail_in = mid_in + sml_in

            point = {
                'time': time_short,
                'main_in': round(main_in / 10000, 1),
                'retail_in': round(retail_in / 10000, 1),
                'net_buy': round(main_in / 10000, 1),  # 兼容新字段
                'cum_net': round(main_in / 10000, 1),
            }
            if time_short in price_map:
                point['price'] = round(price_map[time_short], 3)
            timeline.append(point)

        return APIResponse(
            success=True,
            data=timeline,
            message=f"资金流时间线 (旧版, {len(timeline)} 点)"
        )
    except Exception as e:
        logging.error(f"获取资金流时间线失败: {stock_code}, {e}")
        raise BusinessError(f"获取资金流时间线失败: {str(e)}")


# CCASS 内存缓存（同一进程内避免重复查 DB）
_ccass_cache: dict = {}  # key: "stock_code:date" -> result


def _load_ccass_from_db(db_manager, stock_code: str, date_str: str) -> list:
    """从 DB 加载某日的 CCASS 持仓数据"""
    rows = db_manager.execute_query("""
        SELECT participant_id, participant_name, shareholding, percent
        FROM ccass_holdings
        WHERE stock_code = ? AND holding_date = ?
        ORDER BY shareholding DESC
    """, (stock_code, date_str))
    return [{'id': r[0], 'name': r[1], 'shareholding': r[2], 'percent': r[3]} for r in rows] if rows else []


def _save_ccass_to_db(db_manager, stock_code: str, date_str: str, holdings: list):
    """将 CCASS 持仓数据保存到 DB"""
    for h in holdings:
        try:
            db_manager.execute_update("""
                INSERT OR REPLACE INTO ccass_holdings
                (stock_code, holding_date, participant_id, participant_name, shareholding, percent)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (stock_code, date_str, h.get('id', ''), h['name'], h['shareholding'], h.get('percent', 0)))
        except Exception as e:
            logging.debug(f"保存 CCASS 记录失败: {e}")


def _compute_changes(latest_holdings: list, compare_holdings: list) -> dict:
    """从两天的持仓数据计算增持/减持"""
    latest_map = {h['name']: h['shareholding'] for h in latest_holdings}
    compare_map = {h['name']: h['shareholding'] for h in compare_holdings}

    all_names = set(latest_map.keys()) | set(compare_map.keys())
    changes = []
    for name in all_names:
        new_val = latest_map.get(name, 0)
        old_val = compare_map.get(name, 0)
        diff = new_val - old_val
        if diff != 0:
            changes.append({'name': name, 'change': diff, 'shareholding': new_val})

    changes.sort(key=lambda x: x['change'], reverse=True)

    return {
        'top_increases': [c for c in changes if c['change'] > 0][:10],
        'top_decreases': [c for c in changes if c['change'] < 0][-10:][::-1],
    }


@router.get("/ccass-holdings/{stock_code}", response_model=APIResponse)
async def get_ccass_holdings(
    stock_code: str, days: int = 2, container=Depends(get_container)
):
    """获取 CCASS 经纪商持仓变化（T+1 数据）

    优先从数据库读取（避免重复爬取 HKEX）。
    如果 DB 无数据，则爬取并存入 DB。
    """
    import asyncio
    from datetime import datetime as _dt

    today_str = _dt.now().strftime('%Y%m%d')
    cache_key = f"{stock_code}:{today_str}"

    # 1. 内存缓存（最快）
    if cache_key in _ccass_cache:
        return APIResponse(
            success=True, data=_ccass_cache[cache_key],
            message=f"CCASS 持仓变化 (缓存): {stock_code}"
        )

    db = container.db_manager

    # 2. 尝试从 DB 加载（次快）
    try:
        from ...services.data.ccass_scraper import CCASSScraper
        scraper = CCASSScraper()

        # 获取最近两个交易日日期
        dates = scraper._get_recent_trading_dates(days=max(2, min(days, 5)))
        if len(dates) >= 2:
            latest_date, compare_date = dates[0], dates[1]
            db_latest = _load_ccass_from_db(db, stock_code, latest_date)
            db_compare = _load_ccass_from_db(db, stock_code, compare_date)

            if db_latest and db_compare:
                # DB 有数据，直接计算
                result = _compute_changes(db_latest, db_compare)
                result['latest_date'] = latest_date
                result['compare_date'] = compare_date
                _ccass_cache[cache_key] = result
                return APIResponse(
                    success=True, data=result,
                    message=f"CCASS 持仓变化 (DB): {stock_code}"
                )
    except Exception as e:
        logging.debug(f"从 DB 加载 CCASS 失败: {e}")

    # 3. DB 无数据，爬取 HKEX 并保存
    try:
        def _fetch_and_save():
            result = scraper.get_holding_changes(stock_code, days=max(2, min(days, 5)))

            # 保存原始持仓到 DB（如果爬取成功）
            if result.get('_raw_latest'):
                _save_ccass_to_db(db, stock_code, result['latest_date'], result['_raw_latest'])
            if result.get('_raw_compare'):
                _save_ccass_to_db(db, stock_code, result['compare_date'], result['_raw_compare'])

            # 移除内部字段
            result.pop('_raw_latest', None)
            result.pop('_raw_compare', None)
            return result

        result = await asyncio.get_event_loop().run_in_executor(None, _fetch_and_save)

        if 'error' in result and not result.get('top_increases'):
            return APIResponse(success=False, data=None, message=result['error'])

        _ccass_cache[cache_key] = result
        return APIResponse(
            success=True, data=result,
            message=f"CCASS 持仓变化: {stock_code}"
        )
    except Exception as e:
        logging.error(f"获取 CCASS 数据失败: {stock_code}, {e}")
        raise BusinessError(f"获取 CCASS 数据失败: {str(e)}")


logging.info("增强热度分析路由已注册")
