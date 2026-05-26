#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 股票分析 API 路由

提供独立的 AI 分析 endpoint，供选股工作台和交易决策中心使用。
"""

import asyncio
import logging
from fastapi import APIRouter, Depends, Query

from ...dependencies import get_container
from ...schemas.common import APIResponse

router = APIRouter(prefix="/api/ai-analysis", tags=["AI分析"])
logger = logging.getLogger(__name__)


@router.post("/analyze", response_model=APIResponse)
async def analyze_stock(
    stock_code: str = Query(..., description="股票代码"),
    container=Depends(get_container),
):
    """对单只股票执行 AI 分析

    从系统获取该股票的实时行情、K线数据、评分等信息，
    连同规则知识库发送给 Gemini 进行分析。
    """
    analyzer = container.stock_ai_analyzer
    if not analyzer or not analyzer.is_available():
        return APIResponse(
            success=False,
            message="AI 分析服务不可用���请检查 Gemini API Key 配置）",
        )

    try:
        # 1. 获取实时行情
        logger.info(f"[AI分析API] 收到分析请求: {stock_code}")
        quote = _get_stock_quote(container, stock_code)
        if not quote:
            return APIResponse(
                success=False,
                message=f"无法获取 {stock_code} 的实时行情",
            )

        stock_name = quote.get('name', quote.get('stock_name', stock_code))

        # 2. 获取 K线数据
        klines = _get_kline_data(container, stock_code)

        # 3. 获取评分结果（如果有缓存）
        score_result = _get_score_result(container, stock_code, quote, klines)

        # 4. 获取板块信息
        plate_info = _get_plate_info(container, stock_code)

        # 5. 获取持仓信息（如果是持仓股票）
        position_info = _get_position_info(container, stock_code)

        # 6. 异步获取消息面（不阻塞，失败不影响分析）
        news_data = await _get_stock_news(container, stock_code, stock_name)

        # 6.5 获取实时逐笔成交 / 资金流信号
        flow_data = _get_intraday_flow_data(container, stock_code)

        # 7. 获取逐笔资金流时间线摘要（动能标签、买卖比、前后半段对比）
        capital_flow_summary = await _get_capital_flow_summary(container, stock_code)

        # 8. 获取日内支撑/阻力位 + 经纪商席位分析
        intraday_levels_data = await _get_intraday_levels_data(container, stock_code)

        logger.info(
            f"[AI分析API] {stock_code} 数据聚合完成 | "
            f"行情: {'\u2713' if quote else '\u2717'} | "
            f"K线: {len(klines) if klines else 0}条 | "
            f"板块: {'\u2713' if plate_info else '\u2717'} | "
            f"持仓: {'\u2713' if position_info else '\u2717'} | "
            f"消息面: {len(news_data.get('news', [])) if news_data else 0}条 | "
            f"资金流: {'\u2713' if flow_data else '\u2717'} | "
            f"时间线摘要: {'\u2713' if capital_flow_summary else '\u2717'} | "
            f"支撑阻力: {'\u2713' if intraday_levels_data else '\u2717'}"
        )

        # 9. 执行 AI 分析
        result = await analyzer.analyze_stock(
            stock_code=stock_code,
            stock_name=stock_name,
            quote=quote,
            klines=klines,
            score_result=score_result,
            plate_info=plate_info,
            position_info=position_info,
            news_data=news_data,
            flow_data=flow_data,
            capital_flow_summary=capital_flow_summary,
            intraday_levels_data=intraday_levels_data,
        )

        if result.get('success'):
            return APIResponse(
                success=True,
                data=result.get('data'),
                message=f"AI 分析完成{'（缓存）' if result.get('from_cache') else ''}",
            )
        else:
            return APIResponse(
                success=False,
                message=result.get('error', 'AI 分析失败'),
            )

    except Exception as e:
        logger.error(f"AI 分析接口异常 {stock_code}: {e}", exc_info=True)
        return APIResponse(success=False, message=f"分析异常: {str(e)}")


@router.delete("/cache", response_model=APIResponse)
async def clear_cache(
    stock_code: str = Query(None, description="股票代码（空则清除全部）"),
    container=Depends(get_container),
):
    """\u6e05\u9664 AI \u5206\u6790\u7f13\u5b58"""
    analyzer = container.stock_ai_analyzer
    if analyzer:
        analyzer.clear_cache(stock_code)
    target = stock_code or "\u5168\u90e8"
    logger.info(f"[AI\u5206\u6790API] \u7f13\u5b58\u5df2\u6e05\u9664: {target}")
    return APIResponse(success=True, message="\u7f13\u5b58\u5df2\u6e05\u9664")


# ==================== 辅助函数 ====================

def _get_stock_quote(container, stock_code: str) -> dict:
    """从缓存或实时查询获取股票行情"""
    # 优先从缓存获取
    from ...core import get_state_manager
    state = get_state_manager()
    if state:
        quotes = state.get_cached_quotes() or []
        for q in quotes:
            if q.get('code', '') == stock_code:
                return q

    # 缓存没有，尝试实时查询
    realtime = getattr(container, 'realtime_query', None) or \
               getattr(getattr(container, 'data', None), 'realtime_query', None)
    if realtime:
        try:
            result = realtime.get_realtime_quotes([stock_code])
            if result.get('success') and result.get('quotes'):
                return result['quotes'][0]
        except Exception as e:
            logger.warning(f"实时查询 {stock_code} 行情失败: {e}")

    return {}


def _get_kline_data(container, stock_code: str) -> list:
    """从数据库获取K线数据"""
    db = container.db_manager
    if not db:
        return []
    try:
        klines = db.kline_queries.get_stock_kline(stock_code, days=30)
        return klines or []
    except Exception as e:
        logger.debug(f"获取 {stock_code} K线数据失败: {e}")
        return []


def _get_score_result(container, stock_code: str, quote: dict, klines: list) -> dict:
    """使用 StockScorer 计算多策略评分结果

    调用 score_all_strategies 获取 TREND + BREAKOUT + MOMENTUM 三套策略的独立评分，
    与前端 consensus 展示对齐，避免 AI 看到的分数与页面不一致。
    """
    scorer = getattr(container, 'stock_scorer', None)
    if not scorer or not quote:
        return {}
    try:
        indicators = _compute_scoring_indicators(quote, klines)
        if not indicators:
            return {}
        stock_name = quote.get('name', quote.get('stock_name', stock_code))
        all_scores = scorer.score_all_strategies(stock_code, stock_name, indicators)
        best = all_scores['best']

        # 构建包含所有策略的评分结果
        result = best.to_dict()

        # 附加各策略独立评分，让 AI 了解完整信息
        strategies_summary = []
        for mode_key in ('trend', 'breakout', 'momentum'):
            sr = all_scores[mode_key]
            triggered = True
            if mode_key == 'breakout':
                triggered = all_scores.get('breakout_triggered', False)
            elif mode_key == 'momentum':
                triggered = all_scores.get('momentum_triggered', False)
            strategies_summary.append({
                'mode': sr.mode,
                'total_score': sr.total_score,
                'passed': sr.passed,
                'triggered': triggered,
                'details': [
                    {'dimension': d.dimension, 'value': d.value,
                     'score': d.score, 'max': d.max_score, 'note': d.note}
                    for d in sr.details
                ],
            })
        result['strategies'] = strategies_summary
        result['best_mode'] = best.mode
        return result
    except Exception as e:
        logger.debug(f"计算 {stock_code} 评分失败: {e}")
        return {}


def _compute_scoring_indicators(quote: dict, klines: list) -> dict:
    """从行情和K线数据计算评分所需指标

    对齐 TrendReversalStrategy 的6个买入条件：
    - 条件②距高点跌幅 → kline_pos_20d
    - 条件③距低点反弹 → rise_from_low (新增)
    - 条件④今日阳线   → today_change (新增)
    - 条件⑤反弹放量   → vol_ratio
    """
    indicators = {}

    # 日振幅
    high = quote.get('high_price', 0)
    low = quote.get('low_price', 0)
    prev_close = quote.get('prev_close_price', quote.get('last_close_price', 0))
    if prev_close > 0 and high > 0 and low > 0:
        indicators['day_amplitude'] = (high - low) / prev_close * 100

    # 量比
    indicators['vol_ratio'] = quote.get('volume_ratio', None)

    # 资金流净比率
    indicators['flow_ratio'] = quote.get('net_inflow_ratio', None)

    # 今日涨跌幅 (对齐TrendReversal条件④: 今日阳线反转)
    last_price = quote.get('last_price', 0)
    if prev_close > 0 and last_price > 0:
        indicators['today_change'] = (last_price - prev_close) / prev_close * 100

    # 从 K 线计算趋势指标
    if klines and len(klines) >= 2:
        closes = [k.get('close', 0) for k in klines if k.get('close', 0) > 0]

        # 前日涨幅
        if len(closes) >= 2:
            indicators['prev_day_change'] = (closes[-1] - closes[-2]) / closes[-2] * 100

        # 5日累计涨幅
        if len(closes) >= 6:
            indicators['change_5d'] = (closes[-1] - closes[-6]) / closes[-6] * 100

        # K线20日位置
        if len(klines) >= 10:
            recent = klines[-20:] if len(klines) >= 20 else klines
            highs = [k.get('high', 0) for k in recent]
            lows = [k.get('low', 0) for k in recent]
            max_h = max(highs) if highs else 0
            min_l = min(lows) if lows else 0
            price = last_price or (closes[-1] if closes else 0)
            if max_h > min_l and price > 0:
                indicators['kline_pos_20d'] = (price - min_l) / (max_h - min_l)

        # 距近10日最低点反弹幅度 (对齐TrendReversal条件③: rise_from_low≥2%)
        if len(klines) >= 3:
            lookback = klines[-10:] if len(klines) >= 10 else klines
            recent_lows = [k.get('low', 0) for k in lookback if k.get('low', 0) > 0]
            if recent_lows:
                period_low = min(recent_lows)
                price = last_price or (closes[-1] if closes else 0)
                if period_low > 0 and price > 0:
                    indicators['rise_from_low'] = (price - period_low) / period_low * 100

    return indicators


def _get_plate_info(container, stock_code: str) -> str:
    """获取板块信息"""
    plate_mgr = getattr(container, 'plate_manager', None) or \
                getattr(getattr(container, 'data', None), 'plate_manager', None)
    if not plate_mgr:
        return ""
    try:
        if hasattr(plate_mgr, 'get_stock_plates'):
            plates = plate_mgr.get_stock_plates(stock_code)
            if plates:
                names = [
                    p.get('plate_name', p) if isinstance(p, dict) else str(p)
                    for p in plates
                ]
                return f"所属板块: {', '.join(names)}"
    except Exception:
        pass
    return ""


def _get_position_info(container, stock_code: str) -> dict:
    """获取持仓信息（如果是持仓股票）"""
    trade_svc = container.futu_trade_service
    if not trade_svc:
        return {}
    try:
        positions_result = trade_svc.get_positions()
        positions = []
        if isinstance(positions_result, dict) and positions_result.get('success'):
            positions = positions_result.get('positions', [])
        elif isinstance(positions_result, list):
            positions = positions_result

        for pos in positions:
            code = pos.get('stock_code', pos.get('code', ''))
            if code == stock_code:
                return pos
    except Exception as e:
        logger.debug(f"获取 {stock_code} 持仓信息失败: {e}")
    return {}


async def _get_stock_news(container, stock_code: str, stock_name: str) -> dict:
    """获取消息面数据（Gemini + Google Search grounding）"""
    try:
        import os
        from ...services.analysis.stock_news_search import StockNewsSearchService

        config = getattr(container, 'config', None)
        gemini_cfg = getattr(config, 'gemini', None) if config else None

        # 优先 Vertex AI
        project = os.environ.get('VERTEX_AI_PROJECT', '')
        if project:
            service = StockNewsSearchService(
                api_key=os.environ.get('GEMINI_API_KEY', ''),
                model='gemini-2.5-flash',
                vertexai=True,
                project=project,
                location=os.environ.get('VERTEX_AI_LOCATION', 'global'),
            )
        else:
            api_key = getattr(gemini_cfg, 'api_key', '') if gemini_cfg else os.environ.get('GEMINI_API_KEY', '')
            if not api_key:
                return {}
            service = StockNewsSearchService(api_key=api_key, model='gemini-2.5-flash')

        if not service.is_available():
            return {}

        result = await service.search(stock_code, stock_name)
        return result if not result.get('error') else {}
    except Exception as e:
        logger.debug(f"获取 {stock_code} 消息面失败: {e}")
        return {}


def _get_intraday_flow_data(container, stock_code: str) -> dict:
    """获取日内逐笔成交资金流数据

    聚合三个来源：
    1. big_order_tracking — 最近30分钟大单快照
    2. daily_order_accumulator — 当日累计
    3. high_turnover_cache — 资金流信号（吸筹/出货/接盘失败）
    """
    result = {}
    db = container.db_manager
    if not db:
        return result

    # 1) 大单追踪快照（最近30分钟）
    try:
        from datetime import datetime, timedelta
        lookback = (datetime.now() - timedelta(minutes=30)).isoformat()
        rows = db.execute_query("""
            SELECT timestamp, big_buy_count, big_sell_count,
                   big_buy_amount, big_sell_amount,
                   buy_sell_ratio, order_strength
            FROM big_order_tracking
            WHERE stock_code = ? AND timestamp > ?
            ORDER BY timestamp DESC LIMIT 10
        """, (stock_code, lookback))

        if rows:
            snapshots = []
            for r in rows:
                snapshots.append({
                    'time': (r[0] or '')[:19],
                    'buy_count': r[1] or 0,
                    'sell_count': r[2] or 0,
                    'buy_amt': f"{(r[3] or 0)/1e4:.0f}万",
                    'sell_amt': f"{(r[4] or 0)/1e4:.0f}万",
                    'ratio': round(float(r[5] or 1), 2),
                    'strength': round(float(r[6] or 0), 2),
                })
            result['recent_big_orders'] = snapshots

            # 汇总趋势
            strengths = [float(r[6] or 0) for r in rows]
            avg_strength = sum(strengths) / len(strengths) if strengths else 0
            sell_dominant = sum(1 for s in strengths if s < -0.1)
            buy_dominant = sum(1 for s in strengths if s > 0.1)
            result['big_order_summary'] = {
                'avg_strength': round(avg_strength, 2),
                'sell_dominant_periods': sell_dominant,
                'buy_dominant_periods': buy_dominant,
                'total_periods': len(rows),
                'trend': '主力卖出' if avg_strength < -0.15 else '主力买入' if avg_strength > 0.15 else '均衡',
            }
    except Exception as e:
        logger.debug(f"获取 {stock_code} 大单追踪失败: {e}")

    # 2) 当日累计
    try:
        from datetime import datetime as _dt
        trade_date = _dt.now().strftime("%Y-%m-%d")
        rows2 = db.execute_query("""
            SELECT super_large_buy_amt, super_large_sell_amt,
                   large_buy_amt, large_sell_amt
            FROM daily_order_accumulator
            WHERE stock_code = ? AND trade_date = ?
        """, (stock_code, trade_date))

        if rows2:
            r = rows2[0]
            big_buy = float(r[0] or 0) + float(r[2] or 0)
            big_sell = float(r[1] or 0) + float(r[3] or 0)
            net = big_buy - big_sell
            result['daily_accumulator'] = {
                'big_buy': f"{big_buy/1e4:.0f}万",
                'big_sell': f"{big_sell/1e4:.0f}万",
                'net': f"{'+' if net > 0 else ''}{net/1e4:.0f}万",
                'ratio': round(big_buy / big_sell, 2) if big_sell > 0 else 999,
                'is_net_inflow': net > 0,
            }
    except Exception as e:
        logger.debug(f"获取 {stock_code} 日内累计失败: {e}")

    # 3) 资金流信号
    try:
        from ...core import get_state_manager
        state = get_state_manager()
        ht_cache = state.high_turnover_cache.get_all()
        cached = ht_cache.get(stock_code)
        if cached and cached.get('flow_signal'):
            result['flow_signal'] = {
                'type': cached['flow_signal'],
                'label': cached.get('flow_signal_label', ''),
                'detail': cached.get('flow_signal_detail', ''),
            }
    except Exception:
        pass

    return result


async def _get_capital_flow_summary(container, stock_code: str) -> dict:
    """获取逐笔资金流时间线的摘要数据

    复用 enhanced_heat 路由中的 _compute_flow_summary 逻辑，
    返回动能标签、买卖比、前后半段净流入对比等关键指标。
    """
    try:
        from datetime import date as _date
        db = getattr(container, 'db_manager', None)
        if not db:
            return {}

        today_str = _date.today().isoformat()

        # 查询 ticker_data 逐分钟聚合
        rows = db.execute_query("""
            SELECT
                substr(datetime(timestamp/1000, 'unixepoch', '+8 hours'), 12, 5) as minute,
                direction,
                SUM(turnover) as total_turnover,
                SUM(volume) as total_volume,
                AVG(price) as avg_price
            FROM ticker_data
            WHERE stock_code = ? AND trade_date = ?
            GROUP BY minute, direction
            ORDER BY minute
        """, (stock_code, today_str))

        if not rows or len(rows) < 5:
            return {}

        # 按分钟聚合
        minute_data = {}
        for row in rows:
            minute, direction, turnover, volume, avg_price = row
            if not ('09:15' <= minute <= '16:10'):
                continue
            if minute not in minute_data:
                minute_data[minute] = {'buy': 0.0, 'sell': 0.0, 'vol': 0, 'price_sum': 0.0, 'price_n': 0}
            entry = minute_data[minute]
            tv = float(turnover or 0)
            if direction == 'BUY':
                entry['buy'] += tv
            elif direction == 'SELL':
                entry['sell'] += tv
            entry['vol'] += int(volume or 0)
            if avg_price and float(avg_price) > 0:
                entry['price_sum'] += float(avg_price)
                entry['price_n'] += 1

        if len(minute_data) < 3:
            return {}

        # 构建时间线
        timeline = []
        cum_buy = 0.0
        cum_sell = 0.0
        for minute in sorted(minute_data.keys()):
            e = minute_data[minute]
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

        # 复用 enhanced_heat 的摘要计算
        from ..data.enhanced_heat import _compute_flow_summary
        summary = _compute_flow_summary(timeline)

        # 附加时间线的首尾价格用于判断走势
        first_price = next((p.get('price', 0) for p in timeline if p.get('price', 0) > 0), 0)
        last_price = next((p.get('price', 0) for p in reversed(timeline) if p.get('price', 0) > 0), 0)

        return {
            'summary': summary,
            'data_points': len(timeline),
            'first_price': first_price,
            'last_price': last_price,
            # 附加最近5个数据点，让AI看到最新趋势
            'recent_points': timeline[-5:] if len(timeline) >= 5 else timeline,
        }
    except Exception as e:
        logger.debug(f"获取 {stock_code} 资金流时间线摘要失败: {e}")
        return {}


async def _get_intraday_levels_data(container, stock_code: str) -> dict:
    """获取日内支撑/阻力位 + 经纪商席位分析

    直接调用 IntradayLevelsService + BrokerConsistencyFilter，
    返回支撑位、阻力位、VWAP、POC、经纪商买卖席位。
    """
    try:
        from ...services.analysis.intraday_levels_service import IntradayLevelsService
        from ..data.ticker.helpers import get_ticker_service, get_order_book_service

        ticker_svc = get_ticker_service(container)
        ob_svc = get_order_book_service(container)
        service = IntradayLevelsService(
            ticker_service=ticker_svc,
            order_book_service=ob_svc,
        )

        result = await service.get_levels(stock_code)
        data = result.to_dict()

        # 附加经纪商席位分析
        try:
            futu_client = getattr(container, 'futu_client', None)
            if futu_client and result.current_price > 0:
                from ...services.analysis.flow.broker_consistency_filter import BrokerConsistencyFilter
                change_pct = 0.0
                try:
                    quote_cache = getattr(container, 'quote_cache', None)
                    if quote_cache:
                        quotes_map = quote_cache.get_quotes_for_codes([stock_code])
                        cached = quotes_map.get(stock_code)
                        if cached:
                            change_pct = abs(float(cached.get('change_rate', 0)))
                except Exception:
                    pass
                bf = BrokerConsistencyFilter(futu_client)
                broker_result = bf.check_distribution_trap(stock_code, change_pct=change_pct)
                data['broker_analysis'] = {
                    'is_trap': broker_result.is_trap,
                    'trap_confidence': broker_result.trap_confidence,
                    'reason': broker_result.reason,
                    'top_buyers': broker_result.top_buyers[:5],
                    'top_sellers': broker_result.top_sellers[:5],
                    'buyer_details': broker_result.buyer_details,
                    'seller_details': broker_result.seller_details,
                    'institutional_sell_count': broker_result.institutional_sell_count,
                    'retail_buy_count': broker_result.retail_buy_count,
                }
        except Exception as e:
            logger.debug(f"经纪商分析附加失败: {e}")

        return data
    except Exception as e:
        logger.debug(f"获取 {stock_code} 日内支撑/阻力位失败: {e}")
        return {}
