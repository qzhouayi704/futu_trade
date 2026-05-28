#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盘后优选 API 路由"""

import asyncio
import json
import logging
from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ...dependencies import get_container
from ...core import get_state_manager
from ...schemas.common import APIResponse
from ...services.analysis.overnight_screener import OvernightScreener
from ...services.analysis.overnight_tracker import OvernightTracker

logger = logging.getLogger("overnight_screen")
router = APIRouter(prefix="/api/overnight-screen", tags=["盘后优选"])

# 全局任务状态
_task_status = {"running": False, "progress": "", "result": None, "error": None, "timestamp": None}


@router.post("", response_model=APIResponse)
async def trigger_screen(container=Depends(get_container)):
    """触发盘后优选评分"""
    global _task_status

    if _task_status["running"]:
        return APIResponse(success=False, message="优选任务正在运行中，请等待完成")

    # 判断数据源：盘中用历史收盘数据，收盘后用实时报价快照
    from ...utils.market_helper import MarketTimeHelper
    use_history = MarketTimeHelper.is_any_market_trading()
    source_label = "历史收盘数据" if use_history else "最新报价快照"

    _task_status = {"running": True, "progress": "准备数据...", "result": None, "error": None,
                    "timestamp": datetime.now().isoformat()}

    # 异步执行
    asyncio.create_task(_run_screen(container, use_history=use_history))
    return APIResponse(success=True, message=f"盘后优选已启动（数据源：{source_label}）", data={"status": "running"})


@router.get("/status", response_model=APIResponse)
async def get_status():
    """查询任务状态"""
    return APIResponse(success=True, message="获取状态成功", data={
        "running": _task_status["running"],
        "progress": _task_status["progress"],
        "has_result": _task_status["result"] is not None,
        "error": _task_status["error"],
        "timestamp": _task_status["timestamp"],
    })


@router.get("/dates", response_model=APIResponse)
async def get_dates(container=Depends(get_container)):
    """获取所有可用的优选日期列表"""
    try:
        rows = container.db_manager.execute_query(
            "SELECT screen_date, total_count FROM overnight_screen_results "
            "ORDER BY screen_date DESC"
        )
        dates = [{"date": r[0], "count": r[1] or 0} for r in rows] if rows else []
        return APIResponse(success=True, message=f"共 {len(dates)} 个日期", data={"dates": dates})
    except Exception as e:
        logger.warning(f"获取优选日期列表失败: {e}")
        return APIResponse(success=True, message="获取日期失败", data={"dates": []})


@router.get("/result", response_model=APIResponse)
async def get_result(screen_date: Optional[str] = None, container=Depends(get_container)):
    """获取优选结果（优先内存，其次DB持久化），支持按日期查询"""
    if _task_status["running"]:
        return APIResponse(success=True, message="任务运行中", data={"running": True, "candidates": []})

    result = None
    timestamp = None

    # 指定日期 → 直接从DB查询
    if screen_date:
        try:
            rows = container.db_manager.execute_query(
                "SELECT candidates_json, created_at FROM overnight_screen_results "
                "WHERE screen_date = ?", (screen_date,)
            )
            if rows:
                result = json.loads(rows[0][0])
                timestamp = rows[0][1]
        except Exception as e:
            logger.warning(f"从DB加载 {screen_date} 优选结果失败: {e}")
    else:
        # 未指定日期 → 优先内存，其次DB最新
        result = _task_status.get("result")
        timestamp = _task_status.get("timestamp")

        if not result:
            try:
                rows = container.db_manager.execute_query(
                    "SELECT candidates_json, created_at FROM overnight_screen_results "
                    "ORDER BY screen_date DESC LIMIT 1"
                )
                if rows:
                    result = json.loads(rows[0][0])
                    timestamp = rows[0][1]
                    _task_status["result"] = result
                    _task_status["timestamp"] = timestamp
            except Exception as e:
                logger.warning(f"从DB加载盘后优选结果失败: {e}")

    if not result:
        return APIResponse(success=True, message="暂无结果，请先触发优选", data={"candidates": [], "total": 0})

    # 附加突破候选股数据（仅当前会话有效）
    breakout_data = _task_status.get("breakout_candidates", []) if not screen_date else []
    consolidation_data = _task_status.get("consolidation_candidates", []) if not screen_date else []

    return APIResponse(success=True, message=f"共 {len(result)} 只推荐股票", data={
        "candidates": result,
        "timestamp": timestamp,
        "total": len(result),
        "breakout_candidates": breakout_data,
        "consolidation_candidates": consolidation_data,
    })


