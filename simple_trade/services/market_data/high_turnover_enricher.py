#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
活跃个股后台预计算任务

定时从缓存报价中取活跃股票，执行大单追踪和量比计算，
将结果写入 HighTurnoverCache 供 API 路由直接读取。

增强功能：
- 资金背离检测（涨跌幅 vs 大单方向）
- 大单动量趋势（加速/减速/稳定）
- 数据源标记（db_daily_accum）
"""

import asyncio
import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

# 配置常量
ENRICHER_INTERVAL = 20      # 刷新间隔（秒），从 30s 降至 20s 提升新鲜度
VOLUME_RATIO_KLINE_DAYS = 5  # 量比计算历史K线天数
BIG_ORDER_TOP_N = 50         # 大单追踪股票数量（与显示列表一致）
ACTIVE_STOCK_LIMIT = 100     # 与市场扫描 limit 对齐
CAPITAL_FLOW_BATCH_SIZE = 15 # 每轮资金流预填充数量（28 req/30s 限制下的安全值）

# 昨日活跃股票持久化文件（供次日启动预热）
_PERSIST_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    'data', 'prev_day_stocks.json'
)

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
        # 资金流轮转指针：记录上次处理到的位置，实现错开填充
        self._capital_flow_offset: int = 0
        # K线补充下载冷却记录（避免重复提交）
        self._kline_download_cooldown: dict[str, float] = {}
        self._bg_kline_task = None
        # strength 信号推送：记录上一轮 strength 值用于检测反转
        self._prev_strength: dict[str, float] = {}
        # 买卖推荐扫描计时器（每 5 分钟扫描一次）
        self._recommendation_scan_counter: int = 0
        self._RECOMMENDATION_INTERVAL: int = 15  # 15 * 20s = 300s = 5分钟

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

        # 2.5 逐笔强度持续采集（写入 big_order_tracking 供图表展示）
        # 优先追踪：目标股票页面中经过换手率筛选后展示的股票
        pool_codes = set()
        try:
            db = getattr(self._container, 'db_manager', None)
            if db:
                rows = db.execute_query("SELECT code FROM stocks WHERE is_low_activity = 0")
                pool_codes = {r[0] for r in rows} if rows else set()
        except Exception:
            pass
        top_set = set(top_codes)
        # 只追踪通过筛选的目标股票（在stocks表且有活跃行情）
        filtered_pool = [c for c in top_codes if c in pool_codes]
        priority = list(set(filtered_pool + (watchlist_codes or [])))
        await self._track_strength_snapshots(top_codes, priority)

        # 3. 量比计算
        await self._enrich_volume_ratio(top_codes, sorted_quotes, enrichment)

        # 4. 资金背离检测
        quotes_map = {q['code']: q for q in sorted_quotes if q.get('code')}
        self._detect_capital_divergence(enrichment, quotes_map)

        # 5. 大单动量趋势
        self._calc_big_order_momentum(enrichment)

        # 6. 资金流向预填充（轮转批次，不阻塞主循环）
        await self._enrich_capital_flow(top_codes)

        # 7. 流动性评分预计算（新增）
        await self._enrich_liquidity_scores(top_codes, sorted_quotes, enrichment)

        # 8. 股票行为标签（控盘检测）
        await self._enrich_stock_tags(top_codes, enrichment)

        # 9. 写入缓存 + 保存当前轮数据
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

        # 9. 持久化活跃股票列表（供次日启动预热）
        self._persist_active_stocks(top_codes)

        # 10. 定时买卖推荐扫描（每 5 分钟）
        self._recommendation_scan_counter += 1
        if self._recommendation_scan_counter >= self._RECOMMENDATION_INTERVAL:
            self._recommendation_scan_counter = 0
            await self._scan_and_push_recommendations()

    async def _enrich_big_orders(self, codes: list[str], enrichment: dict):
        """读取大单数据：从 daily_order_accumulator DB 表获取全天持久化数据"""
        db = getattr(self._container, 'db_manager', None)
        if not db or not codes:
            return
        try:
            trade_date = datetime.now().strftime("%Y-%m-%d")
            placeholders = ",".join("?" for _ in codes)
            rows = await db.async_execute_query(
                f"SELECT stock_code, "
                f" super_large_buy_amt, super_large_sell_amt, "
                f" large_buy_amt, large_sell_amt "
                f"FROM daily_order_accumulator "
                f"WHERE stock_code IN ({placeholders}) AND trade_date = ?",
                (*codes, trade_date),
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
                    f"【HighTurnoverEnricher】DB 补充 {db_count} 只股票的大单数据"
                )
        except Exception as e:
            logger.warning(f"【HighTurnoverEnricher】DB 查询失败: {e}")

    async def _track_strength_snapshots(self, codes: list[str], priority_codes: list[str] = None):
        """持续采集逐笔成交强度，写入 big_order_tracking 表供图表展示

        Args:
            codes: 未使用（保留接口兼容）
            priority_codes: 追踪的股票（目标股票页面筛选后的 + 自选股）
        """
        big_order_tracker = getattr(self._container, 'big_order_tracker', None)
        if not big_order_tracker:
            return

        track_set = list(dict.fromkeys(priority_codes or []))  # 去重保序
        if not track_set:
            return

        try:
            loop = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None, big_order_tracker.track_rt_tickers, track_set, len(track_set)
                ),
                timeout=15.0,
            )
            if result:
                logger.debug(
                    f"【HighTurnoverEnricher】strength 采集: {len(result)}/{len(track_set)} 只"
                    f" (含 {len(priority_codes or [])} 只目标股票)"
                )
                # 检测信号变化并推送企业微信
                await self._push_strength_signals(result)
        except asyncio.TimeoutError:
            logger.debug("【HighTurnoverEnricher】strength 采集超时(15s)")
        except Exception as e:
            logger.debug(f"【HighTurnoverEnricher】strength 采集异常: {e}")

    async def _push_strength_signals(self, big_order_result: dict):
        """检测 strength 信号变化并通过企业微信推送

        推送条件（任一触发）：
        1. strength 从正转负（主力由买转卖）
        2. strength 从负转正（主力由卖转买）
        3. strength 绝对值突然增大（趋势加速）

        防重复：每只股票同一信号 10 分钟内不重复推送（由 WeChatAlertService 控制���
        """
        wechat = getattr(self._container, 'wechat_alert_service', None)
        if not wechat or not wechat.enabled:
            return

        for code, data in big_order_result.items():
            strength = data.get('order_strength', 0)
            ratio = data.get('buy_sell_ratio', 1.0)
            prev = self._prev_strength.get(code)
            stock_name = data.get('stock_name', code)

            signal = None

            if prev is not None:
                # 信号1：从买转卖（strength 从 >0.15 降到 <-0.15）
                if prev > 0.15 and strength < -0.15:
                    signal = {
                        'type': '🔴 主力转卖',
                        'desc': f'强度从 +{prev:.2f} 转为 {strength:.2f}',
                        'level': 'warning',
                    }
                # 信号2：从卖转买（strength 从 <-0.15 升到 >0.15）
                elif prev < -0.15 and strength > 0.15:
                    signal = {
                        'type': '🟢 主力转买',
                        'desc': f'强度从 {prev:.2f} 转为 +{strength:.2f}',
                        'level': 'info',
                    }
                # 信号3：强度急剧增强（绝对值增加 >0.3）
                elif abs(strength) - abs(prev) > 0.3:
                    direction = '买入加速' if strength > 0 else '卖出加速'
                    signal = {
                        'type': f'⚡ {direction}',
                        'desc': f'强度从 {prev:+.2f} 变为 {strength:+.2f}',
                        'level': 'warning' if strength < 0 else 'info',
                    }

            # 更新记录
            self._prev_strength[code] = strength

            if signal:
                content = (
                    f"- 股票：**{stock_name}** ({code})\n"
                    f"- 信号：**{signal['type']}**\n"
                    f"- 详情：{signal['desc']}\n"
                    f"- 买卖比：{ratio:.2f}"
                )
                try:
                    from ..alert.wechat_alert import AlertLevel
                    level = AlertLevel.WARNING if signal['level'] == 'warning' else AlertLevel.INFO
                    await wechat.send(
                        level=level,
                        title=f"大单信号 - {stock_name}",
                        content=content,
                        dedup_key=f"strength_{code}_{signal['type']}",
                    )
                except Exception as e:
                    logger.debug(f"推送 strength 信号失败: {code}, {e}")

    async def _scan_and_push_recommendations(self):
        """每 5 分钟扫描目标股票和持仓，推送买入/卖出建议

        买入条件（目标股票）：
        - strength > 0.25 且 buy_sell_ratio > 1.3（主力明确买入）

        卖出条件（持仓股）：
        - strength < -0.15 且 buy_sell_ratio < 0.7（主力明确卖出）
        """
        wechat = getattr(self._container, 'wechat_alert_service', None)
        if not wechat or not wechat.enabled:
            return

        # 收集当前所有 strength 数据
        if not self._prev_strength:
            return

        db = getattr(self._container, 'db_manager', None)
        if not db:
            return

        # 获取持仓股代码（通过 Futu API）
        position_codes = set()
        position_info = {}  # code -> {qty, cost, market_val, pl_ratio}
        try:
            trade_svc = getattr(self._container, 'futu_trade_service', None)
            if trade_svc:
                loop = asyncio.get_running_loop()
                pos_result = await loop.run_in_executor(None, trade_svc.get_positions)
                if pos_result and pos_result.get('success'):
                    for p in pos_result.get('data', []):
                        code = p.get('code', '')
                        qty = p.get('qty', 0)
                        if code and qty > 0:
                            position_codes.add(code)
                            position_info[code] = {
                                'qty': qty,
                                'cost': p.get('cost_price', 0),
                                'pl_ratio': p.get('pl_ratio', 0),  # 盈亏比例%
                                'market_val': p.get('market_val', 0),
                            }
        except Exception as e:
            logger.debug(f"获取持仓失败: {e}")

        # 获取目标股票池
        pool_codes = set()
        try:
            pool_rows = db.execute_query(
                "SELECT code FROM stocks WHERE is_low_activity = 0"
            )
            if pool_rows:
                pool_codes = {r[0] for r in pool_rows}
        except Exception:
            pass

        # 获取最新 strength 快照
        buy_candidates = []
        sell_candidates = []

        for code, strength in self._prev_strength.items():
            # 从 big_order_tracking 取最新 ratio
            try:
                rows = db.execute_query("""
                    SELECT buy_sell_ratio, order_strength FROM big_order_tracking
                    WHERE stock_code = ? ORDER BY created_at DESC LIMIT 1
                """, (code,))
                ratio = float(rows[0][0]) if rows else 1.0
                str_val = float(rows[0][1]) if rows else strength
            except Exception:
                ratio = 1.0
                str_val = strength

            # 获取股票名称
            name = code
            try:
                name_rows = db.execute_query(
                    "SELECT name FROM stocks WHERE code = ?", (code,)
                )
                if name_rows:
                    name = name_rows[0][0] or code
            except Exception:
                pass

            # 获取换手率用于动态阈值（P3）
            avg_turnover = 1.0
            try:
                tr_rows = db.execute_query("""
                    SELECT AVG(turnover_rate) FROM (
                        SELECT turnover_rate FROM kline_data
                        WHERE stock_code = ? ORDER BY time_key DESC LIMIT 5
                    )
                """, (code,))
                if tr_rows and tr_rows[0][0]:
                    avg_turnover = float(tr_rows[0][0])
            except Exception:
                pass

            # 动态阈值：高流动性股票 strength 门槛低，低流动性门槛高
            if avg_turnover >= 3.0:
                buy_str_threshold, buy_ratio_threshold = 0.15, 1.2
            elif avg_turnover >= 1.0:
                buy_str_threshold, buy_ratio_threshold = 0.25, 1.3
            else:
                buy_str_threshold, buy_ratio_threshold = 0.40, 1.5

            # 买入信号：目标股票 + 主力在买（动态阈值）
            if code in pool_codes and code not in position_codes:
                if str_val > buy_str_threshold and ratio > buy_ratio_threshold:
                    buy_candidates.append({
                        'code': code, 'name': name,
                        'strength': str_val, 'ratio': ratio,
                        'turnover': avg_turnover,
                    })

            # 卖出信号：持仓股 + 多条件检测
            if code in position_codes:
                pinfo = position_info.get(code, {})
                pl_ratio = pinfo.get('pl_ratio', 0)
                sell_reason = None

                # 条件1：主力明确卖出
                if str_val < -0.15 and ratio < 0.7:
                    sell_reason = f"主力卖出 str={str_val:+.2f}"
                # 条件2：strength 持续为负（>= -0.05 但 ratio < 0.8）
                elif str_val < -0.05 and ratio < 0.8:
                    sell_reason = f"主力偏卖 str={str_val:+.2f}"
                # 条件3：浮亏超过 3%
                elif pl_ratio < -3.0:
                    sell_reason = f"浮亏{pl_ratio:.1f}%"

                if sell_reason:
                    sell_candidates.append({
                        'code': code, 'name': name,
                        'strength': str_val, 'ratio': ratio,
                        'pl_ratio': pl_ratio,
                        'reason': sell_reason,
                    })

        # 构建推送消息
        if not buy_candidates and not sell_candidates:
            return

        lines = []

        if buy_candidates:
            buy_candidates.sort(key=lambda x: x['strength'], reverse=True)
            lines.append("**🟢 建议关注买入：**")
            for c in buy_candidates[:5]:
                lines.append(
                    f"> **{c['name']}** ({c['code']}) "
                    f"强度 <font color=\"info\">{c['strength']:+.2f}</font> "
                    f"买卖比 {c['ratio']:.2f}"
                )

        if sell_candidates:
            sell_candidates.sort(key=lambda x: x['strength'])
            lines.append("**🔴 持仓预警：**")
            for c in sell_candidates[:5]:
                pl_text = f" 盈亏{c['pl_ratio']:+.1f}%" if c.get('pl_ratio') else ""
                lines.append(
                    f"> **{c['name']}** ({c['code']}) "
                    f"{c['reason']}{pl_text}"
                )

        # 基于内容的去重（推荐列表变化时才推新消息）
        import hashlib
        content_str = "\n".join(lines)
        content_hash = hashlib.md5(content_str.encode()).hexdigest()[:8]

        try:
            from ..alert.wechat_alert import AlertLevel
            level = AlertLevel.WARNING if sell_candidates else AlertLevel.INFO
            await wechat.send(
                level=level,
                title="交易建议速报",
                content=content_str,
                dedup_key=f"trade_rec_{content_hash}",
            )
        except Exception as e:
            logger.debug(f"推送交易建议失败: {e}")

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

    # ==================== 资金流向预填充 ====================

    async def _enrich_capital_flow(self, codes: list[str]):
        """后台预填充资金流向缓存（轮转批次）

        每轮从 codes 中取一批（CAPITAL_FLOW_BATCH_SIZE），调用
        fetch_capital_flow_data 填充 capital_flow_cache 表。
        下一轮从上次停止的位置继续，实现全量覆盖。
        """
        capital_analyzer = getattr(self._container, 'capital_analyzer', None)
        if not capital_analyzer:
            return

        total = len(codes)
        if total == 0:
            return

        # 轮转取一批
        start = self._capital_flow_offset % total
        batch = codes[start:start + CAPITAL_FLOW_BATCH_SIZE]
        # 如果尾部不够，从头部补
        if len(batch) < CAPITAL_FLOW_BATCH_SIZE:
            batch += codes[:CAPITAL_FLOW_BATCH_SIZE - len(batch)]
        self._capital_flow_offset = start + CAPITAL_FLOW_BATCH_SIZE

        try:
            loop = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None, capital_analyzer.fetch_capital_flow_data, batch, True
                ),
                timeout=20.0,
            )
            if result:
                logger.debug(
                    f"【HighTurnoverEnricher】资金流预填充: "
                    f"{len(result)}/{len(batch)} 只命中/请求"
                )
        except asyncio.TimeoutError:
            logger.warning(
                f"【HighTurnoverEnricher】资金流预填充超时(20s)，"
                f"批次: {batch[:3]}..."
            )
        except Exception as e:
            logger.warning(f"【HighTurnoverEnricher】资金流预填充异常: {e}")

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

    # ==================== 新增：流动性评分预计算 ====================

    async def _enrich_liquidity_scores(
        self,
        codes: list[str],
        quotes: list[dict],
        enrichment: dict
    ):
        """批量预计算流动性评分（20秒周期）

        Args:
            codes: 股票代码列表
            quotes: 报价列表
            enrichment: 预计算结果字典（会被修改）
        """
        liquidity_calc = getattr(self._container, 'liquidity_calculator', None)
        if not liquidity_calc:
            return

        quotes_map = {q['code']: q for q in quotes if q.get('code')}
        missing_kline_codes = []  # 收集K线数据不足的股票

        for code in codes:
            quote = quotes_map.get(code)
            if not quote:
                continue

            try:
                liq_result = await liquidity_calc.calculate_liquidity_score(
                    code, quote, include_history=True
                )
                enrichment.setdefault(code, {})
                enrichment[code]['liquidity_score'] = liq_result['liquidity_score']
                enrichment[code]['liquidity_level'] = liq_result['liquidity_level']
                enrichment[code]['is_volume_anomaly'] = liq_result['is_volume_anomaly']
                enrichment[code]['kline_data_missing'] = liq_result.get('kline_data_missing', False)
                enrichment[code]['volume_score'] = liq_result['volume_score']
                enrichment[code]['turnover_rate_score'] = liq_result['turnover_rate_score']
                enrichment[code]['amount_score'] = liq_result['amount_score']
                enrichment[code]['amplitude_score'] = liq_result['amplitude_score']
                enrichment[code]['stability_score'] = liq_result['stability_score']

                if liq_result.get('kline_data_missing'):
                    missing_kline_codes.append(code)
            except Exception as e:
                logger.warning(f"流动性评分计算失败 {code}: {e}")

        # 触发K线补充下载
        if missing_kline_codes:
            self._trigger_kline_download(missing_kline_codes)

    async def _enrich_stock_tags(self, codes: list[str], enrichment: dict):
        """批量计算股票行为标签（控盘/暴量/仙股/明星/正常）"""
        from .stock_profile_tagger import StockProfileTagger

        db = getattr(self._container, 'db_manager', None)
        if not db:
            logger.warning("【StockTags】db_manager 不可用，跳过标签计算")
            return

        tagger = StockProfileTagger()
        today = datetime.now().strftime('%Y-%m-%d')
        tagged_count = 0
        skip_count = 0

        for code in codes:
            try:
                rows = db.execute_query("""
                    SELECT time_key, open_price, high_price, low_price, close_price,
                           volume, turnover_rate
                    FROM kline_data WHERE stock_code = ? AND date(time_key) < ?
                    ORDER BY time_key DESC LIMIT 15
                """, (code, today))

                if not rows or len(rows) < 5:
                    skip_count += 1
                    continue

                cols = ["time_key", "open_price", "high_price", "low_price",
                        "close_price", "volume", "turnover_rate"]
                klines = [dict(zip(cols, r)) for r in rows]
                klines.reverse()

                # 获取当前价格（从 enrichment 中已有的报价数据）
                current_price = enrichment.get(code, {}).get('last_price', 0) or 0

                tag = tagger.tag_stock(code, klines, current_price)
                enrichment.setdefault(code, {})
                enrichment[code]['stock_tag_label'] = tag.label
                enrichment[code]['stock_tag_phase'] = tag.phase
                enrichment[code]['stock_tag_risk'] = tag.risk_note
                tagged_count += 1
            except Exception as e:
                logger.warning(f"【StockTags】标签计算失败 {code}: {e}")

        logger.info(f"【StockTags】标签计算完成: {tagged_count}只已标注, {skip_count}只K线不足跳过")

    def _trigger_kline_download(self, codes: list[str]):
        """触发K线数据补充下载（带1小时冷却期，避免重复提交）"""
        import time as _time
        now = _time.time()
        cooldown = 3600  # 1小时冷却

        new_codes = [
            c for c in codes
            if now - self._kline_download_cooldown.get(c, 0) > cooldown
        ]

        if not new_codes:
            return

        try:
            from .kline.background_kline_task import BackgroundKlineTask
            if self._bg_kline_task is None:
                self._bg_kline_task = BackgroundKlineTask(self._container)

            stocks = [{'code': c} for c in new_codes]
            self._bg_kline_task.submit(stocks)

            for c in new_codes:
                self._kline_download_cooldown[c] = now

            logger.info(
                f"【流动性】触发K线补充下载: {len(new_codes)} 只股票 "
                f"(前5: {new_codes[:5]})"
            )
        except Exception as e:
            logger.warning(f"【流动性】触发K线补充下载失败: {e}")

    # ==================== 持久化活跃股票池 ====================

    def _persist_active_stocks(self, codes: list[str]):
        """保存当前活跃股票列表到 JSON，供次日启动预热"""
        try:
            data = {
                'codes': codes,
                'date': datetime.now().strftime('%Y-%m-%d'),
                'count': len(codes),
            }
            os.makedirs(os.path.dirname(_PERSIST_FILE), exist_ok=True)
            with open(_PERSIST_FILE, 'w') as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception as e:
            logger.debug(f"保存活跃股票池失败: {e}")
