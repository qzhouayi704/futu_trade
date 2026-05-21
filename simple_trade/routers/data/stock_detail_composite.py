#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票详情页组合数据路由

提供三个核心API：
1. 日内分时+成交强度叠加数据
2. 多维信号共振数据
3. 5分钟K线+Delta联动数据
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query

from ...core.exceptions import BusinessError
from ...dependencies import get_container
from ...schemas.common import APIResponse

router = APIRouter(prefix="/api/stock-detail", tags=["股票详情组合数据"])
logger = logging.getLogger(__name__)


# ==================== 1. 日内分时+成交强度 ====================

@router.get("/intraday-composite/{stock_code}", response_model=APIResponse)
async def get_intraday_composite(
    stock_code: str,
    container=Depends(get_container),
):
    """日内分时走势 + 逐笔成交强度 + 大单标记 组合数据"""
    try:
        db = container.db_manager
        today = datetime.now().strftime('%Y-%m-%d')

        # 并行获取三类数据
        rt_task = asyncio.to_thread(
            _get_rt_data, db, stock_code, today
        )
        ticker_task = asyncio.to_thread(
            _get_ticker_strength, db, stock_code, today
        )
        bigorder_task = asyncio.to_thread(
            _get_big_orders, db, stock_code, today
        )

        rt_data, ticker_strength, big_orders = await asyncio.gather(
            rt_task, ticker_task, bigorder_task
        )

        return APIResponse(
            success=True,
            data={
                "price_line": rt_data,
                "ticker_strength": ticker_strength,
                "big_orders": big_orders,
                "stock_code": stock_code,
                "trade_date": today,
            },
            message=f"获取 {stock_code} 日内组合数据成功",
        )
    except Exception as e:
        logger.error(f"获取日内组合数据失败 {stock_code}: {e}")
        raise BusinessError(f"获取日内组合数据失败: {str(e)}")


# ==================== 2. 多维信号共振 ====================

@router.get("/signal-resonance/{stock_code}", response_model=APIResponse)
async def get_signal_resonance(
    stock_code: str,
    container=Depends(get_container),
):
    """多维信号共振数据：趋势+成交+资金+盘口+量能"""
    try:
        db = container.db_manager

        # 1. 策略评分
        strategy_dim = await asyncio.to_thread(
            _get_strategy_dimension, container, stock_code
        )

        # 2. 成交力量（从ticker分析）
        ticker_dim = await asyncio.to_thread(
            _get_ticker_dimension, container, stock_code
        )

        # 3. 资金流向
        capital_dim = await asyncio.to_thread(
            _get_capital_dimension, db, stock_code
        )

        # 4. 盘口数据
        orderbook_dim = await asyncio.to_thread(
            _get_orderbook_dimension, db, stock_code
        )

        # 5. 量能可信度
        volume_dim = await asyncio.to_thread(
            _get_volume_dimension, db, stock_code
        )

        dimensions = [strategy_dim, ticker_dim, capital_dim, orderbook_dim, volume_dim]
        valid_dims = [d for d in dimensions if d["score"] is not None]

        # 综合判定
        if valid_dims:
            avg_score = sum(d["score"] for d in valid_dims) / len(valid_dims)
            bullish = sum(1 for d in valid_dims if d["score"] >= 60)
            bearish = sum(1 for d in valid_dims if d["score"] < 40)
            neutral = len(valid_dims) - bullish - bearish
        else:
            avg_score = 50
            bullish = bearish = neutral = 0

        # 信号矛盾检测
        conflicts = _detect_conflicts(dimensions)

        if bullish > bearish:
            verdict = "看多"
        elif bearish > bullish:
            verdict = "看空"
        else:
            verdict = "中性"

        return APIResponse(
            success=True,
            data={
                "dimensions": dimensions,
                "summary": {
                    "avg_score": round(avg_score, 1),
                    "bullish_count": bullish,
                    "bearish_count": bearish,
                    "neutral_count": neutral,
                    "verdict": verdict,
                    "conflicts": conflicts,
                },
                "stock_code": stock_code,
            },
            message=f"获取 {stock_code} 信号共振数据成功",
        )
    except Exception as e:
        logger.error(f"获取信号共振数据失败 {stock_code}: {e}")
        raise BusinessError(f"获取信号共振数据失败: {str(e)}")