async def auto_trigger_screen(container):
    """收盘后自动触发盘后优选（供 DailyKlineUpdater 调用）"""
    global _task_status
    if _task_status["running"]:
        logger.info("[盘后优选] 自动触发时已有任务在运行，跳过")
        return

    _task_status = {"running": True, "progress": "自动触发...", "result": None, "error": None,
                    "timestamp": datetime.now().isoformat()}
    logger.info("[盘后优选] 收盘后自动触发评分")
    await _run_screen(container, use_history=False)


async def _run_screen(container, use_history: bool = False):
    """后台执行优选任务

    Args:
        container: 服务容器
        use_history: True=使用历史K线收盘数据（盘中）, False=使用实时报价快照（收盘后）
    """
    global _task_status
    try:
        if use_history:
            _task_status["progress"] = "读取历史收盘数据..."
            stock_list, data_date = await asyncio.to_thread(_get_stock_list_from_history, container)
        else:
            data_date = None
            _task_status["progress"] = "获取市场扫描池股票..."
            stock_list = await asyncio.to_thread(_get_stock_list, container)
            # 收盘后重启场景：内存快照为空，回退到历史K线
            if not stock_list:
                logger.info("[盘后优选] 实时快照为空（可能是重启后），回退到历史K线数据")
                stock_list, data_date = await asyncio.to_thread(_get_stock_list_from_history, container)
                use_history = True

        if not stock_list:
            _task_status["error"] = (
                "未获取到股票数据。"
                + ("请确保K线数据库有历史数据。" if use_history else "请确保市场扫描已运行。")
            )
            _task_status["running"] = False
            return

        _task_status["progress"] = f"对 {len(stock_list)} 只股票评分中（{'历史数据' if use_history else '实时数据'}）..."

        screener = OvernightScreener(db_manager=container.db_manager, container=container)
        candidates = await screener.run_screen(stock_list)

        _task_status["result"] = [c.to_dict() for c in candidates]
        _task_status["timestamp"] = datetime.now().isoformat()

        # === 补充下载当天K线数据（确保突破扫描使用最新数据） ===
        _task_status["progress"] = "补充下载K线..."
        try:
            await asyncio.to_thread(_download_today_klines, container, stock_list)
        except Exception as e:
            logger.warning(f"[盘后优选] K线补充下载失败: {e}")

        # === 自动运行突破扫描器 ===
        _task_status["progress"] = "运行突破扫描..."
        try:
            from ...services.analysis.breakout_scanner import BreakoutScanner
            scanner = BreakoutScanner(db_manager=container.db_manager)
            breakout_list = await asyncio.to_thread(scanner.scan)
            _task_status["breakout_candidates"] = [b.to_dict() for b in breakout_list]
            logger.info(f"[盘后优选] 突破扫描完成，{len(breakout_list)} 只候选")
        except Exception as e:
            logger.warning(f"[盘后优选] 突破扫描失败: {e}")
            _task_status["breakout_candidates"] = []

        # === 自动运行横盘启动扫描器 ===
        _task_status["progress"] = "运行横盘启动扫描..."
        try:
            from ...services.analysis.consolidation_breakout_scanner import ConsolidationBreakoutScanner
            consol_scanner = ConsolidationBreakoutScanner(db_manager=container.db_manager)
            consol_list = await asyncio.to_thread(consol_scanner.scan)
            _task_status["consolidation_candidates"] = [c.to_dict() for c in consol_list]
            logger.info(f"[盘后优选] 横盘启动扫描完成，{len(consol_list)} 只候选")
        except Exception as e:
            logger.warning(f"[盘后优选] 横盘启动扫描失败: {e}")
            _task_status["consolidation_candidates"] = []

        _task_status["progress"] = "完成"

        # 持久化到DB
        try:
            # screen_date 用数据日期（而非点击日期），确保同一份数据只存一条记录
            screen_date = data_date if data_date else date.today().isoformat()
            candidates_json = json.dumps(_task_status["result"], ensure_ascii=False)
            container.db_manager.execute_update(
                "INSERT OR REPLACE INTO overnight_screen_results "
                "(screen_date, candidates_json, total_count) VALUES (?, ?, ?)",
                (screen_date, candidates_json, len(candidates))
            )
            logger.info(f"[盘后优选] 结果已持久化，日期={screen_date}")
        except Exception as e:
            logger.warning(f"[盘后优选] 持久化失败: {e}")

        logger.info(f"[盘后优选] 完成，返回 {len(candidates)} 只推荐")

        # === 自动追踪前一次推荐的次日表现 ===
        try:
            tracker = OvernightTracker(container.db_manager)
            track_result = tracker.track_previous_screen()
            if track_result.get('success'):
                logger.info(
                    f"[优选追踪] 自动追踪完成: {track_result['screen_date']} → "
                    f"胜率{track_result['win_rate']}% 均盈{track_result['avg_pnl']:+.2f}%"
                )
        except Exception as e:
            logger.debug(f"[优选追踪] 自动追踪失败: {e}")

        # === 自动创建交易任务（如果开启了自动交易） ===
        if container.config.auto_trade and candidates:
            _auto_create_trade_tasks(container, candidates)

    except Exception as e:
        logger.error(f"[盘后优选] 执行失败: {e}", exc_info=True)
        _task_status["error"] = str(e)
    finally:
        _task_status["running"] = False


