#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
活跃个股后台预计算任务

定时从缓存报价中取活跃股票，执行大单追踪和量比计算，
将结果写入 HighTurnoverCache 供 API 路由直接读取。

增强功能：
- 资金背离检测（涨跌幅 vs 大单方向）
- 大单动量趋势（加速/减速/稳定）
- 数据源标记（scalping_tick / db_daily_accum）
"""

import asyncio
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# 配置常量
ENRICHER_INTERVAL = 20      # 刷新间隔（秒），从 30s 降至 20s 提升新鲜度
VOLUME_RATIO_KLINE_DAYS = 5  # 量比计算历史K线天数
BIG_ORDER_TOP_N = 50         # 大单追踪股票数量（与显示列表一致）
ACTIVE_STOCK_LIMIT = 50      # 取换手率前N只

# 背离检测阈值
DIVERGENCE_PRICE_THRESHOLD = 3.0   # 涨跌幅阈值（%）
DIVERGENCE_RATIO_LOW = 0.8         # 买卖比低于此值视为净卖出
DIVERGENCE_RATIO_HIGH = 1.25       # 买卖比高于此值视为净买入


class HighTurnoverEnricher:
    """后台定时预计算活跃个股的大单和量比数据"""

    def __init__(self, container):
        self._container = container
        self._task: asyncio.Task | None = None
        self._running = False
        # 上一轮预计算数据，用于计算动量趋势
        self._prev_enrichment: dict[str, dict] = {}
        # 启动时间戳，用于冷却期跳过回退
        self._start_time: float = asyncio.get_running_loop().time()

    async def start(self):
        """启动后台循环"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("【HighTurnoverEnricher】后台预计算任务已启动")

    async def stop(self):
        """停止后台循环"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("【HighTurnoverEnricher】后台预计算任务已停止")

    async def _loop(self):
        """主循环：每 ENRICHER_INTERVAL 秒执行一次"""
        while self._running:
            try:
                await self._enrich_once()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"【HighTurnoverEnricher】预计算异常: {e}", exc_info=True)
            await asyncio.sleep(ENRICHER_INTERVAL)

    async def _enrich_once(self):
        """执行一次完整的预计算"""
        from ...core import get_state_manager
        state = get_state_manager()

        # 1. 获取缓存报价，按换手率排序取前N只
        cached_quotes = state.get_cached_quotes()
        if not cached_quotes:
            return

        sorted_quotes = sorted(
            [q for q in cached_quotes if isinstance(q, dict) and q.get('code')],
            key=lambda q: q.get('turnover_rate', 0) or 0,
            reverse=True,
        )
        top_codes = [q['code'] for q in sorted_quotes[:ACTIVE_STOCK_LIMIT]]

        # 确保自选股和持仓股始终被纳入预计算（即使不在换手率前N名）
        watchlist_codes = state.get_watchlist()
        if watchlist_codes:
            for code in watchlist_codes:
                if code not in top_codes:
                    top_codes.append(code)

        if not top_codes:
            return

        enrichment: dict[str, dict] = {}

        # 2. 大单追踪（在线程池中执行同步的 track_rt_tickers）
        await self._enrich_big_orders(top_codes, enrichment)

        # 3. 量比计算
        await self._enrich_volume_ratio(top_codes, sorted_quotes, enrichment)

        # 4. 资金背离检测
        quotes_map = {q['code']: q for q in sorted_quotes if q.get('code')}
        self._detect_capital_divergence(enrichment, quotes_map)

        # 5. 大单动量趋势
        self._calc_big_order_momentum(enrichment)

        # 6. 写入缓存 + 保存当前轮数据
        if enrichment:
            state.high_turnover_cache.update_batch(enrichment)
            self._prev_enrichment = {
                code: {
                    'verified_big_buy_amount': d.get('verified_big_buy_amount', 0),
                    'verified_big_sell_amount': d.get('verified_big_sell_amount', 0),
                }
                for code, d in enrichment.items()
            }
            logger.debug(
                f"【HighTurnoverEnricher】预计算完成，更新 {len(enrichment)} 只股票"
            )

    async def _enrich_big_orders(self, codes: list[str], enrichment: dict):
        """读取大单数据：优先从日度累加器（全天累积），不足部分从 DB 回退

        数据来源优先级:
        1. ScalpingPersistence._daily_accum（全天真实累积，由 DeltaCalculator 驱动）
        2. daily_order_accumulator DB 表（全天持久化数据，覆盖不在 Scalping 监控中的股票）
        """
        covered_codes = set()

        # --- 来源1：ScalpingPersistence 日度累加器（零 I/O）---
        persistence = getattr(self._container, 'scalping_persistence', None)
        if persistence and hasattr(persistence, '_daily_accum'):
            accum = persistence._daily_accum
            for code in codes:
                d = accum.get(code)
                if d is None:
                    continue
                big_buy = d.get('super_large_buy_amt', 0) + d.get('large_buy_amt', 0)
                big_sell = d.get('super_large_sell_amt', 0) + d.get('large_sell_amt', 0)
                # 跳过全为零（引擎刚启动尚无数据）
                if big_buy == 0 and big_sell == 0:
                    continue
                ratio = big_buy / big_sell if big_sell > 0 else (999.0 if big_buy > 0 else 1.0)
                enrichment.setdefault(code, {})
                enrichment[code]['verified_big_buy_amount'] = big_buy
                enrichment[code]['verified_big_sell_amount'] = big_sell
                enrichment[code]['verified_buy_sell_ratio'] = round(ratio, 2)
                enrichment[code]['big_order_data_source'] = 'scalping_tick'
                covered_codes.add(code)

        # --- 来源2：daily_order_accumulator DB 回退（全天持久化数据）---
        remaining = [c for c in codes if c not in covered_codes]
        if remaining:
            # 启动冷却期（60秒）内跳过回退，等 Scalping 积累数据
            elapsed = asyncio.get_running_loop().time() - self._start_time
            if elapsed < 60:
                logger.debug(
                    f"【HighTurnoverEnricher】启动冷却期({elapsed:.0f}s<60s)，"
                    f"跳过 {len(remaining)} 只股票的 DB 回退"
                )
                return

            db = getattr(self._container, 'db_manager', None)
            if db:
                try:
                    trade_date = datetime.now().strftime("%Y-%m-%d")
                    placeholders = ",".join("?" for _ in remaining)
                    rows = await db.async_execute_query(
                        f"SELECT stock_code, "
                        f" super_large_buy_amt, super_large_sell_amt, "
                        f" large_buy_amt, large_sell_amt "
                        f"FROM daily_order_accumulator "
                        f"WHERE stock_code IN ({placeholders}) AND trade_date = ?",
                        (*remaining, trade_date),
                    )
                    db_count = 0
                    for row in rows:
                        code = row[0]
                        big_buy = float(row[1] or 0) + float(row[3] or 0)
                        big_sell = float(row[2] or 0) + float(row[4] or 0)
                        if big_buy == 0 and big_sell == 0:
                            continue
                        ratio = big_buy / big_sell if big_sell > 0 else (999.0 if big_buy > 0 else 1.0)
                        enrichment.setdefault(code, {})
                        enrichment[code]['verified_big_buy_amount'] = big_buy
                        enrichment[code]['verified_big_sell_amount'] = big_sell
                        enrichment[code]['verified_buy_sell_ratio'] = round(ratio, 2)
                        enrichment[code]['big_order_data_source'] = 'db_daily_accum'
                        db_count += 1
                    if db_count > 0:
                        logger.debug(
                            f"【HighTurnoverEnricher】DB 回退补充 {db_count} 只股票的大单数据"
                        )
                except Exception as e:
                    logger.warning(f"【HighTurnoverEnricher】DB 回退查询失败: {e}")

    async def _enrich_volume_ratio(self, codes: list[str], quotes: list[dict], enrichment: dict):
        """批量预计算量比"""
        db = self._container.db_manager
        if not db:
            return

        quotes_map = {q['code']: q for q in quotes if isinstance(q, dict) and q.get('code')}
        loop = asyncio.get_running_loop()

        for code in codes:
            quote = quotes_map.get(code, {})
            current_vol = quote.get('volume', 0) or 0
            existing_vr = quote.get('volume_ratio', 0) or 0

            # 跳过已有量比或成交量为0的
            if existing_vr > 0 or current_vol <= 0:
                if existing_vr > 0 and code not in enrichment:
                    enrichment[code] = {}
                if existing_vr > 0:
                    enrichment.setdefault(code, {})['volume_ratio'] = existing_vr
                continue

            try:
                klines = await asyncio.wait_for(
                    loop.run_in_executor(
                        None, db.kline_queries.get_stock_kline, code, VOLUME_RATIO_KLINE_DAYS,
                    ),
                    timeout=5.0,
                )
                if not klines:
                    continue

                avg_vol = sum(k.get('volume', 0) for k in klines) / len(klines)
                if avg_vol > 0:
                    enrichment.setdefault(code, {})['volume_ratio'] = round(current_vol / avg_vol, 2)
            except Exception:
                pass  # 单只失败不影响整体

    # ==================== 新增：资金背离检测 ====================

    def _detect_capital_divergence(self, enrichment: dict, quotes_map: dict):
        """检测资金背离：涨跌幅与大单资金方向不一致

        在活跃股列表层面标注背离，让用户一眼看出异常股票。
        """
        for code, data in enrichment.items():
            quote = quotes_map.get(code, {})
            change_pct = quote.get('change_percent', 0) or 0
            ratio = data.get('verified_buy_sell_ratio', 1.0)

            divergence = None

            if change_pct >= DIVERGENCE_PRICE_THRESHOLD and ratio < DIVERGENCE_RATIO_LOW:
                divergence = {
                    "type": "bearish_divergence",
                    "label": "涨价卖出",
                    "desc": f"涨{change_pct:.1f}%但大单净卖(比={ratio:.2f})",
                }
            elif change_pct <= -DIVERGENCE_PRICE_THRESHOLD and ratio > DIVERGENCE_RATIO_HIGH:
                divergence = {
                    "type": "bullish_divergence",
                    "label": "跌价买入",
                    "desc": f"跌{abs(change_pct):.1f}%但大单净买(比={ratio:.2f})",
                }

            if divergence:
                data['capital_divergence'] = divergence

    # ==================== 新增：大单动量趋势 ====================

    def _calc_big_order_momentum(self, enrichment: dict):
        """计算大单动量趋势：与上一轮预计算数据比较

        通过比较当前轮和上一轮的大单净额，判断大单买入是在加速还是减速。
        """
        for code, data in enrichment.items():
            curr_buy = data.get('verified_big_buy_amount', 0)
            curr_sell = data.get('verified_big_sell_amount', 0)
            curr_net = curr_buy - curr_sell

            prev = self._prev_enrichment.get(code, {})
            prev_buy = prev.get('verified_big_buy_amount', 0)
            prev_sell = prev.get('verified_big_sell_amount', 0)
            prev_net = prev_buy - prev_sell

            if prev_net == 0 and prev_buy == 0:
                momentum = "unknown"
            elif curr_net > 0 and prev_net > 0 and curr_net > prev_net * 1.2:
                momentum = "accelerating"    # 买入加速
            elif curr_net > 0 and prev_net > 0 and curr_net < prev_net * 0.8:
                momentum = "decelerating"    # 买入减速
            elif curr_net < 0 and prev_net < 0 and curr_net < prev_net * 1.2:
                momentum = "accelerating"    # 卖出加速
            elif curr_net < 0 and prev_net < 0 and curr_net > prev_net * 0.8:
                momentum = "decelerating"    # 卖出减速
            elif curr_net * prev_net < 0:
                momentum = "reversing"       # 方向反转
            else:
                momentum = "stable"

            data['big_order_momentum'] = momentum