# ==================== 3. 5分钟K线+Delta ====================

@router.get("/kline-delta/{stock_code}", response_model=APIResponse)
async def get_kline_delta(
    stock_code: str,
    limit: int = Query(default=48, ge=12, le=120),
    container=Depends(get_container),
):
    """5分钟K线 + Delta买卖净力量 联动数据"""
    try:
        db = container.db_manager

        kline_task = asyncio.to_thread(
            _get_5min_klines, db, stock_code, limit
        )
        delta_task = asyncio.to_thread(
            _get_delta_history, db, stock_code, limit
        )

        klines, deltas = await asyncio.gather(kline_task, delta_task)

        # 合并：按时间对齐
        merged = _merge_kline_delta(klines, deltas)

        return APIResponse(
            success=True,
            data={
                "candles": merged,
                "stock_code": stock_code,
                "count": len(merged),
            },
            message=f"获取 {stock_code} K线Delta数据成功",
        )
    except Exception as e:
        logger.error(f"获取K线Delta数据失败 {stock_code}: {e}")
        raise BusinessError(f"获取K线Delta数据失败: {str(e)}")


# ==================== 数据提取函数 ====================

def _get_rt_data(db, stock_code: str, trade_date: str) -> list:
    """获取分时数据，优先 rt_data 表，无数据时从 ticker_data 合成"""
    rows = db.execute_query(
        """SELECT time, cur_price, avg_price, volume, turnover
           FROM rt_data
           WHERE stock_code = ? AND trade_date = ?
           ORDER BY time ASC""",
        (stock_code, trade_date)
    )
    if rows:
        return [
            {"time": r[0], "price": r[1], "avg_price": r[2],
             "volume": r[3], "turnover": r[4]}
            for r in rows
        ]

    # 回退：从 ticker_data（Unix毫秒时间戳）按1分钟聚合合成价格线
    rows = db.execute_query(
        """SELECT
             CAST(timestamp / 60000 AS INTEGER) * 60000 as minute_ts,
             AVG(price) as avg_price,
             MAX(price) as high,
             MIN(price) as low,
             SUM(volume) as volume,
             SUM(turnover) as turnover
           FROM ticker_data
           WHERE stock_code = ? AND trade_date = ?
           GROUP BY minute_ts
           ORDER BY minute_ts ASC""",
        (stock_code, trade_date)
    )
    result = []
    cum_vol = 0
    for r in rows:
        ts_ms = r[0]
        cum_vol += (r[4] or 0)
        # 将Unix毫秒转为 HH:MM 格式
        from datetime import datetime as dt, timezone, timedelta
        t = dt.fromtimestamp(ts_ms / 1000, tz=timezone(timedelta(hours=8)))
        time_str = t.strftime('%H:%M')
        result.append({
            "time": time_str,
            "price": round(r[1], 3) if r[1] else 0,
            "avg_price": 0,
            "volume": cum_vol,
            "turnover": r[5] or 0,
        })
    return result


