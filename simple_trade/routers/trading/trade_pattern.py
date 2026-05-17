#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易模式匹配 API — 分析历史买入模式，寻找类似阶段的股票
"""

import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from ...dependencies import get_container
from ...schemas.common import APIResponse

router = APIRouter(prefix="/api/trade-pattern", tags=["交易模式匹配"])
logger = logging.getLogger("router.trade_pattern")


@router.get("/similar-stocks", response_model=APIResponse)
async def get_similar_stocks(container=Depends(get_container)):
    """
    分析历史买入模式，在当前股票池中寻找类似买入阶段的股票。
    """
    db = getattr(container, 'db_manager', None)
    if not db:
        return APIResponse(success=False, data=None, message="数据库不可用")

    try:
        from ...services.analysis.trade_pattern_matcher import TradePatternMatcher
        matcher = TradePatternMatcher(db, container)
        result = await matcher.find_similar_stocks()
        return APIResponse(
            success=True,
            data=result,
            message=f"找到 {len(result.get('similar_stocks', []))} 只类似股票"
        )
    except Exception as e:
        logger.error(f"模式匹配异常: {e}", exc_info=True)
        return APIResponse(success=False, data=None, message=f"分析失败: {e}")


@router.get("/analyze-history", response_model=APIResponse)
async def analyze_trade_history(container=Depends(get_container)):
    """
    诊断接口：从富途API获取真实交易记录，分析每笔买入的K线上下文和买后表现。

    用于先审查数据，再制定选股规则。
    """
    db = getattr(container, 'db_manager', None)
    trade_service = getattr(container, 'futu_trade_service', None)

    if not trade_service:
        return APIResponse(success=False, data=None, message="futu_trade_service 不可用")

    order_mgr = getattr(trade_service, 'order_manager', None)
    if not order_mgr:
        return APIResponse(success=False, data=None, message="order_manager 不可用")

    trade_client = getattr(order_mgr, 'trade_client', None)
    if not trade_client:
        return APIResponse(success=False, data=None, message="trade_client 未连接，请先连接交易API")

    try:
        from futu import RET_OK

        # 查询最近60天的成交记录
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=60)
        trd_env = getattr(order_mgr, 'trd_env', None)

        ret, data = trade_client.history_deal_list_query(
            start=start_dt.strftime('%Y-%m-%d 00:00:00'),
            end=end_dt.strftime('%Y-%m-%d 23:59:59'),
            trd_env=trd_env,
        )

        if ret != RET_OK or data is None:
            return APIResponse(
                success=False, data=None,
                message=f"获取历史成交失败: {data}"
            )

        # 解析所有成交
        all_deals = []
        for _, row in data.iterrows():
            all_deals.append({
                "code": row.get('code', ''),
                "stock_name": str(row.get('stock_name', '')),
                "trd_side": str(row.get('trd_side', '')),
                "price": float(row.get('price', 0)),
                "qty": int(row.get('qty', 0)),
                "create_time": str(row.get('create_time', '')),
                "deal_id": str(row.get('deal_id', '')),
            })

        # 只取买入记录，按股票去重（取每只股票最近一次买入）
        buy_deals = [d for d in all_deals if d["trd_side"] == "BUY"]
        seen = set()
        unique_buys = []
        for d in buy_deals:
            if d["code"] not in seen:
                seen.add(d["code"])
                unique_buys.append(d)

        # 为每笔买入，分析K线上下文 + 买后表现
        analyzed = []
        for deal in unique_buys:
            code = deal["code"]
            buy_price = deal["price"]
            buy_time = deal["create_time"]
            buy_date = buy_time.split(" ")[0].split("T")[0] if buy_time else ""

            analysis = {
                "stock_code": code,
                "stock_name": deal["stock_name"],
                "buy_price": buy_price,
                "buy_time": buy_time,
                "buy_qty": deal["qty"],
            }

            if not db or not buy_date:
                analysis["error"] = "无法获取K线数据"
                analyzed.append(analysis)
                continue

            # 买入前K线（最近20根日K）
            try:
                before_klines = db.execute_query("""
                    SELECT time_key, open_price, high_price, low_price,
                           close_price, volume, turnover_rate
                    FROM kline_data
                    WHERE stock_code = ? AND time_key <= ?
                    ORDER BY time_key DESC LIMIT 20
                """, (code, buy_date))

                if before_klines and len(before_klines) >= 5:
                    before_klines = list(reversed(before_klines))
                    closes = [float(k[4]) for k in before_klines if k[4]]
                    highs = [float(k[2]) for k in before_klines if k[2]]
                    lows = [float(k[3]) for k in before_klines if k[3]]
                    opens = [float(k[1]) for k in before_klines if k[1]]
                    volumes = [int(k[5]) for k in before_klines if k[5]]

                    if closes and len(closes) >= 5:
                        peak = max(closes)
                        h, l = max(highs), min(lows)
                        pos = (closes[-1] - l) / (h - l) if h > l else 0.5

                        # 量比
                        if len(volumes) >= 6:
                            avg_vol = sum(volumes[-6:-1]) / 5
                            vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1
                        else:
                            vol_ratio = 1

                        analysis["before_buy"] = {
                            "kline_count": len(closes),
                            "drop_from_peak_pct": round((peak - closes[-1]) / peak * 100, 1) if peak > 0 else 0,
                            "kline_position": round(pos, 2),
                            "recent_5d_change_pct": round((closes[-1] - closes[-5]) / closes[-5] * 100, 1) if closes[-5] > 0 else 0,
                            "volume_ratio": round(vol_ratio, 2),
                            "last_is_bullish": closes[-1] > opens[-1] if opens else False,
                            "last_5_closes": [round(c, 3) for c in closes[-5:]],
                        }
                else:
                    analysis["before_buy"] = {"error": f"K线不足，只有{len(before_klines) if before_klines else 0}根"}
            except Exception as e:
                analysis["before_buy"] = {"error": str(e)}

            # 买入后K线（后5个交易日）
            try:
                after_klines = db.execute_query("""
                    SELECT time_key, open_price, high_price, low_price,
                           close_price, volume
                    FROM kline_data
                    WHERE stock_code = ? AND time_key >= ?
                    ORDER BY time_key ASC LIMIT 6
                """, (code, buy_date))

                if after_klines and len(after_klines) >= 2:
                    day0_close = float(after_klines[0][4]) if after_klines[0][4] else buy_price
                    day0_high = float(after_klines[0][2]) if after_klines[0][2] else 0

                    # 逐日表现
                    daily = []
                    for i, k in enumerate(after_klines):
                        c = float(k[4]) if k[4] else 0
                        h = float(k[2]) if k[2] else 0
                        change_from_buy = (c - buy_price) / buy_price * 100 if buy_price > 0 else 0
                        daily.append({
                            "day": i,
                            "date": str(k[0]),
                            "close": round(c, 3),
                            "high": round(h, 3),
                            "change_from_buy_pct": round(change_from_buy, 1),
                        })

                    # 整体表现
                    all_highs = [float(k[2]) for k in after_klines if k[2]]
                    max_high = max(all_highs) if all_highs else buy_price
                    max_rise = (max_high - buy_price) / buy_price * 100 if buy_price > 0 else 0

                    day1_close = float(after_klines[1][4]) if len(after_klines) >= 2 and after_klines[1][4] else day0_close
                    day1_change = (day1_close - day0_close) / day0_close * 100 if day0_close > 0 else 0

                    analysis["after_buy"] = {
                        "max_rise_pct": round(max_rise, 1),
                        "day1_change_pct": round(day1_change, 1),
                        "is_successful": max_rise > 1 or day1_change > 0,
                        "daily_performance": daily,
                    }
                else:
                    analysis["after_buy"] = {"error": "买后K线不足"}
            except Exception as e:
                analysis["after_buy"] = {"error": str(e)}

            analyzed.append(analysis)

        return APIResponse(
            success=True,
            data={
                "total_deals": len(all_deals),
                "buy_deals_count": len(buy_deals),
                "unique_stocks_bought": len(unique_buys),
                "analyzed_stocks": analyzed,
                "query_range": f"{start_dt.strftime('%Y-%m-%d')} ~ {end_dt.strftime('%Y-%m-%d')}",
            },
            message=f"获取到 {len(all_deals)} 条成交，分析了 {len(unique_buys)} 只���入股票"
        )
    except Exception as e:
        logger.error(f"分析历史交易异常: {e}", exc_info=True)
        return APIResponse(success=False, data=None, message=f"分析失败: {e}")