def _get_stock_list(container) -> list:
    """从市场扫描报价快照获取活跃股列表

    使用 get_last_quotes()（不检查TTL）而非 get_cached_quotes()，
    确保收盘后仍能获取到最后一次市场扫描的完整报价数据。
    """
    stocks = []
    seen = set()

    state = get_state_manager()
    # 收盘后 get_cached_quotes() 因TTL过期返回None，
    # get_last_quotes() 返回最后一次快照，不受TTL限制
    cached_quotes = state.quote_cache.get_last_quotes()
    if cached_quotes:
        for q in cached_quotes:
            code = q.get('code', q.get('stock_code', ''))
            if code and code not in seen:
                seen.add(code)
                stocks.append({
                    'code': code,
                    'name': q.get('name', q.get('stock_name', '')),
                    'market': q.get('market', ''),
                    'last_price': q.get('last_price', q.get('cur_price', 0)),
                    'change_rate': q.get('change_rate', q.get('change_percent', 0)),
                    'turnover_rate': q.get('turnover_rate', 0),
                    'turnover': q.get('turnover', q.get('amount', 0)),
                    'volume_ratio': q.get('volume_ratio', 0),
                    'amplitude': q.get('amplitude', 0),
                    'high_price': q.get('high_price', 0),
                    'low_price': q.get('low_price', 0),
                    'open_price': q.get('open_price', 0),
                    'prev_close_price': q.get('prev_close_price', 0),
                    'capital_signal': q.get('capital_signal', ''),
                    'plates': q.get('plates', []),
                    'is_position': q.get('is_position', False),
                    'leader_rank': q.get('leader_rank', 0),
                })

    logger.info(f"[盘后优选] 收集到 {len(stocks)} 只股票（市场扫描快照）")
    return stocks