def _get_ticker_strength(db, stock_code: str, trade_date: str) -> list:
    """从逐笔数据按1分钟聚合买卖强度（timestamp为Unix毫秒）"""
    rows = db.execute_query(
        """SELECT
             CAST(timestamp / 60000 AS INTEGER) * 60000 as minute_ts,
             SUM(CASE WHEN direction='BUY' THEN volume ELSE 0 END) as buy_vol,
             SUM(CASE WHEN direction='SELL' THEN volume ELSE 0 END) as sell_vol,
             SUM(CASE WHEN direction='BUY' THEN turnover ELSE 0 END) as buy_amt,
             SUM(CASE WHEN direction='SELL' THEN turnover ELSE 0 END) as sell_amt,
             COUNT(*) as tick_count
           FROM ticker_data
           WHERE stock_code = ? AND trade_date = ?
           GROUP BY minute_ts
           ORDER BY minute_ts ASC""",
        (stock_code, trade_date)
    )
    result = []
    for r in rows:
        ts_ms = r[0]
        from datetime import datetime as dt, timezone, timedelta
        t = dt.fromtimestamp(ts_ms / 1000, tz=timezone(timedelta(hours=8)))
        time_str = t.strftime('%H:%M')
        buy_vol = r[1] or 0
        sell_vol = r[2] or 0
        delta = buy_vol - sell_vol
        result.append({
            "time": time_str,
            "buy_volume": buy_vol,
            "sell_volume": sell_vol,
            "delta": delta,
            "ratio": round(buy_vol / sell_vol, 2) if sell_vol > 0 else 0,
            "tick_count": r[5],
        })
    return result


def _get_big_orders(db, stock_code: str, trade_date: str) -> list:
    """获取大单记录"""
    rows = db.execute_query(
        """SELECT timestamp, price, volume, turnover, direction
           FROM big_order_tracking
           WHERE stock_code = ? AND DATE(timestamp) = ?
           ORDER BY timestamp ASC""",
        (stock_code, trade_date)
    )
    return [
        {"time": r[0], "price": r[1], "volume": r[2],
         "turnover": r[3], "direction": r[4]}
        for r in rows
    ]


def _get_strategy_dimension(container, stock_code: str) -> dict:
    """策略评分维度"""
    dim = {"name": "趋势评分", "icon": "📈", "score": None, "label": "-"}
    try:
        from ...services.strategy.stock_scorer import StockScorer
        scorer = StockScorer()
        cached = scorer.get_score(stock_code)
        if cached:
            dim["score"] = cached.total_score
            dim["label"] = "看多" if cached.total_score >= 60 else ("偏空" if cached.total_score < 40 else "中性")
            return dim

        # 尝试从snapshot获取
        snapshot_store = getattr(container, 'snapshot_store', None)
        if snapshot_store:
            snap = snapshot_store.get(stock_code)
            if snap:
                result = scorer.score_snapshot(snap)
                dim["score"] = result.total_score
                dim["label"] = "看多" if result.total_score >= 60 else ("偏空" if result.total_score < 40 else "中性")
    except Exception as e:
        logger.debug(f"策略评分获取失败 {stock_code}: {e}")
    return dim


def _get_ticker_dimension(container, stock_code: str) -> dict:
    """成交力量维度（从ticker_data DB查询，避免依赖5s TTL缓存）"""
    dim = {"name": "成交力量", "icon": "⚡", "score": None, "label": "-"}
    try:
        db = container.db_manager
        today = datetime.now().strftime('%Y-%m-%d')
        rows = db.execute_query(
            """SELECT
                 SUM(CASE WHEN direction='BUY' THEN volume ELSE 0 END) as buy_vol,
                 SUM(volume) as total_vol
               FROM ticker_data
               WHERE stock_code = ? AND trade_date = ?""",
            (stock_code, today)
        )
        if rows and rows[0][1] and rows[0][1] > 0:
            buy_vol = rows[0][0] or 0
            total_vol = rows[0][1]
            ratio = buy_vol / total_vol
            dim["score"] = int(ratio * 100)
            dim["label"] = "看多" if ratio >= 0.55 else ("偏空" if ratio < 0.45 else "均衡")
    except Exception as e:
        logger.debug(f"成交力量获取失败 {stock_code}: {e}")
    return dim


