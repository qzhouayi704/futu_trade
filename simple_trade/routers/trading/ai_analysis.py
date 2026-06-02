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

        # 9. 获取盘中狙击手排行数据（Sniper TOP排行 + 该股信号）
        sniper_data = _get_sniper_data(container, stock_code)

        logger.info(
            f"[AI分析API] {stock_code} 数据聚合完成 | "
            f"行情: {'\u2713' if quote else '\u2717'} | "
            f"K线: {len(klines) if klines else 0}条 | "
            f"板块: {'\u2713' if plate_info else '\u2717'} | "
            f"持仓: {'\u2713' if position_info else '\u2717'} | "
            f"消息面: {len(news_data.get('news', [])) if news_data else 0}条 | "
            f"资金流: {'\u2713' if flow_data else '\u2717'} | "
            f"时间线摘要: {'\u2713' if capital_flow_summary else '\u2717'} | "
            f"支撑阻力: {'\u2713' if intraday_levels_data else '\u2717'} | "
            f"狙击手: {'\u2713' if sniper_data else '\u2717'}"
        )

        # 10. 执行 AI 分析
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
            sniper_data=sniper_data,
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
    """从缓存或实时查询获取股票行情（委托共享实现）"""
    from ..data.helpers.quote_helpers import get_stock_quote
    return get_stock_quote(container, stock_code)


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


# 模块级持仓缓存（避免每次单股分析都调用 Futu API）
_positions_cache = None
_positions_cache_ts = 0


def _get_position_info(container, stock_code: str) -> dict:
    """获取持仓信息（如果是持仓股票），使用 10 秒缓存避免重复 API 调用"""
    import time
    global _positions_cache, _positions_cache_ts

    trade_svc = container.futu_trade_service
    if not trade_svc:
        return {}
    try:
        now = time.time()
        if _positions_cache is None or (now - _positions_cache_ts) > 10:
            positions_result = trade_svc.get_positions()
            positions = []
            if isinstance(positions_result, dict) and positions_result.get('success'):
                positions = positions_result.get('positions', [])
            elif isinstance(positions_result, list):
                positions = positions_result
            _positions_cache = positions
            _positions_cache_ts = now
        else:
            positions = _positions_cache

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


def _get_sniper_data(container, stock_code: str) -> dict:
    """获取盘中狙击手排行和信号数据

    返回：
    - ranking: 当前 TOP 3 机会/风险排行
    - stock_position: 该股在排行中的位置（机会/风险/无）
    - signals: 该股今日所有 sniper 信号
    """
    sniper = getattr(container, 'intraday_sniper', None)
    if not sniper:
        return {}

    result = {}
    try:
        # 排行榜
        ranking = sniper.get_top_ranking()
        if ranking and ranking.get('updated_at'):
            result['ranking'] = ranking

            # 该股在排行中的位置
            for item in ranking.get('opportunity', []):
                if item['stock_code'] == stock_code:
                    result['stock_position'] = {
                        'type': 'opportunity',
                        'rank': ranking['opportunity'].index(item) + 1,
                        'score': item['score'],
                        'detail': item.get('detail', {}),
                    }
                    break
            for item in ranking.get('risk', []):
                if item['stock_code'] == stock_code:
                    result['stock_position'] = {
                        'type': 'risk',
                        'rank': ranking['risk'].index(item) + 1,
                        'score': item['score'],
                        'detail': item.get('detail', {}),
                    }
                    break

        # 该股今日信号
        all_signals = sniper.get_today_signals()
        stock_signals = [s for s in all_signals if s.get('stock_code') == stock_code]
        if stock_signals:
            result['signals'] = stock_signals[-10:]  # 最近10条
    except Exception as e:
        logger.debug(f"获取 {stock_code} 狙击手数据失败: {e}")

    return result


# ==================== AI 智选 ====================

from pydantic import BaseModel
from typing import List, Optional as Opt


class SmartPickStockItem(BaseModel):
    """前端传入的单只股票数据"""
    code: str
    name: str
    change_rate: float = 0
    turnover_rate: float = 0
    turnover: float = 0
    volume_ratio: float = 0
    amplitude: float = 0
    capital_signal: str = ""
    capital_score: float = 0
    main_net_inflow: float = 0
    big_order_buy_ratio: float = 0
    ticker_buy_sell_ratio: float = 0
    consensus_score: float = 0
    consensus_verdict: str = ""
    is_position: bool = False


class SmartPickRequest(BaseModel):
    """AI 智选请求"""
    stocks: List[SmartPickStockItem]


