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


def _detect_absorption(timeline: list) -> dict | None:
    """检测买入吸收异常：连续主买但价格不涨，说明有大量隐性卖单压盘

    扫描条件：
    - 滑动窗口内 ≥5 分钟连续净买入为正
    - 窗口期间股价涨幅 ≤ 0.1% (几乎持平或下跌)
    - 累计净买入额 > 0 (确认确实是资金流入)

    Returns:
        dict with detected=True/False, details if detected
    """
    MIN_WINDOW = 5         # 最少连续5分钟
    PRICE_THRESHOLD = 0.1  # 价格变化阈值 ±0.1%

    if not timeline or len(timeline) < MIN_WINDOW:
        return None

    # 只检查有价格数据的点
    priced = [p for p in timeline if p.get('price', 0) > 0]
    if len(priced) < MIN_WINDOW:
        return None

    best = None  # 记录最强的吸收段

    # 滑动窗口扫描
    i = 0
    while i < len(priced):
        # 找连续净买入起点
        if priced[i].get('net_buy', 0) <= 0:
            i += 1
            continue

        # 扩展窗口
        j = i
        while j < len(priced) and priced[j].get('net_buy', 0) > 0:
            j += 1

        window_len = j - i
        if window_len >= MIN_WINDOW:
            start_price = priced[i]['price']
            end_price = priced[j - 1]['price']
            price_change_pct = (end_price - start_price) / start_price * 100 if start_price > 0 else 0
            cum_buy_in_window = sum(p.get('net_buy', 0) for p in priced[i:j])

            # 核心判据：持续买入 + 价格不涨
            if price_change_pct <= PRICE_THRESHOLD and cum_buy_in_window > 0:
                severity = 'high' if window_len >= 8 or (window_len >= 5 and price_change_pct < -0.1) else 'medium'
                candidate = {
                    'detected': True,
                    'severity': severity,
                    'start_time': priced[i].get('time', ''),
                    'end_time': priced[j - 1].get('time', ''),
                    'duration_min': window_len,
                    'price_change_pct': round(price_change_pct, 2),
                    'cum_net_buy': round(cum_buy_in_window, 1),
                    'start_price': round(start_price, 3),
                    'end_price': round(end_price, 3),
                    'message': f"{priced[i].get('time','')}~{priced[j-1].get('time','')}"
                               f" 连续{window_len}分钟主买 净买{cum_buy_in_window:.0f}万"
                               f" 但股价{'下跌' if price_change_pct < -0.05 else '持平'}"
                               f"({price_change_pct:+.2f}%)，疑似大量压单吸收",
                }
                if best is None or window_len > best['duration_min']:
                    best = candidate

        i = j  # 跳到窗口结束

    return best


def _compute_flow_summary(timeline: list) -> dict:
    """从时间线数据计算资金流动能摘要"""
    if not timeline or len(timeline) < 3:
        return {}

    # 基础指标
    total_buy = sum(p.get('buy_in', 0) for p in timeline)
    total_sell = sum(abs(p.get('sell_in', 0)) for p in timeline)
    cum_net = timeline[-1].get('cum_net', 0)
    buy_sell_ratio = min(round(total_buy / total_sell, 2), 9.99) if total_sell > 0 else (9.99 if total_buy > 0 else 1.0)

    # 前后半段动能对比
    mid = len(timeline) // 2
    first_half_net = sum(p.get('net_buy', 0) for p in timeline[:mid])
    second_half_net = sum(p.get('net_buy', 0) for p in timeline[mid:])
    if abs(first_half_net) > 0:
        momentum_change = round((second_half_net - first_half_net) / abs(first_half_net) * 100)
    else:
        momentum_change = 100 if second_half_net > 0 else -100 if second_half_net < 0 else 0

    # 最近 5 分钟趋势
    recent = timeline[-min(5, len(timeline)):]
    recent_net = sum(p.get('net_buy', 0) for p in recent)

    # 动能标签
    if cum_net > 0:
        if momentum_change > 30:
            momentum_label = '加速流入'
            signal = 'bullish'
        elif momentum_change > -20:
            momentum_label = '稳定流入'
            signal = 'bullish'
        else:
            momentum_label = '减速流入'
            signal = 'warning'
    elif cum_net < 0:
        if momentum_change < -30:
            momentum_label = '加速流出'
            signal = 'bearish'
        elif momentum_change < 20:
            momentum_label = '稳定流出'
            signal = 'bearish'
        else:
            momentum_label = '减速流出'
            signal = 'warning'
    else:
        momentum_label = '震荡'
        signal = 'neutral'

    # 最近趋势微调
    if signal in ('bullish', 'warning') and recent_net < -abs(cum_net) * 0.05:
        signal = 'warning'
        if momentum_label == '加速流入':
            momentum_label = '冲高回落'
    elif signal in ('bearish', 'warning') and recent_net > abs(cum_net) * 0.05:
        signal = 'warning'
        if momentum_label == '加速流出':
            momentum_label = '跌后回升'

    return {
        'momentum_label': momentum_label,
        'momentum_change': momentum_change,
        'signal': signal,
        'buy_sell_ratio': buy_sell_ratio,
        'cum_net': round(cum_net, 1),
        'recent_net': round(recent_net, 1),
        'first_half_net': round(first_half_net, 1),
        'second_half_net': round(second_half_net, 1),
        'absorption': _detect_absorption(timeline),
    }