def _get_capital_dimension(db, stock_code: str) -> dict:
    """资金流向维度"""
    dim = {"name": "资金流向", "icon": "💰", "score": None, "label": "-"}
    try:
        rows = db.execute_query(
            """SELECT capital_score, net_inflow_ratio
               FROM capital_flow_cache
               WHERE stock_code = ?
               ORDER BY timestamp DESC LIMIT 1""",
            (stock_code,)
        )
        if rows:
            score = rows[0][0] or 50
            ratio = rows[0][1] or 0
            dim["score"] = int(score)
            dim["label"] = "流入" if ratio > 0.02 else ("流出" if ratio < -0.02 else "均衡")
    except Exception as e:
        logger.debug(f"资金流向获取失败 {stock_code}: {e}")
    return dim


def _get_orderbook_dimension(db, stock_code: str) -> dict:
    """大单买卖比维度（替代不存在的盘口快照表）"""
    dim = {"name": "大单买卖", "icon": "📊", "score": None, "label": "-"}
    try:
        rows = db.execute_query(
            """SELECT buy_sell_ratio
               FROM big_order_tracking
               WHERE stock_code = ?
               ORDER BY timestamp DESC LIMIT 1""",
            (stock_code,)
        )
        if rows and rows[0][0]:
            ratio = rows[0][0]
            score = min(100, max(0, int(ratio / 3.0 * 100)))  # ratio 1.5=50, 3.0=100
            dim["score"] = score
            dim["label"] = "偏多" if score >= 60 else ("偏空" if score < 40 else "均衡")
    except Exception as e:
        logger.debug(f"大单买卖获取失败 {stock_code}: {e}")
    return dim


def _get_volume_dimension(db, stock_code: str) -> dict:
    """成交量能维度（从ticker_data今日买卖比推算）"""
    dim = {"name": "量能强弱", "icon": "📐", "score": None, "label": "-"}
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        rows = db.execute_query(
            """SELECT
                 SUM(CASE WHEN direction='BUY' THEN turnover ELSE 0 END) as buy_amt,
                 SUM(CASE WHEN direction='SELL' THEN turnover ELSE 0 END) as sell_amt
               FROM ticker_data
               WHERE stock_code = ? AND trade_date = ?""",
            (stock_code, today)
        )
        if rows and rows[0][0] is not None:
            buy = rows[0][0] or 0
            sell = rows[0][1] or 0
            total = buy + sell
            if total > 0:
                ratio = buy / total
                dim["score"] = int(ratio * 100)
                dim["label"] = "买强" if ratio >= 0.55 else ("卖强" if ratio < 0.45 else "均衡")
    except Exception as e:
        logger.debug(f"量能获取失败 {stock_code}: {e}")
    return dim


def _detect_conflicts(dimensions: list) -> list:
    """检测信号矛盾"""
    conflicts = []
    scored = {d["name"]: d["score"] for d in dimensions if d["score"] is not None}

    ticker = scored.get("成交力量")
    orderbook = scored.get("盘口挂单")
    if ticker and orderbook:
        if ticker >= 60 and orderbook < 40:
            conflicts.append("成交偏多但盘口偏空，可能存在压盘吸筹")
        elif ticker < 40 and orderbook >= 60:
            conflicts.append("盘口偏多但成交偏空，可能存在虚假挂单")

    capital = scored.get("资金流向")
    strategy = scored.get("趋势评分")
    if capital and strategy:
        if capital >= 60 and strategy < 40:
            conflicts.append("资金流入但趋势偏弱，关注反转信号")
        elif capital < 40 and strategy >= 60:
            conflicts.append("趋势良好但资金流出，警惕出货风险")

    return conflicts