SMART_PICK_SYSTEM_PROMPT = """# 角色
你是一位资深的港股/美股短线量化交易师。你的任务是从一组活跃股票中，筛选出最值得短线买入的标的。

# 数据说明
你将收到每只股票的以下信息：
- **基础行情**：涨跌幅、换手率、成交额、量比、振幅
- **资金数据**：资金评分、主力净流入、大单买入占比、逐笔力量比
- **K线趋势**：5日/10日涨幅、20日位置（0=最低点, 100=最高点）
- **评分系统**：多策略评分（趋势/突破/动量）、是否通过
- **大单追踪**：近30分钟主力方向、买卖强度
- **日内资金流**：当日大单净流入/流出
- **狙击手信号**：机会/风险排行、今日信号
- **持仓信息**：成本价、盈亏比例（如为持仓股）
- **所属板块**：行业板块归属

# 分析方法
1. **资金优先**：资金流入（capital_score高、主力净流入正、大单买入占比高、大单追踪显示"主力买入"）的股票优先
2. **趋势确认**：涨跌幅合理（不追高位暴涨股）、换手率适中（2-15%最佳）、量比放大、20日位置适中
3. **交叉验证**：资金流入 + 价格上涨 = 健康；资金流入 + 价格下跌 = 可能洗盘（关注）
4. **评分系统**：评分通过且分数高的优先，多策略均通过更好
5. **狙击手确认**：在机会排行中的股票加分，在风险排行中的减分
6. **风险排除**：一票否决触发的不选、capital_score极低的不选、暴涨超5%慎选、大单追踪显示"主力卖出"慎选

# 选股标准（按优先级）
- 🥇 资金评分 ≥ 60 + 大单主力买入 + 评分通过 + 涨幅温和(0~3%) → 最佳
- 🥈 大单买卖比 ≥ 1.5 + 量比放大 + 日内净流入 + 20日位置 < 70% → 良好
- 🥉 资金转正 + 低位反弹(20日位置<30%) + 板块强势 → 可关注

# 输出要求
1. 最多选出 **5 只** 最值得买入的股票
2. 如果没有任何股票值得买入，返回空列表并说明原因
3. reasoning 中必须引用具体的服务端指标（如"大单追踪显示主力买入"、"20日位置仅23%处于低位"）
4. 严格输出 JSON 格式，所有文本使用简体中文
5. picks 数组中按推荐优先级排序（最推荐的在前）

```json
{
  "picks": [
    {
      "code": "股票代码",
      "name": "股票名称",
      "action": "STRONG_BUY" | "BUY",
      "confidence": 0-100,
      "reasoning": "简短买入理由（引用关键指标，不超过150字）",
      "key_signal": "最关键的一个信号",
      "risk": "主要风险点",
      "target_price": null,
      "stop_loss_price": null
    }
  ],
  "market_summary": "一句话总结当前市场整体状态",
  "skip_reason": "如果没有推荐，说明原因"
}
```"""