# ==================== 日内资金动能扫描 ====================

@router.get("/flow-momentum-scan", response_model=APIResponse)
async def flow_momentum_scan(container=Depends(get_container)):
    """扫描所有已有逐笔数据的股票，按资金动能排序返回

    用于快速发现"加速流入"等强势资金形态的标的。
    """
    try:
        from datetime import date as _date
        db = getattr(container, 'db_manager', None)
        if not db:
            return APIResponse(success=True, data=[], message="数据库不可用")

        today_str = _date.today().isoformat()

        # 一次性查询所有股票的分钟级聚合数据
        rows = db.execute_query("""
            SELECT
                stock_code,
                substr(datetime(timestamp/1000, 'unixepoch', '+8 hours'), 12, 5) as minute,
                direction,
                SUM(turnover) as total_turnover,
                SUM(volume) as total_volume,
                AVG(price) as avg_price
            FROM ticker_data
            WHERE trade_date = ?
            GROUP BY stock_code, minute, direction
            ORDER BY stock_code, minute
        """, (today_str,))

        if not rows:
            return APIResponse(success=True, data=[], message="今日暂无逐笔数据")

        # 交易时段过滤
        def _in_trading(hhmm: str) -> bool:
            try:
                return '09:15' <= hhmm <= '16:10'
            except (TypeError, ValueError):
                return False

        # 按股票分组，构建每只股票的时间线
        from collections import defaultdict
        stock_minutes = defaultdict(lambda: defaultdict(lambda: {'buy': 0.0, 'sell': 0.0, 'vol': 0, 'price_sum': 0.0, 'price_n': 0}))

        for row in rows:
            code, minute, direction, turnover, volume, avg_price = row
            if not _in_trading(minute):
                continue
            entry = stock_minutes[code][minute]
            tv = float(turnover or 0)
            if direction == 'BUY':
                entry['buy'] += tv
            elif direction == 'SELL':
                entry['sell'] += tv
            entry['vol'] += int(volume or 0)
            if avg_price and float(avg_price) > 0:
                entry['price_sum'] += float(avg_price)
                entry['price_n'] += 1

        # 为每只股票计算时间线和摘要
        results = []
        for code, minutes_data in stock_minutes.items():
            if len(minutes_data) < 5:
                continue  # 数据太少跳过

            timeline = []
            cum_buy = 0.0
            cum_sell = 0.0
            for minute in sorted(minutes_data.keys()):
                e = minutes_data[minute]
                buy_t = e['buy']
                sell_t = e['sell']
                cum_buy += buy_t
                cum_sell += sell_t
                net = buy_t - sell_t
                cum_net = cum_buy - cum_sell
                point = {
                    'time': minute,
                    'buy_in': round(buy_t / 10000, 1),
                    'sell_in': round(-sell_t / 10000, 1),
                    'net_buy': round(net / 10000, 1),
                    'cum_net': round(cum_net / 10000, 1),
                }
                if e['price_n'] > 0:
                    point['price'] = round(e['price_sum'] / e['price_n'], 3)
                timeline.append(point)

            summary = _compute_flow_summary(timeline)
            if not summary:
                continue

            # 取最新价格
            last_price = 0
            for p in reversed(timeline):
                if p.get('price', 0) > 0:
                    last_price = p['price']
                    break

            results.append({
                'stock_code': code,
                'price': last_price,
                'data_points': len(timeline),
                **summary,
            })

        # 批量获取股票名称
        all_codes = [r['stock_code'] for r in results]
        name_map = {}
        if all_codes:
            try:
                placeholders = ','.join(['?' for _ in all_codes])
                name_rows = db.execute_query(
                    f"SELECT code, name FROM stocks WHERE code IN ({placeholders})",
                    tuple(all_codes)
                )
                name_map = {r[0]: r[1] for r in name_rows} if name_rows else {}
            except Exception:
                pass

        for r in results:
            r['stock_name'] = name_map.get(r['stock_code'], '')

        # 按信号优先级 + 动能排序
        signal_order = {'bullish': 0, 'warning': 1, 'neutral': 2, 'bearish': 3}
        results.sort(key=lambda x: (
            signal_order.get(x.get('signal', 'neutral'), 2),
            -abs(x.get('momentum_change', 0)),
            -abs(x.get('cum_net', 0)),
        ))

        return APIResponse(
            success=True,
            data=results,
            message=f"扫描 {len(stock_minutes)} 只股票，{len(results)} 只有效"
        )
    except Exception as e:
        logging.error(f"资金动能扫描失败: {e}")
        raise BusinessError(f"资金动能扫描失败: {str(e)}")


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

        # 港股交易时段过滤：只保留 09:15 ~ 16:10 的数据点
        def _in_trading_hours(hhmm: str) -> bool:
            """判断 HH:MM 格式的时间是否在港股交易时段内"""
            try:
                return '09:15' <= hhmm <= '16:10'
            except (TypeError, ValueError):
                return False

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
                if not _in_trading_hours(minute):
                    continue
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

            summary = _compute_flow_summary(timeline)
            return APIResponse(
                success=True,
                data={'timeline': timeline, 'summary': summary},
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
        prev_main_cum = 0.0
        prev_retail_cum = 0.0
        for _, row in df.iterrows():
            time_str = str(row.get('capital_flow_item_time', ''))
            time_short = time_str[11:16] if len(time_str) >= 16 else time_str
            if not _in_trading_hours(time_short):
                continue

            super_in = float(row.get('super_in_flow', 0) or 0)
            big_in = float(row.get('big_in_flow', 0) or 0)
            mid_in = float(row.get('mid_in_flow', 0) or 0)
            sml_in = float(row.get('sml_in_flow', 0) or 0)

            main_cum = super_in + big_in      # 富途API返回的是累计值
            retail_cum = mid_in + sml_in

            # 差分得到本分钟净流入
            main_delta = main_cum - prev_main_cum
            retail_delta = retail_cum - prev_retail_cum
            prev_main_cum = main_cum
            prev_retail_cum = retail_cum

            # buy_in / sell_in 从 delta 拆分
            buy_in = max(main_delta, 0)
            sell_in = min(main_delta, 0)

            point = {
                'time': time_short,
                'main_in': round(main_cum / 10000, 1),
                'retail_in': round(retail_cum / 10000, 1),
                'buy_in': round(buy_in / 10000, 1),
                'sell_in': round(sell_in / 10000, 1),
                'net_buy': round(main_delta / 10000, 1),
                'cum_net': round(main_cum / 10000, 1),
            }
            if time_short in price_map:
                point['price'] = round(price_map[time_short], 3)
            timeline.append(point)

        summary = _compute_flow_summary(timeline)
        return APIResponse(
            success=True,
            data={'timeline': timeline, 'summary': summary},
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


# ==================== 量价异常预警（全量扫描） ====================


async def _get_alert_stock_codes(container, db, source: str) -> list:
    """根据 source 参数获取目标股票代码列表

    Args:
        source: 'focus' = 仅狙击+优选股, 'all' = 全部订阅股票
    """
    if source == 'focus':
        # 从狙击信号 + 盘后优选收集股票
        focus_codes = set()
        try:
            # 1. 今日狙击信号股
            sniper_rows = await db.async_execute_query("""
                SELECT DISTINCT stock_code FROM sniper_signals
                WHERE DATE(created_at) = DATE('now', 'localtime')
            """)
            if sniper_rows:
                focus_codes.update(r[0] for r in sniper_rows)
        except Exception:
            pass
        try:
            # 2. 最新盘后优选股
            overnight_rows = await db.async_execute_query("""
                SELECT DISTINCT stock_code FROM overnight_screen_results
                WHERE screen_date = (
                    SELECT MAX(screen_date) FROM overnight_screen_results
                )
            """)
            if overnight_rows:
                focus_codes.update(r[0] for r in overnight_rows)
        except Exception:
            pass
        # 3. 当前持仓股也纳入
        try:
            from ..trading.trade_helpers import ensure_trade_service
            trade_service = ensure_trade_service(container)
            result = trade_service.get_positions()
            if result.get('success') and result.get('positions'):
                focus_codes.update(p['stock_code'] for p in result['positions'])
        except Exception:
            pass
        return list(focus_codes)
    else:
        # 全部订阅股票
        sub_mgr = getattr(container, 'subscription_manager', None)
        if sub_mgr and hasattr(sub_mgr, 'subscribed_stocks'):
            return list(sub_mgr.subscribed_stocks)
        return []

@router.get("/volume-price-alerts")
async def get_volume_price_alerts(
    source: str = Query("all", description="股票来源: all=全部订阅, focus=狙击+优选"),
    container=Depends(get_container)
):
    """扫描股票的量价异常（吸收+拉升），供首页预警卡片使用"""
    from ...services.analysis.absorption_scanner import AbsorptionScanner

    db = getattr(container, 'db_manager', None)
    if not db:
        return APIResponse(success=True, data=[], message="数据库不可用")

    # 获取目标股票代码
    codes = await _get_alert_stock_codes(container, db, source)

    if not codes:
        return APIResponse(success=True, data=[], message="无目标股票")

    scanner = AbsorptionScanner(db)
    # 不受冷却限制 — 清空冷却记录
    scanner._cooldown.clear()

    loop = asyncio.get_running_loop()
    alerts = await loop.run_in_executor(None, scanner.scan_all, codes)

    return APIResponse(
        success=True,
        data=alerts,
        message=f"量价扫描完成: {len(alerts)} 条预警, 共扫描 {len(codes)} 只股票"
    )


# ==================== Delta 量价背离扫描 ====================

@router.get("/delta-divergence-alerts")
async def get_delta_divergence_alerts(
    source: str = Query("all", description="股票来源: all=全部订阅, focus=狙击+优选"),
    container=Depends(get_container)
):
    """5分钟K线量价背离扫描

    检测两种模式:
    1. 跌势量缩(看涨): 价格下跌但成交量在萎缩 → 抛压衰竭，可能反弹
    2. 涨势量缩(看跌): 价格上涨但成交量在萎缩 → 动能不足，可能回调
    """
    from collections import defaultdict
    from datetime import date as _date, datetime as _dt, timezone, timedelta

    db = getattr(container, 'db_manager', None)
    if not db:
        return APIResponse(success=True, data=[], message="数据库不可用")

    codes = await _get_alert_stock_codes(container, db, source)
    if not codes:
        return APIResponse(success=True, data=[], message="无目标股票")

    today_str = _date.today().isoformat()
    placeholders = ','.join(['?' for _ in codes])

    try:
        rows = db.execute_query(f"""
            SELECT
                stock_code,
                CAST(timestamp / 300000 AS INTEGER) * 300000 as bar_ts,
                SUM(CASE WHEN direction='BUY' THEN volume ELSE 0 END) as buy_vol,
                SUM(CASE WHEN direction='SELL' THEN volume ELSE 0 END) as sell_vol,
                SUM(volume) as total_vol,
                AVG(price) as avg_price
            FROM ticker_data
            WHERE stock_code IN ({placeholders}) AND trade_date = ?
            GROUP BY stock_code, bar_ts
            ORDER BY stock_code, bar_ts
        """, (*codes, today_str))
    except Exception as e:
        logging.debug(f"[Delta背离] 查询失败: {e}")
        return APIResponse(success=True, data=[], message="查询失败")

    if not rows:
        return APIResponse(success=True, data=[], message="今日无逐笔数据")

    # 按股票分组
    stock_bars = defaultdict(list)
    for row in rows:
        code, bar_ts, buy_vol, sell_vol, total_vol, avg_price = row
        stock_bars[code].append({
            'bar_ts': bar_ts,
            'total_vol': total_vol or 0,
            'delta': (buy_vol or 0) - (sell_vol or 0),
            'avg_price': float(avg_price) if avg_price else 0,
        })

    # 股票名称
    name_map = {}
    try:
        name_rows = db.execute_query(
            f"SELECT code, name FROM stocks WHERE code IN ({placeholders})",
            tuple(codes)
        )
        if name_rows:
            name_map = {r[0]: r[1] for r in name_rows}
    except Exception:
        pass

    tz8 = timezone(timedelta(hours=8))
    now = _dt.now()
    alerts = []

    for code, all_bars in stock_bars.items():
        # 过滤午休时段 (12:00~13:00) 的 bar，避免假信号
        bars = []
        for b in all_bars:
            bar_hhmm = _dt.fromtimestamp(b['bar_ts'] / 1000, tz=tz8).strftime('%H:%M')
            if '12:00' <= bar_hhmm < '13:00':
                continue
            bars.append(b)

        if len(bars) < 6:
            continue

        recent = bars[-6:]  # 最近6根5分钟K线 (30分钟)

        prices = [b['avg_price'] for b in recent if b['avg_price'] > 0]
        if len(prices) < 4:
            continue
        price_change = (prices[-1] - prices[0]) / prices[0] * 100

        # 成交量趋势: 后3根 vs 前3根
        first_vol = sum(b['total_vol'] for b in recent[:3])
        second_vol = sum(b['total_vol'] for b in recent[3:])
        if first_vol <= 0:
            continue
        vol_ratio = second_vol / first_vol

        # Delta趋势
        first_delta = sum(b['delta'] for b in recent[:3])
        second_delta = sum(b['delta'] for b in recent[3:])

        # 时间
        start_t = _dt.fromtimestamp(recent[0]['bar_ts'] / 1000, tz=tz8).strftime('%H:%M')
        end_t = _dt.fromtimestamp(recent[-1]['bar_ts'] / 1000, tz=tz8).strftime('%H:%M')

        # 新鲜度检查: end_time 距当前不超过30分钟
        try:
            eh, em = int(end_t[:2]), int(end_t[3:5])
            diff = (now.hour * 60 + now.minute) - (eh * 60 + em)
            if diff > 30:
                continue
        except (ValueError, IndexError):
            pass

        divergence = None

        # 1. 跌势量缩 → 看涨背离: 价格跌 + 量缩
        if price_change < -0.3 and vol_ratio < 0.7:
            delta_improving = second_delta > first_delta
            severity = 'high' if (vol_ratio < 0.5 and delta_improving) else 'medium'
            divergence = {
                'div_type': 'bullish',
                'label': '跌势量缩',
                'hint': '抛压衰竭，关注反弹',
                'severity': severity,
            }

        # 2. 涨势量缩 → 看跌背离: 价格涨 + 量缩
        elif price_change > 0.3 and vol_ratio < 0.7:
            delta_weakening = second_delta < first_delta
            severity = 'high' if (vol_ratio < 0.5 and delta_weakening) else 'medium'
            divergence = {
                'div_type': 'bearish',
                'label': '涨势量缩',
                'hint': '动能不足，警惕回调',
                'severity': severity,
            }

        if divergence:
            alerts.append({
                'stock_code': code,
                'stock_name': name_map.get(code, ''),
                'start_time': start_t,
                'end_time': end_t,
                'price_change_pct': round(price_change, 2),
                'vol_ratio': round(vol_ratio, 2),
                'last_price': round(prices[-1], 3),
                **divergence,
            })

    alerts.sort(key=lambda x: (0 if x['severity'] == 'high' else 1, x['vol_ratio']))

    return APIResponse(
        success=True,
        data=alerts,
        message=f"量价背离扫描: {len(alerts)} 条, 共扫描 {len(stock_bars)} 只"
    )


# ==================== 板块预警（全量扫描） ====================

@router.get("/plate-alerts", response_model=APIResponse)
async def get_plate_alerts(container=Depends(get_container)):
    """扫描所有板块，生成板块级异动预警

    预警类型:
    - surge: 板块大涨（平均涨幅 >= 2%）
    - plunge: 板块大跌（平均跌幅 <= -2%）
    - concentration: 板块内 >= 70% 个股同向（齐涨/齐跌）
    - divergence: 板块热度高但涨幅为负（资金异动）
    """
    try:
        monitor = container.market_heat_monitor
        _, quotes_map, plates_monitor, _, _ = _get_realtime_data(
            container=container, heat_quote_svc=container.heat_quote_service
        )

        if not plates_monitor or not quotes_map:
            return APIResponse(success=True, data=[], message="暂无板块数据")

        # 计算所有板块信息
        all_plates = []
        for plate in plates_monitor:
            info = monitor._calculate_plate_info(plate, quotes_map)
            info['stock_codes'] = plate.get('stocks', [])
            all_plates.append(info)

        alerts = []

        for p in all_plates:
            avg_chg = p.get('avg_change_pct', 0)
            up_ratio = p.get('up_ratio', 0)
            heat = p.get('heat_score', 0)
            stock_count = p.get('stock_count', 0)
            hot_count = p.get('hot_stock_count', 0)
            leader = p.get('leading_stock_name', '')

            # 收集板块内个股涨跌细节
            codes = p.get('stock_codes', [])
            plate_quotes = [quotes_map[c] for c in codes if c in quotes_map]
            n = len(plate_quotes)
            if n < 3:
                continue

            changes = [q.get('change_pct', 0) for q in plate_quotes]
            down_ratio = sum(1 for c in changes if c < 0) / n

            # 领涨/领跌股
            top_stock = max(plate_quotes, key=lambda q: q.get('change_pct', 0))
            bot_stock = min(plate_quotes, key=lambda q: q.get('change_pct', 0))

            base = {
                'plate_code': p['plate_code'],
                'plate_name': p['plate_name'],
                'avg_change_pct': round(avg_chg, 2),
                'up_ratio': round(up_ratio, 4),
                'heat_score': round(heat, 1),
                'stock_count': stock_count,
                'hot_stock_count': hot_count,
                'leader': leader,
            }

            # --- 板块大涨 ---
            if avg_chg >= 2.0:
                severity = 'high' if avg_chg >= 4.0 else 'medium'
                alerts.append({
                    **base,
                    'alert_type': 'surge',
                    'severity': severity,
                    'top_stock_name': top_stock.get('stock_name', ''),
                    'top_stock_change': round(top_stock.get('change_pct', 0), 2),
                    'message': f"板块整体大涨{avg_chg:+.1f}%，{hot_count}只涨超3%，领涨{leader}",
                })

            # --- 板块大跌 ---
            if avg_chg <= -2.0:
                severity = 'high' if avg_chg <= -4.0 else 'medium'
                alerts.append({
                    **base,
                    'alert_type': 'plunge',
                    'severity': severity,
                    'bot_stock_name': bot_stock.get('stock_name', ''),
                    'bot_stock_change': round(bot_stock.get('change_pct', 0), 2),
                    'message': f"板块整体大跌{avg_chg:+.1f}%，{int(down_ratio*100)}%个股下跌",
                })

            # --- 齐涨/齐跌集中度 ---
            if up_ratio >= 0.75 and avg_chg >= 1.0:
                alerts.append({
                    **base,
                    'alert_type': 'concentration',
                    'direction': 'up',
                    'severity': 'medium',
                    'concentration_pct': round(up_ratio * 100, 0),
                    'message': f"{int(up_ratio*100)}%个股上涨，板块齐升{avg_chg:+.1f}%",
                })
            elif down_ratio >= 0.75 and avg_chg <= -1.0:
                alerts.append({
                    **base,
                    'alert_type': 'concentration',
                    'direction': 'down',
                    'severity': 'medium',
                    'concentration_pct': round(down_ratio * 100, 0),
                    'message': f"{int(down_ratio*100)}%个股下跌，板块齐跌{avg_chg:+.1f}%",
                })

            # --- 热度-涨幅背离（板块高热度但涨幅为负，可能轮动） ---
            if heat >= 60 and avg_chg < -0.5:
                alerts.append({
                    **base,
                    'alert_type': 'divergence',
                    'severity': 'medium',
                    'message': f"热度{heat:.0f}但跌{avg_chg:+.1f}%，资金异动或轮动",
                })

        # 排序：高危优先，然后按涨幅绝对值
        alerts.sort(key=lambda x: (
            0 if x['severity'] == 'high' else 1,
            -abs(x.get('avg_change_pct', 0)),
        ))

        return APIResponse(
            success=True,
            data=alerts,
            message=f"板块预警: {len(alerts)} 条, 扫描 {len(all_plates)} 个板块"
        )
    except Exception as e:
        logging.error(f"板块预警扫描失败: {e}")
        raise BusinessError(f"板块预警扫描失败: {str(e)}")


logging.info("增强热度分析路由已注册")