def _get_5min_klines(db, stock_code: str, limit: int) -> list:
    """获取K线，优先5min表，回退到日线kline_data"""
    # 先尝试5分钟K线
    try:
        rows = db.execute_query(
            """SELECT time_key, open_price, high_price, low_price, close_price, volume
               FROM kline_5min_data
               WHERE stock_code = ?
               ORDER BY time_key DESC LIMIT ?""",
            (stock_code, limit)
        )
        if rows:
            result = [
                {"time": r[0], "open": r[1], "high": r[2],
                 "low": r[3], "close": r[4], "volume": r[5]}
                for r in rows
            ]
            result.reverse()
            return result
    except Exception:
        pass

    # 回退到日线K线
    rows = db.execute_query(
        """SELECT time_key, open_price, high_price, low_price, close_price, volume
           FROM kline_data
           WHERE stock_code = ?
           ORDER BY time_key DESC LIMIT ?""",
        (stock_code, limit)
    )
    result = [
        {"time": r[0], "open": r[1], "high": r[2],
         "low": r[3], "close": r[4], "volume": r[5]}
        for r in rows
    ]
    result.reverse()
    return result


def _get_delta_history(db, stock_code: str, limit: int) -> list:
    """获取Delta历史，优先专用表，回退从ticker_data合成"""
    # 先尝试专用表
    try:
        rows = db.execute_query(
            """SELECT timestamp, delta_value, cumulative_delta,
                      buy_volume, sell_volume
               FROM scalping_delta_history
               WHERE stock_code = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (stock_code, limit)
        )
        if rows:
            result = [
                {"time": r[0], "delta": r[1], "cum_delta": r[2],
                 "buy_vol": r[3], "sell_vol": r[4]}
                for r in rows
            ]
            result.reverse()
            return result
    except Exception:
        pass

    # 回退：从 ticker_data 按5分钟聚合合成 delta
    today = datetime.now().strftime('%Y-%m-%d')
    rows = db.execute_query(
        """SELECT
             CAST(timestamp / 300000 AS INTEGER) * 300000 as bar_ts,
             SUM(CASE WHEN direction='BUY' THEN volume ELSE 0 END) -
             SUM(CASE WHEN direction='SELL' THEN volume ELSE 0 END) as delta,
             SUM(CASE WHEN direction='BUY' THEN volume ELSE 0 END) as buy_vol,
             SUM(CASE WHEN direction='SELL' THEN volume ELSE 0 END) as sell_vol
           FROM ticker_data
           WHERE stock_code = ? AND trade_date = ?
           GROUP BY bar_ts
           ORDER BY bar_ts ASC""",
        (stock_code, today)
    )
    result = []
    cum = 0
    for r in rows:
        ts_ms = r[0]
        from datetime import datetime as dt, timezone, timedelta
        t = dt.fromtimestamp(ts_ms / 1000, tz=timezone(timedelta(hours=8)))
        time_str = t.strftime('%Y-%m-%d %H:%M')
        d = r[1] or 0
        cum += d
        result.append({
            "time": time_str,
            "delta": d,
            "cum_delta": cum,
            "buy_vol": r[2] or 0,
            "sell_vol": r[3] or 0,
        })
    return result[-limit:] if len(result) > limit else result


def _merge_kline_delta(klines: list, deltas: list) -> list:
    """按时间合并K线和Delta数据"""
    if not klines:
        return []

    # 构建delta查找表
    delta_map = {}
    for d in deltas:
        t = d.get("time", "")
        if t:
            key = t[:16]  # 截取到分钟
            delta_map[key] = d

    merged = []
    for k in klines:
        t = k.get("time", "")
        key = t[:16] if t else ""
        d = delta_map.get(key, {})
        merged.append({
            "time": k["time"],
            "open": k["open"],
            "high": k["high"],
            "low": k["low"],
            "close": k["close"],
            "volume": k["volume"],
            "delta": d.get("delta", 0),
            "cum_delta": d.get("cum_delta", 0),
            "buy_vol": d.get("buy_vol", 0),
            "sell_vol": d.get("sell_vol", 0),
        })
    return merged


logger.info("股票详情组合数据路由已注册")