def _get_stock_list_from_history(container) -> tuple:
    """从DK线历史收盘数据构建股票列表（盘中/重启后使用）

    读取最近一个已完成交易日的K线收盘数据。
    排除今天的K线（可能是预下载的不完整数据）。

    Returns:
        (stock_list, data_date) 元组，data_date 是数据对应的交易日(YYYY-MM-DD)
    """
    db = container.db_manager
    stocks = []
    data_date = None

    try:
        # 获取最近一个已完成交易日的K线数据
        # 排除今天（可能是预下载的不完整数据）
        today_prefix = date.today().isoformat()  # '2026-05-19'
        date_row = db.execute_query(
            "SELECT DISTINCT time_key FROM kline_data "
            "WHERE time_key < ? "
            "ORDER BY time_key DESC LIMIT 1",
            (today_prefix,)
        )
        if not date_row:
            logger.warning("[盘后优选] K线数据库为空，无法获取历史数据")
            return [], None

        last_date = date_row[0][0]
        # 提取纯日期部分作为 data_date
        data_date = last_date[:10]  # '2026-05-18 00:00:00' -> '2026-05-18'
        logger.info(f"[盘后优选] 使用历史数据日期: {data_date}")

        # 读取该日所有股票的K线
        rows = db.execute_query(
            "SELECT k.stock_code, s.name, "
            "k.close_price, k.open_price, k.high_price, k.low_price, k.volume "
            "FROM kline_data k "
            "LEFT JOIN stocks s ON k.stock_code = s.code "
            "WHERE k.time_key = ?",
            (last_date,)
        )
        if not rows:
            logger.warning(f"[盘后优选] {last_date} 无K线数据")
            return [], data_date

        for row in rows:
            code, name, close_p, open_p, high_p, low_p, volume = row
            if not code or not close_p:
                continue

            # 计算涨跌幅（用前一日收盘价）
            prev_row = db.execute_query(
                "SELECT close_price, volume FROM kline_data "
                "WHERE stock_code = ? AND time_key < ? "
                "ORDER BY time_key DESC LIMIT 1",
                (code, last_date)
            )
            prev_close = prev_row[0][0] if prev_row and prev_row[0][0] else close_p
            change_rate = ((close_p - prev_close) / prev_close * 100) if prev_close > 0 else 0

            # 计算振幅
            amplitude = ((high_p - low_p) / prev_close * 100) if prev_close > 0 else 0

            # 计算量比：当日成交量 / 5日均量
            volume_ratio = 0
            if volume and volume > 0:
                vol_rows = db.execute_query(
                    "SELECT volume FROM kline_data "
                    "WHERE stock_code = ? AND time_key < ? "
                    "ORDER BY time_key DESC LIMIT 5",
                    (code, last_date)
                )
                if vol_rows:
                    avg_vol = sum(r[0] for r in vol_rows if r[0]) / len(vol_rows)
                    if avg_vol > 0:
                        volume_ratio = round(volume / avg_vol, 2)

            stocks.append({
                'code': code,
                'name': name or '',
                'market': 'HK' if code.startswith('HK.') else ('US' if code.startswith('US.') else ''),
                'last_price': close_p,
                'change_rate': round(change_rate, 2),
                'turnover_rate': 0,  # K线无换手率，排除条件已兼容
                'turnover': 0,
                'volume_ratio': volume_ratio,
                'amplitude': round(amplitude, 2),
                'high_price': high_p or 0,
                'low_price': low_p or 0,
                'open_price': open_p or 0,
                'prev_close_price': prev_close,
                'plates': [],
                'leader_rank': 0,
            })

        logger.info(f"[盘后优选] 收集到 {len(stocks)} 只股票（历史K线 {last_date}）")
    except Exception as e:
        logger.error(f"[盘后优选] 读取历史数据失败: {e}", exc_info=True)

    return stocks, data_date


def _download_today_klines(container, stock_list: list):
    """检查当天K线数据就绪状态（下载由 DailyKlineUpdater 负责）"""
    from ...utils.market_helper import MarketTimeHelper

    db = container.db_manager
    sample_code = stock_list[0].get('code', '') if stock_list else ''
    if not sample_code:
        return

    market = MarketTimeHelper.get_market_from_code(sample_code)
    today_str = MarketTimeHelper.get_market_today(market)

    rows = db.execute_query(
        "SELECT count(DISTINCT stock_code) FROM kline_data WHERE time_key >= ?",
        (today_str,)
    )
    count = rows[0][0] if rows else 0
    total = len(stock_list)
    logger.info(f"[盘后K线] 当天K线就绪: {count}/{total} 只股票有今天数据")