async def _enrich_stocks_batch(
    stocks: List[SmartPickStockItem], container
) -> dict:
    """批量为股票列表注入服务端深度指标

    Returns: dict mapping stock_code -> enriched data dict
    """
    enriched = {}

    # 1. 一次性获取所有持仓
    all_positions = {}
    try:
        trade_svc = container.futu_trade_service
        if trade_svc:
            positions_result = trade_svc.get_positions()
            positions = []
            if isinstance(positions_result, dict) and positions_result.get('success'):
                positions = positions_result.get('positions', [])
            elif isinstance(positions_result, list):
                positions = positions_result
            for pos in positions:
                code = pos.get('stock_code', pos.get('code', ''))
                if code:
                    all_positions[code] = pos
    except Exception as e:
        logger.debug(f"[AI智选] 批量获取持仓失败: {e}")

    # 2. 获取狙击手排行（一次性）
    sniper_ranking = {}
    sniper = getattr(container, 'intraday_sniper', None)
    if sniper:
        try:
            ranking = sniper.get_top_ranking()
            if ranking and ranking.get('updated_at'):
                for item in ranking.get('opportunity', []):
                    sniper_ranking[item['stock_code']] = {
                        'type': '机会',
                        'rank': ranking['opportunity'].index(item) + 1,
                        'score': item['score'],
                    }
                for item in ranking.get('risk', []):
                    sniper_ranking[item['stock_code']] = {
                        'type': '风险',
                        'rank': ranking['risk'].index(item) + 1,
                        'score': item['score'],
                    }
        except Exception as e:
            logger.debug(f"[AI智选] 获取狙击手排行失败: {e}")

    # 3. 获取狙击手今日所有信号
    all_signals = []
    if sniper:
        try:
            all_signals = sniper.get_today_signals()
        except Exception:
            pass

    db = container.db_manager

    # 4. 逐只获取 K线/评分/大单/资金
    for s in stocks:
        code = s.code
        data = {}
        klines = None  # 复用K线数据，避免重复DB查询

        # K线趋势摘要
        try:
            klines = _get_kline_data(container, code)
            if klines and len(klines) >= 5:
                closes = [k.get('close', 0) for k in klines if k.get('close', 0) > 0]
                if len(closes) >= 5:
                    data['kline'] = {}
                    if len(closes) >= 6:
                        data['kline']['5d_chg'] = round(
                            (closes[-1] - closes[-6]) / closes[-6] * 100, 2)
                    if len(closes) >= 11:
                        data['kline']['10d_chg'] = round(
                            (closes[-1] - closes[-11]) / closes[-11] * 100, 2)
                    # 20日位置
                    recent = klines[-20:] if len(klines) >= 20 else klines
                    highs = [k.get('high', 0) for k in recent]
                    lows = [k.get('low', 0) for k in recent]
                    max_h = max(highs) if highs else 0
                    min_l = min(lows) if lows else 0
                    if max_h > min_l:
                        data['kline']['pos_20d'] = round(
                            (closes[-1] - min_l) / (max_h - min_l) * 100, 1)
        except Exception:
            pass

        # 多策略评分（复用上面已获取的 klines）
        try:
            quote = _get_stock_quote(container, code)
            if quote:
                score = _get_score_result(container, code, quote, klines or [])
                if score:
                    data['score'] = {
                        'total': score.get('total_score', 0),
                        'passed': score.get('passed', False),
                        'mode': score.get('best_mode', ''),
                    }
                    strategies = score.get('strategies', [])
                    if strategies:
                        data['score']['detail'] = ', '.join(
                            f"{st['mode']}:{st['total_score']}{'✓' if st['passed'] else '✗'}"
                            for st in strategies
                        )
        except Exception:
            pass

        # 大单追踪摘要（近30分钟）
        if db:
            try:
                from datetime import datetime, timedelta
                lookback = (datetime.now() - timedelta(minutes=30)).isoformat()
                rows = db.execute_query("""
                    SELECT AVG(order_strength),
                           SUM(CASE WHEN order_strength > 0.1 THEN 1 ELSE 0 END),
                           SUM(CASE WHEN order_strength < -0.1 THEN 1 ELSE 0 END),
                           COUNT(*)
                    FROM big_order_tracking
                    WHERE stock_code = ? AND timestamp > ?
                """, (code, lookback))
                if rows and rows[0][3]:
                    r = rows[0]
                    avg_s = float(r[0] or 0)
                    data['big_order'] = {
                        'strength': round(avg_s, 2),
                        'buy_n': int(r[1] or 0),
                        'sell_n': int(r[2] or 0),
                        'trend': '主力卖出' if avg_s < -0.15 else '主力买入' if avg_s > 0.15 else '均衡',
                    }
            except Exception:
                pass

            # 日内大单累计
            try:
                from datetime import datetime as _dt
                trade_date = _dt.now().strftime("%Y-%m-%d")
                rows2 = db.execute_query("""
                    SELECT super_large_buy_amt, super_large_sell_amt,
                           large_buy_amt, large_sell_amt
                    FROM daily_order_accumulator
                    WHERE stock_code = ? AND trade_date = ?
                """, (code, trade_date))
                if rows2:
                    r = rows2[0]
                    big_buy = float(r[0] or 0) + float(r[2] or 0)
                    big_sell = float(r[1] or 0) + float(r[3] or 0)
                    net = big_buy - big_sell
                    data['daily_flow'] = {
                        'buy_wan': round(big_buy / 1e4),
                        'sell_wan': round(big_sell / 1e4),
                        'net_wan': round(net / 1e4),
                        'inflow': net > 0,
                    }
            except Exception:
                pass

        # 持仓详情
        pos = all_positions.get(code)
        if pos:
            data['position'] = {
                'qty': pos.get('qty', pos.get('position_qty', 0)),
                'cost': pos.get('cost_price', 0),
                'pnl_pct': round(float(pos.get('pnl_pct', pos.get('profit_ratio', 0)) or 0), 2),
            }

        # 板块
        try:
            plate = _get_plate_info(container, code)
            if plate:
                data['plate'] = plate
        except Exception:
            pass

        # 狙击手排行
        if code in sniper_ranking:
            data['sniper'] = sniper_ranking[code]

        # 该股今日信号数
        stock_sigs = [sig for sig in all_signals if sig.get('stock_code') == code]
        if stock_sigs:
            data['sniper_sig_count'] = len(stock_sigs)
            latest = stock_sigs[-1]
            data['sniper_latest'] = (
                latest.get('signal_type', '') + ':' +
                str(latest.get('detail', ''))[:50]
            )

        enriched[code] = data

    logger.info(
        f"[AI智选] 数据聚合完成: {len(enriched)} 只股票, "
        f"持仓 {len(all_positions)} 只, "
        f"狙击手排行 {len(sniper_ranking)} 只"
    )
    return enriched


