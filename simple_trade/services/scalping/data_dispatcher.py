"""
数据分发器 - 处理 Tick/OrderBook 数据回调并分发给各计算器。

从 engine.py 中提取，负责：
- on_tick() 回调处理（清洗 → 分发 → 信号评估）
- on_order_book() 回调处理
- 数据接收汇总统计（每10秒控制台打印）
"""

import logging
import time
from typing import TYPE_CHECKING

from simple_trade.services.scalping.models import OrderBookData, TickData
from simple_trade.utils.logger import print_status

if TYPE_CHECKING:
    from simple_trade.services.scalping.engine import ScalpingEngine

logger = logging.getLogger("scalping")

# 控制台汇总打印间隔（秒）
_TICK_SUMMARY_INTERVAL = 10.0


class DataDispatcher:
    """数据分发器 - 接收 Tick/OrderBook 并分发给各计算器和检测器"""

    def __init__(self, engine: "ScalpingEngine"):
        self._engine = engine
        # 控制台汇总统计
        self._tick_counts: dict[str, int] = {}
        self._ob_counts: dict[str, int] = {}
        self._last_summary_time: float = 0.0

    # ------------------------------------------------------------------
    # Tick 数据回调
    # ------------------------------------------------------------------

    async def on_tick(self, stock_code: str, tick: TickData) -> None:
        """Tick 数据回调：验证 → 清洗 → 分发 → 信号评估 → 定期 POC/Delta"""
        e = self._engine
        lm = e._lifecycle

        if not lm.is_active(stock_code):
            logging.debug(f"[数据验证] {stock_code} 不在活跃列表中，跳过处理")
            return

        # 数据有效性检查
        if not tick:
            logging.warning(f"[数据验证] {stock_code} Tick 数据为 None")
            return

        if not hasattr(tick, 'timestamp') or not hasattr(tick, 'price'):
            logging.warning(
                f"[数据验证] {stock_code} Tick 数据缺少必要字段 "
                f"(has_timestamp: {hasattr(tick, 'timestamp')}, has_price: {hasattr(tick, 'price')})"
            )
            return

        # 价格合理性检查
        if tick.price <= 0 or tick.volume <= 0:
            logging.warning(
                f"[数据验证] {stock_code} Tick 数据异常 "
                f"(price: {tick.price}, volume: {tick.volume}, time: {getattr(tick, 'time', 'N/A')})"
            )
            return

        # 重置重连计数（收到数据说明连接正常）
        lm.record_data_received(stock_code)

        # 汇总统计
        self._tick_counts[stock_code] = self._tick_counts.get(stock_code, 0) + 1

        # 每 100 条数据输出一次统计
        if self._tick_counts[stock_code] % 100 == 0:
            logging.info(
                f"[数据统计] {stock_code} 已接收 {self._tick_counts[stock_code]} 条 Tick 数据 "
                f"(最新价格: {tick.price}, 成交量: {tick.volume})"
            )

        self._maybe_print_summary()

        # 1. TickCredibilityFilter 清洗
        if e._tick_credibility_filter is not None:
            try:
                should_dispatch, _is_outlier = (
                    e._tick_credibility_filter.filter_tick(stock_code, tick)
                )
                if not should_dispatch:
                    return
            except Exception as exc:
                logger.warning(
                    f"[{stock_code}] TickCredibilityFilter 异常: {exc}"
                )

        # 2. 分发至核心计算器（同步方法）
        direction = None
        try:
            direction = e._delta_calculator.on_tick(stock_code, tick)
        except Exception as exc:
            logger.warning(f"[{stock_code}] DeltaCalculator 异常: {exc}")

        try:
            e._tape_velocity.on_tick(stock_code, tick)
        except Exception as exc:
            logger.warning(f"[{stock_code}] TapeVelocityMonitor 异常: {exc}")

        try:
            e._poc_calculator.on_tick(stock_code, tick, direction=direction)
        except Exception as exc:
            logger.warning(f"[{stock_code}] POCCalculator 异常: {exc}")

        # 分发至可选组件
        if e._divergence_detector is not None:
            try:
                e._divergence_detector.on_tick(stock_code, tick)
            except Exception as exc:
                logger.warning(
                    f"[{stock_code}] DivergenceDetector 异常: {exc}"
                )

        if e._breakout_monitor is not None:
            try:
                e._breakout_monitor.on_tick(stock_code, tick)
            except Exception as exc:
                logger.warning(
                    f"[{stock_code}] BreakoutMonitor 异常: {exc}"
                )

        if e._vwap_guard is not None:
            try:
                await e._vwap_guard.on_tick_async(stock_code, tick)
            except Exception as exc:
                logger.warning(f"[{stock_code}] VwapGuard 异常: {exc}")

        if e._stop_loss_monitor is not None:
            try:
                e._stop_loss_monitor.on_tick(stock_code, tick)
            except Exception as exc:
                logger.warning(
                    f"[{stock_code}] StopLossMonitor 异常: {exc}"
                )

        # 3. 更新日内高点 & 记录价格
        lm.update_day_high(stock_code, tick.price)
        e._signal_engine.record_price(
            stock_code, tick.price, tick.timestamp / 1000.0
        )

        # 4. 检测动能点火 & 评估信号
        try:
            await e._tape_velocity.check_ignition(stock_code)
        except Exception as exc:
            logger.warning(f"[{stock_code}] check_ignition 异常: {exc}")

        await self._evaluate_signals(stock_code, tick.price)

        # 5. 定期计算 POC 和 flush Delta
        # 有 scheduler 或 data_poller 时由其定时任务负责（墙钟驱动）
        # 无调度器时（测试场景）在 tick 回调中用 tick 时间戳驱动
        if e._scheduler is None and e._data_poller is None:
            tick_sec = tick.timestamp / 1000.0
            await e._calc_scheduler.maybe_calc_poc(stock_code, tick_sec)
            await e._calc_scheduler.maybe_flush_delta(stock_code, tick_sec)

    # ------------------------------------------------------------------
    # OrderBook 数据回调
    # ------------------------------------------------------------------

    async def on_order_book(
        self, stock_code: str, order_book: OrderBookData
    ) -> None:
        """OrderBook 数据回调，分发至 SpoofingFilter"""
        if not self._engine._lifecycle.is_active(stock_code):
            return

        self._ob_counts[stock_code] = self._ob_counts.get(stock_code, 0) + 1

        try:
            await self._engine._spoofing_filter.on_order_book(
                stock_code, order_book
            )
        except Exception as exc:
            logger.warning(f"[{stock_code}] SpoofingFilter 异常: {exc}")

    # ------------------------------------------------------------------
    # 信号评估
    # ------------------------------------------------------------------

    async def _evaluate_signals(
        self, stock_code: str, current_price: float
    ) -> None:
        """评估突破追多和支撑低吸信号"""
        e = self._engine
        day_high = e._lifecycle._day_highs.get(stock_code, current_price)

        try:
            await e._signal_engine.evaluate_breakout(
                stock_code, current_price, day_high
            )
        except Exception as exc:
            logger.warning(f"[{stock_code}] evaluate_breakout 异常: {exc}")

        try:
            await e._signal_engine.evaluate_support_bounce(
                stock_code, current_price
            )
        except Exception as exc:
            logger.warning(
                f"[{stock_code}] evaluate_support_bounce 异常: {exc}"
            )

    # ------------------------------------------------------------------
    # 汇总统计
    # ------------------------------------------------------------------

    def _maybe_print_summary(self) -> None:
        """每 _TICK_SUMMARY_INTERVAL 秒汇总打印一次 Tick/OrderBook 接收统计"""
        now = time.time()
        if now - self._last_summary_time < _TICK_SUMMARY_INTERVAL:
            return
        self._last_summary_time = now

        total_ticks = sum(self._tick_counts.values())
        total_obs = sum(self._ob_counts.values())
        stock_count = len(self._engine._lifecycle._active_stocks)

        if total_ticks == 0 and total_obs == 0:
            return

        # 找出收到数据最多的前3只
        top_stocks = sorted(
            self._tick_counts.items(), key=lambda x: x[1], reverse=True
        )[:3]
        top_str = ", ".join(
            f"{code}:{cnt}" for code, cnt in top_stocks
        )

        print_status(
            f"【Scalping数据】{stock_count}只股票 | "
            f"Tick:{total_ticks} OB:{total_obs} | "
            f"Top: {top_str}",
            "info"
        )

        # 重置计数
        active = self._engine._lifecycle._active_stocks
        self._tick_counts = {code: 0 for code in active}
        self._ob_counts = {code: 0 for code in active}
