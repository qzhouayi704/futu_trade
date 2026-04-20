"""
健康监控器

负责：
1. 定期 flush Delta 和计算 POC
2. 健康检查：监控数据流是否正常
3. 自动重连：连续失败时触发重新订阅
"""

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from simple_trade.utils.logger import print_status

if TYPE_CHECKING:
    from simple_trade.services.scalping.engine import ScalpingEngine

logger = logging.getLogger("scalping.health_monitor")

# 健康检查间隔（秒）
_HEALTH_CHECK_INTERVAL = 40.0
# 数据超时阈值（秒）- 超过此时间未收到数据视为不健康
_DATA_TIMEOUT = 120.0
# Delta flush 间隔（秒）
_DELTA_FLUSH_INTERVAL = 10.0
# POC 计算间隔（秒）
_POC_CALC_INTERVAL = 5.0
# 连续健康检查失败触发重新订阅的阈值
_HEALTH_FAIL_THRESHOLD = 3


class HealthMonitor:
    """健康监控器 - 定期 flush 和健康检查"""

    def __init__(
        self,
        engine: "ScalpingEngine",
        subscription_manager,
    ):
        self._engine = engine
        self._subscription_manager = subscription_manager

        # Flush 时间跟踪
        self._last_delta_flush: dict[str, float] = {}
        self._last_poc_calc: dict[str, float] = {}
        # 连续健康检查失败计数
        self._health_fail_counts: dict[str, int] = {}

    def add_stock(self, stock_code: str) -> None:
        """添加股票到监控列表"""
        now = time.time()
        self._last_delta_flush[stock_code] = now
        self._last_poc_calc[stock_code] = now
        self._health_fail_counts[stock_code] = 0

    def remove_stock(self, stock_code: str) -> None:
        """从监控列表移除股票"""
        self._last_delta_flush.pop(stock_code, None)
        self._last_poc_calc.pop(stock_code, None)
        self._health_fail_counts.pop(stock_code, None)

    async def flush_loop(self, stocks_getter, running_checker) -> None:
        """定期 flush Delta 和计算 POC（墙钟驱动）"""
        logger.info("Flush 循环启动")
        while running_checker():
            try:
                await asyncio.sleep(1.0)
                now = time.time()

                for stock_code in stocks_getter():
                    # Delta flush
                    last_flush = self._last_delta_flush.get(stock_code, 0.0)
                    if now - last_flush >= _DELTA_FLUSH_INTERVAL:
                        self._last_delta_flush[stock_code] = now
                        # 先读取大单占比（flush 会重置 current_period 导致数据丢失）
                        big_ratio = self._engine._delta_calculator.get_big_order_ratio(
                            stock_code
                        )
                        try:
                            await self._engine._delta_calculator.flush_period(
                                stock_code
                            )
                            # 打印 Delta 多空比例
                            recent = (
                                self._engine._delta_calculator.get_recent_deltas(
                                    stock_code, 1
                                )
                            )
                            if recent:
                                d = recent[-1]
                                direction = (
                                    "多"
                                    if d.delta > 0
                                    else ("空" if d.delta < 0 else "平")
                                )
                                logger.info(
                                    f"[{stock_code}] Delta flush: {d.delta:+.0f} ({direction}), "
                                    f"vol={d.volume}"
                                )
                        except Exception as e:
                            logger.debug(f"[{stock_code}] flush_period 异常: {e}")
                        # flush 后将指标快照写入 StateManager（传入预读的 big_ratio）
                        self._engine._calc_scheduler.publish_scalping_metrics(
                            stock_code, big_ratio
                        )

                        # 行为模式检测（在 delta flush 后执行）
                        try:
                            await self._run_pattern_detection(stock_code)
                        except Exception as e:
                            logger.debug(f"[{stock_code}] 模式检测异常: {e}")

                    # POC 计算
                    last_poc = self._last_poc_calc.get(stock_code, 0.0)
                    if now - last_poc >= _POC_CALC_INTERVAL:
                        self._last_poc_calc[stock_code] = now
                        try:
                            await self._engine._poc_calculator.calculate_poc(
                                stock_code
                            )
                            # 打印 POC 计算结果摘要
                            vol_profile = (
                                self._engine._poc_calculator.get_volume_profile(
                                    stock_code
                                )
                            )
                            if vol_profile:
                                poc_price = max(vol_profile, key=vol_profile.get)
                                poc_vol = vol_profile[poc_price]
                                logger.info(
                                    f"[{stock_code}] POC: price={poc_price}, "
                                    f"vol={poc_vol}, levels={len(vol_profile)}"
                                )
                        except Exception as e:
                            logger.debug(f"[{stock_code}] calculate_poc 异常: {e}")

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"Flush 循环异常: {e}")

    async def health_check_loop(
        self, stocks_getter, running_checker, last_data_time_getter
    ) -> None:
        """定期检查各股票数据流健康状态"""
        logger.info("健康检查循环启动")
        check_count = 0
        while running_checker():
            try:
                await asyncio.sleep(_HEALTH_CHECK_INTERVAL)
                now = time.time()
                check_count += 1
                unhealthy = []
                healthy_count = 0
                # 诊断：按间隔分桶统计
                gap_buckets = {"<10s": 0, "10-30s": 0, "30-60s": 0, "60-120s": 0, ">120s": 0, "无数据": 0}

                for stock_code in stocks_getter():
                    last = last_data_time_getter(stock_code)
                    if last is None:
                        last = 0.0
                    gap = now - last

                    # 分桶统计
                    if last == 0.0:
                        gap_buckets["无数据"] += 1
                    elif gap < 10:
                        gap_buckets["<10s"] += 1
                    elif gap < 30:
                        gap_buckets["10-30s"] += 1
                    elif gap < 60:
                        gap_buckets["30-60s"] += 1
                    elif gap < 120:
                        gap_buckets["60-120s"] += 1
                    else:
                        gap_buckets[">120s"] += 1

                    if gap > _DATA_TIMEOUT:
                        unhealthy.append(stock_code)
                        fail_count = (
                            self._health_fail_counts.get(stock_code, 0) + 1
                        )
                        self._health_fail_counts[stock_code] = fail_count

                        # 子进程模式：不检查订阅状态（子进程的 subscription_manager 是空的）
                        is_subprocess = self._engine._subscription_helper is None

                        if is_subprocess:
                            # 子进程仅在首次和每 _HEALTH_FAIL_THRESHOLD 次时告警，避免刷屏
                            if fail_count == 1 or fail_count % _HEALTH_FAIL_THRESHOLD == 0:
                                logger.warning(
                                    f"[健康检查] {stock_code} 超过 {_DATA_TIMEOUT:.0f}秒 无数据 "
                                    f"(间隔: {gap:.0f}秒, 连续{fail_count}次)"
                                )
                        else:
                            # 主进程模式：检查订阅状态
                            is_ticker_subscribed = (
                                stock_code
                                in self._subscription_manager.ticker_subscribed_stocks
                            )
                            is_orderbook_subscribed = (
                                stock_code
                                in self._subscription_manager.orderbook_subscribed_stocks
                            )

                            logger.warning(
                                f"[健康检查] {stock_code} 超过 {_DATA_TIMEOUT}秒 无数据 "
                                f"(最后数据时间: {last:.1f}, 当前时间: {now:.1f}, 间隔: {gap:.1f}秒)"
                            )
                            logger.info(
                                f"[订阅状态] {stock_code} - TICKER: {is_ticker_subscribed}, ORDER_BOOK: {is_orderbook_subscribed}"
                            )

                            if not is_ticker_subscribed or not is_orderbook_subscribed:
                                logger.warning(
                                    f"[诊断结果] {stock_code} 订阅状态异常，尝试重新订阅"
                                )
                            else:
                                logger.warning(
                                    f"[诊断结果] {stock_code} 已订阅但无数据 (失败次数: {fail_count}/{_HEALTH_FAIL_THRESHOLD}) "
                                    f"(可能原因: 停牌/休市/API限流/市场无成交)"
                                )

                                if fail_count >= _HEALTH_FAIL_THRESHOLD:
                                    logger.error(
                                        f"[严重警告] {stock_code} 连续 {fail_count} 次健康检查失败，建议人工检查: "
                                        f"1. 股票是否停牌？ 2. 市场是否休市？ 3. API 是否限流？"
                                    )

                            # 控制台告警
                            print_status(
                                f"【Scalping告警】[{stock_code}] 已 {gap:.0f}秒无数据！"
                                f"(连续{fail_count}次失败)",
                                "warn",
                            )
                    else:
                        # 恢复健康，重置计数
                        healthy_count += 1
                        self._health_fail_counts[stock_code] = 0

                # 每次健康检查输出诊断摘要
                total = healthy_count + len(unhealthy)
                bucket_str = " ".join(f"{k}:{v}" for k, v in gap_buckets.items() if v > 0)
                logger.info(
                    f"[健康诊断] 第{check_count}次 | "
                    f"总计:{total}只 健康:{healthy_count} 超时:{len(unhealthy)} | "
                    f"间隔分布: {bucket_str}"
                )

                if unhealthy:
                    logger.warning(f"数据流不健康的股票: {unhealthy}")

                    # 连续3次健康检查失败，自动触发重新订阅（仅主进程模式）
                    is_subprocess = self._engine._subscription_helper is None
                    if not is_subprocess:
                        resubscribe_stocks = [
                            code
                            for code in unhealthy
                            if self._health_fail_counts.get(code, 0)
                            >= _HEALTH_FAIL_THRESHOLD
                        ]
                        if resubscribe_stocks:
                            print_status(
                                f"【Scalping告警】{len(resubscribe_stocks)}只股票连续"
                                f"{_HEALTH_FAIL_THRESHOLD}次健康检查失败，触发重新订阅: "
                                f"{resubscribe_stocks[:5]}",
                                "error",
                            )
                            for code in resubscribe_stocks:
                                self._health_fail_counts[code] = 0
                            asyncio.create_task(
                                self._batch_reconnect(resubscribe_stocks)
                            )

                    try:
                        from simple_trade.websocket.events import SocketEvent

                        await self._engine._socket_manager.emit_to_all(
                            SocketEvent.ERROR,
                            {
                                "error": f"Scalping 数据流超时: {unhealthy}",
                                "code": "SCALPING_DATA_TIMEOUT",
                                "stock_codes": unhealthy,
                            },
                        )
                    except Exception as e:
                        logger.debug(f"推送健康告警失败: {e}")

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"健康检查异常: {e}")

    async def _batch_reconnect(self, stock_codes: list[str]) -> None:
        """批量重连：一次性订阅所有掉线的股票（比逐只重连快得多）"""
        e = self._engine
        if e._subscription_helper is None:
            logger.info("批量重连跳过（子进程模式）")
            return

        logger.info(f"[批量重连] 开始批量订阅 {len(stock_codes)} 只股票")
        try:
            # 设置所有需要重连的股票为优先订阅
            e._subscription_helper.set_priority_stocks(stock_codes)
            # 一次性批量订阅（而不是逐只轮询）
            loop = asyncio.get_running_loop()
            sub_result = await loop.run_in_executor(
                None, e._subscription_helper.subscribe_target_stocks, None
            )
            logger.info(f"[批量重连] 批量订阅完成: {sub_result}")

            # 重置所有重连计数和数据时间
            now = time.time()
            for code in stock_codes:
                self._engine._lifecycle._reconnect_attempts[code] = 0
                self._engine._lifecycle._last_data_time[code] = now

            print_status(
                f"【Scalping重连】批量订阅 {len(stock_codes)} 只股票完成",
                "ok",
            )
        except Exception as exc:
            logger.error(f"[批量重连] 批量订阅失败: {exc}，降级为逐只重连")
            # 降级：逐只重连
            success_count = 0
            fail_count = 0
            for code in stock_codes:
                try:
                    await self._engine._reconnect(code)
                    success_count += 1
                except Exception:
                    fail_count += 1
            logger.info(
                f"[批量重连] 降级逐只重连完成: 成功 {success_count}, 失败 {fail_count}"
            )

    async def _run_pattern_detection(self, stock_code: str) -> None:
        """运行行为模式检测 + 行动评分"""
        e = self._engine
        if not hasattr(e, '_pattern_detector') or e._pattern_detector is None:
            return

        # 收集 Delta 历史
        delta_history = e._delta_calculator.get_recent_deltas(stock_code, 20)
        if len(delta_history) < 4:
            return

        # 收集环境数据
        poc_price = None
        vol_profile = e._poc_calculator.get_volume_profile(stock_code)
        if vol_profile:
            poc_price = max(vol_profile, key=vol_profile.get)

        support_prices = []
        resistance_prices = []
        levels = e._spoofing_filter.get_active_levels(stock_code)
        if levels:
            for lv in levels:
                lv_side = getattr(lv, "side", None)
                lv_price = getattr(lv, "price", 0)
                # PriceLevelSide.ASK = 阻力（卖方挂单）, BID = 支撑（买方挂单）
                side_str = str(lv_side).upper() if lv_side else ""
                if "ASK" in side_str or "RESISTANCE" in side_str:
                    resistance_prices.append(lv_price)
                elif "BID" in side_str or "SUPPORT" in side_str:
                    support_prices.append(lv_price)

        vwap_value = getattr(e._vwap_guard, '_last_vwap', {}).get(stock_code)

        # 运行模式检测
        alerts = e._pattern_detector.detect(
            stock_code=stock_code,
            delta_history=delta_history,
            poc_price=poc_price,
            support_prices=support_prices or None,
            vwap_value=vwap_value,
        )

        # 推送模式预警
        from simple_trade.websocket.events import SocketEvent
        for alert in alerts:
            try:
                await e._socket_manager.emit_to_all(
                    SocketEvent.PATTERN_ALERT, alert.to_dict()
                )
                logger.info(f"[{stock_code}] 模式预警: {alert.title} - {alert.description}")
            except Exception:
                pass
            if e._persistence:
                e._persistence.enqueue_event("pattern_alert", alert.to_dict())

        # 运行行动评分
        if hasattr(e, '_action_scorer') and e._action_scorer:
            current_price = delta_history[-1].close_price if hasattr(delta_history[-1], 'close_price') else 0
            delta_sum = sum(
                d.delta if hasattr(d, 'delta') else d.get('delta', 0)
                for d in delta_history[-3:]
            )
            ofi = None
            if hasattr(e, '_ofi_calculator') and e._ofi_calculator:
                ofi = e._ofi_calculator.get_current_ofi()

            signals = e._action_scorer.evaluate(
                stock_code=stock_code,
                pattern_alerts=alerts,
                current_price=current_price,
                delta_recent_sum=delta_sum,
                vwap_value=vwap_value,
                poc_price=poc_price,
                support_prices=support_prices or None,
                resistance_prices=resistance_prices or None,
                ofi_value=ofi,
            )

            for sig in signals:
                try:
                    await e._socket_manager.emit_to_all(
                        SocketEvent.ACTION_SIGNAL, sig.to_dict()
                    )
                    logger.info(
                        f"[{stock_code}] 行动信号: {sig.action} "
                        f"得分={sig.score:.1f} ({sig.level})"
                    )
                except Exception:
                    pass
                if e._persistence:
                    e._persistence.enqueue_event("action_signal", sig.to_dict())