@router.post("/smart-pick", response_model=APIResponse)
async def smart_pick(
    req: SmartPickRequest,
    container=Depends(get_container),
):
    """AI 智选：从页面股票中筛选最值得买入的标的"""
    if not req.stocks:
        return APIResponse(success=False, message="未提供股票数据")

    # 获取 Claude 配置
    claude_cfg = container.config.claude
    if not claude_cfg or not claude_cfg.get('enabled') or not claude_cfg.get('api_key'):
        return APIResponse(success=False, message="Claude AI 未配置，请设置 CLAUDE_API_KEY 环境变量")

    try:
        # 聚合服务端深度指标
        enriched = await _enrich_stocks_batch(req.stocks, container)

        # 构建 prompt（含深度指标）
        prompt = _build_smart_pick_prompt(req.stocks, enriched)
        logger.info(f"[AI智选] 收到 {len(req.stocks)} 只股票，Prompt 长度: {len(prompt)}")

        # 调用 Claude
        response = await _call_claude_for_smart_pick(claude_cfg, prompt)
        if not response:
            return APIResponse(success=False, message="Claude API 调用失败")

        # 解析结果
        result = _parse_smart_pick_response(response)
        if result is None:
            return APIResponse(success=False, message="AI 响应解析失败")

        logger.info(f"[AI智选] 完成，推荐 {len(result.get('picks', []))} 只股票")
        return APIResponse(success=True, data=result, message=f"AI 推荐 {len(result.get('picks', []))} 只标的")

    except Exception as e:
        logger.error(f"[AI智选] 异常: {e}", exc_info=True)
        return APIResponse(success=False, message=f"AI 智选异常: {str(e)}")


def _build_smart_pick_prompt(
    stocks: List[SmartPickStockItem], enriched: dict
) -> str:
    """构建批量智选的 prompt（含服务端深度指标）"""
    from datetime import datetime
    prompt = f"# 待分析股票池（{len(stocks)} 只）\n"
    prompt += f"分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    # 基础行情总览表
    prompt += "## 基础行情\n"
    prompt += "| # | 代码 | 名称 | 涨跌% | 换手% | 成交额 | 量比 | 资金评分 | 主力净流入 | 大单买比 | 力量比 | 综合评分 | 判定 |\n"
    prompt += "|---|------|------|-------|-------|--------|------|---------|-----------|---------|-------|---------|------|\n"

    for i, s in enumerate(stocks, 1):
        turnover_str = f"{s.turnover/1e8:.2f}亿" if s.turnover >= 1e8 else f"{s.turnover/1e4:.0f}万"
        inflow_str = f"{s.main_net_inflow/1e4:+.0f}万" if s.main_net_inflow else "0"
        prompt += (
            f"| {i} | {s.code} | {s.name} | {s.change_rate:+.2f} | {s.turnover_rate:.1f} | "
            f"{turnover_str} | {s.volume_ratio:.1f} | {s.capital_score:.0f} | {inflow_str} | "
            f"{s.big_order_buy_ratio:.2f} | {s.ticker_buy_sell_ratio:.2f} | "
            f"{s.consensus_score:.0f} | {s.consensus_verdict or '-'} |\n"
        )

    # 每只股票的深度指标
    prompt += "\n## 服务端深度指标\n"
    for s in stocks:
        d = enriched.get(s.code, {})
        if not d:
            continue

        parts = [f"### {s.code} {s.name}"]

        # K线趋势
        kl = d.get('kline')
        if kl:
            items = []
            if '5d_chg' in kl:
                items.append(f"5日涨幅:{kl['5d_chg']:+.1f}%")
            if '10d_chg' in kl:
                items.append(f"10日涨幅:{kl['10d_chg']:+.1f}%")
            if 'pos_20d' in kl:
                items.append(f"20日位置:{kl['pos_20d']:.0f}%")
            if items:
                parts.append(f"- K线趋势: {', '.join(items)}")

        # 评分
        sc = d.get('score')
        if sc:
            status = '✓通过' if sc.get('passed') else '✗未通过'
            line = f"- 评分: {sc.get('total', 0)}分({status}, 最佳策略:{sc.get('mode', '?')})"
            if sc.get('detail'):
                line += f" [{sc['detail']}]"
            parts.append(line)

        # 大单追踪
        bo = d.get('big_order')
        if bo:
            parts.append(
                f"- 大单追踪(30min): {bo['trend']}(强度{bo['strength']:+.2f}, "
                f"买入{bo['buy_n']}期/卖出{bo['sell_n']}期)"
            )

        # 日内资金流
        df = d.get('daily_flow')
        if df:
            parts.append(
                f"- 日内大单: 买{df['buy_wan']}万/卖{df['sell_wan']}万, "
                f"净{'流入' if df['inflow'] else '流出'}{abs(df['net_wan'])}万"
            )

        # 持仓
        pos = d.get('position')
        if pos:
            parts.append(
                f"- 持仓: {pos['qty']}股, 成本{pos['cost']}, "
                f"盈亏{pos['pnl_pct']:+.1f}%"
            )

        # 狙击手
        sn = d.get('sniper')
        if sn:
            parts.append(f"- 狙击手: {sn['type']}排行第{sn['rank']}(分数{sn['score']:.1f})")
        if d.get('sniper_sig_count'):
            parts.append(f"- 今日信号: {d['sniper_sig_count']}条, 最新: {d.get('sniper_latest', '')}")

        # 板块
        pl = d.get('plate')
        if pl:
            parts.append(f"- {pl}")

        if len(parts) > 1:  # 有深度数据才输出
            prompt += '\n'.join(parts) + '\n\n'

    prompt += "请综合基础行情和服务端深度指标，筛选出最值得短线买入的股票。\n"
    return prompt