def _auto_create_trade_tasks(container, candidates):
    """根据盘后优选结果，自动创建交易任务

    - TREND: 阶梯低吸(前收-1%/前收)，SL=8%，持仓3天
    - REVERSAL(≥75分): 次日开盘买，SL=20%，持仓30天
    - 每只最多创建1个任务
    - 受限买规则约束(30天内同股最多2次)
    """
    try:
        auto_trade_svc = getattr(container, 'auto_trade_service', None)
        if not auto_trade_svc:
            logger.warning("[自动交易] AutoTradeService 不可用，跳过任务创建")
            return

        created = 0
        skipped = 0
        max_tasks = 5  # 每次最多创建5个任务

        for cand in candidates:
            if created >= max_tasks:
                break

            cand_dict = cand.to_dict() if hasattr(cand, 'to_dict') else cand
            code = cand_dict.get('stock_code', '')
            score = cand_dict.get('total_score', 0)
            category = cand_dict.get('category', '')
            metrics = cand_dict.get('key_metrics', {})
            prev_close = metrics.get('prev_close_price', metrics.get('last_price', 0))

            if not code or prev_close <= 0:
                continue

            # 判断策略类型
            is_trend = 'TREND' in category.upper() or '趋势' in category
            is_reversal = not is_trend

            # REVERSAL需要75分以上（回测验证：活跃股60-70分REVERSAL亏损）
            if is_reversal and score < 75:
                skipped += 1
                continue

            # 参数设置
            if is_trend:
                buy_dip_pct = 1.0   # 阶梯: 先-1%, 兜底前收
                sell_rise_pct = 10.0  # 追踪激活
                stop_loss_pct = 8.0
            else:
                buy_dip_pct = 0.0   # 次日开盘
                sell_rise_pct = 15.0
                stop_loss_pct = 20.0

            qty = 100  # 默认最小手数，实际应根据仓位管理计算

            result = auto_trade_svc.start_auto_trade(
                stock_code=code,
                quantity=qty,
                zone='overnight',
                buy_dip_pct=buy_dip_pct,
                sell_rise_pct=sell_rise_pct,
                stop_loss_pct=stop_loss_pct,
                prev_close=prev_close,
            )

            if result.get('success'):
                created += 1
                logger.info(
                    f"[自动交易] 创建任务: {code} "
                    f"({'TREND' if is_trend else 'REVERSAL'}) "
                    f"score={score} prev={prev_close:.3f}"
                )
            else:
                skipped += 1
                logger.debug(f"[自动交易] 跳过 {code}: {result.get('message', '')}")

        logger.info(f"[自动交易] 自动创建 {created} 个任务，跳过 {skipped} 个")
    except Exception as e:
        logger.error(f"[自动交易] 创建任务异常: {e}", exc_info=True)



logging.info("盘后优选路由已注册")


# ==================== Dashboard 聚合 API ====================