async def _call_claude_for_smart_pick(claude_cfg, prompt: str) -> Opt[str]:
    """调用 Claude API 进行智选分析"""
    import json
    import urllib.request
    import urllib.error

    base_url = claude_cfg.get('base_url', 'https://vtok.ai').rstrip('/')
    api_key = claude_cfg.get('api_key', '')
    model = claude_cfg.get('model', 'claude-sonnet-4-20250514')
    timeout = claude_cfg.get('timeout', 90)
    max_retries = claude_cfg.get('max_retries', 3)
    api_format = claude_cfg.get('api_format', 'openai')

    for attempt in range(max_retries):
        try:
            if api_format == 'anthropic':
                url = f"{base_url}/v1/messages"
                payload = {
                    "model": model,
                    "max_tokens": 4096,
                    "system": SMART_PICK_SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": prompt}],
                }
                headers = {
                    "Content-Type": "application/json",
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                }
            else:
                url = f"{base_url}/v1/chat/completions"
                payload = {
                    "model": model,
                    "max_tokens": 4096,
                    "messages": [
                        {"role": "system", "content": SMART_PICK_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                }
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                }

            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers=headers, method='POST')

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(req, timeout=timeout)
            )
            result = json.loads(response.read().decode('utf-8'))

            if api_format == 'anthropic':
                content = result.get('content', [])
                if content and isinstance(content, list):
                    return content[0].get('text', '').strip()
            else:
                choices = result.get('choices', [])
                if choices:
                    return choices[0].get('message', {}).get('content', '').strip()

            return None

        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            status = getattr(e, 'code', 0)
            if status in (429, 503, 529) and attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                logger.warning(f"[AI智选] Claude API 暂不可用 (attempt {attempt+1})，{wait}s 后重试")
                await asyncio.sleep(wait)
                continue
            logger.error(f"[AI智选] Claude API 调用失败: {e}")
            return None
        except Exception as e:
            logger.error(f"[AI智选] Claude API 异常: {e}")
            return None


def _parse_smart_pick_response(response: str) -> Opt[dict]:
    """解析 AI 智选响应"""
    import json
    try:
        json_str = response
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0].strip()
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0].strip()

        data = json.loads(json_str)

        # 标准化
        picks = data.get('picks', [])
        for p in picks:
            if p.get('action') not in ('STRONG_BUY', 'BUY'):
                p['action'] = 'BUY'
            p['confidence'] = min(100, max(0, int(p.get('confidence', 50))))

        return {
            'picks': picks[:5],
            'market_summary': data.get('market_summary', ''),
            'skip_reason': data.get('skip_reason', ''),
        }
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"[AI智选] 响应解析失败: {e}, response={response[:300]}")
        return None