@router.get("/dashboard", response_model=APIResponse)
async def get_dashboard_data(container=Depends(get_container)):
    """首页盘后优选卡片 — 聚合优选结果 + 实时行情 + 资金信号"""
    try:
        # 1. 获取优选结果（优先内存，其次DB最新）
        candidates = _task_status.get("result")
        timestamp = _task_status.get("timestamp")

        if not candidates:
            try:
                rows = container.db_manager.execute_query(
                    "SELECT candidates_json, created_at FROM overnight_screen_results "
                    "ORDER BY screen_date DESC LIMIT 1"
                )
                if rows:
                    candidates = json.loads(rows[0][0])
                    timestamp = rows[0][1]
            except Exception as e:
                logger.debug(f"[盘后Dashboard] 读DB失败: {e}")

        if not candidates:
            return APIResponse(success=True, message="暂无优选数据", data={"items": [], "timestamp": None})

        # 2. 构建实时报价索引
        quote_map = {}
        try:
            state = get_state_manager()
            cached_quotes = state.quote_cache.get_last_quotes()
            if cached_quotes:
                for q in cached_quotes:
                    code = q.get('code', q.get('stock_code', ''))
                    if code:
                        quote_map[code] = q
        except Exception:
            pass

        # 3. 批量查资金流 + 大单
        codes = [c.get('stock_code', '') for c in candidates if c.get('stock_code')]
        capital_map = {}
        big_order_map = {}
        try:
            if codes:
                placeholders = ','.join(['?'] * len(codes))
                # 资金流
                cap_rows = container.db_manager.execute_query(
                    f"SELECT stock_code, net_inflow_ratio, capital_score "
                    f"FROM capital_flow_cache WHERE stock_code IN ({placeholders}) "
                    f"GROUP BY stock_code HAVING MAX(timestamp)",
                    tuple(codes)
                )
                if cap_rows:
                    for r in cap_rows:
                        capital_map[r[0]] = {'net_inflow_ratio': r[1] or 0, 'capital_score': r[2] or 50}

                # 大单
                bo_rows = container.db_manager.execute_query(
                    f"SELECT stock_code, buy_sell_ratio "
                    f"FROM big_order_tracking WHERE stock_code IN ({placeholders}) "
                    f"GROUP BY stock_code HAVING MAX(timestamp)",
                    tuple(codes)
                )
                if bo_rows:
                    for r in bo_rows:
                        big_order_map[r[0]] = r[1] or 0
        except Exception as e:
            logger.debug(f"[盘后Dashboard] 查资金/大单失败: {e}")

        # 4. 聚合输出
        items = []
        for c in candidates:
            code = c.get('stock_code', '')
            if not code:
                continue

            quote = quote_map.get(code, {})
            cap = capital_map.get(code, {})
            bo_ratio = big_order_map.get(code, 0)

            # 资金信号判定
            cap_score = cap.get('capital_score', 50)
            net_ratio = cap.get('net_inflow_ratio', 0)
            if cap_score >= 65:
                capital_signal = "偏多"
            elif cap_score <= 35:
                capital_signal = "偏空"
            else:
                capital_signal = "中性"

            items.append({
                'stock_code': code,
                'stock_name': c.get('stock_name', ''),
                'total_score': c.get('total_score', 0),
                'category': c.get('category', ''),
                'verdict': c.get('verdict', ''),
                'reasons': c.get('reasons', []),
                'screen_change_rate': c.get('key_metrics', {}).get('change_rate', 0),
                'live_price': quote.get('last_price', quote.get('cur_price', 0)),
                'live_change_rate': quote.get('change_rate', quote.get('change_percent', 0)),
                'capital_signal': capital_signal,
                'capital_score': cap_score,
                'net_inflow_ratio': net_ratio,
                'big_order_ratio': round(bo_ratio, 2) if bo_ratio else 0,
                'volume_ratio': quote.get('volume_ratio', 0),
            })

        return APIResponse(
            success=True,
            message=f"共 {len(items)} 只推荐",
            data={"items": items, "timestamp": timestamp}
        )
    except Exception as e:
        logger.error(f"[盘后Dashboard] 异常: {e}", exc_info=True)
        return APIResponse(success=False, message=str(e))


# ==================== 表现追踪 API ====================



@router.post("/track", response_model=APIResponse)
async def trigger_track(
    screen_date: Optional[str] = None,
    container=Depends(get_container),
):
    """手动触发表现追踪（追踪指定日期的优选推荐在次日的表现）"""
    try:
        tracker = OvernightTracker(container.db_manager)
        result = tracker.track_previous_screen(screen_date)
        return APIResponse(
            success=result.get('success', False),
            message=result.get('message', ''),
            data=result,
        )
    except Exception as e:
        logger.error(f"[优选追踪] 触发失败: {e}")
        return APIResponse(success=False, message=str(e))


@router.get("/performance", response_model=APIResponse)
async def get_performance(
    days: int = 30,
    container=Depends(get_container),
):
    """获取评分表现统计（各分数段胜率、各模式胜率）"""
    try:
        tracker = OvernightTracker(container.db_manager)
        stats = tracker.get_performance_stats(days)
        return APIResponse(success=True, message="获取统计成功", data=stats)
    except Exception as e:
        logger.error(f"[优选追踪] 获取统计失败: {e}")
        return APIResponse(success=False, message=str(e))


@router.get("/performance/recent", response_model=APIResponse)
async def get_recent_performance(
    limit: int = 10,
    container=Depends(get_container),
):
    """获取最近N个交易日的追踪汇总"""
    try:
        tracker = OvernightTracker(container.db_manager)
        recent = tracker.get_recent_performance(limit)
        return APIResponse(success=True, message=f"最近{len(recent)}个交易日", data={"daily": recent})
    except Exception as e:
        logger.error(f"[优选追踪] 获取近期表现失败: {e}")
        return APIResponse(success=False, message=str(e))
