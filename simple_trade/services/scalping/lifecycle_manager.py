"""
生命周期管理器 - 管理 ScalpingEngine 的启动、停止、重连逻辑。

从 engine.py 中提取，负责：
- start() 方法（换手率筛选、订阅、持久化恢复、调度器启动）
- stop() 方法（取消订阅、清理资源）
- _reconnect() 方法（断线重连）
- 运行状态管理
"""

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Optional

from simple_trade.utils.logger import print_status
from simple_trade.websocket.events import SocketEvent

if TYPE_CHECKING:
    from simple_trade.services.scalping.central_scheduler import CentralScheduler
    from simple_trade.services.scalping.data_poller import ScalpingDataPoller
    from simple_trade.services.scalping.engine import ScalpingEngine

logger = logging.getLogger("scalping")

# 重连参数
_RECONNECT_DELAY_SEC = 5.0
_MAX_RECONNECT_ATTEMPTS = 3


class LifecycleManager:
    """ScalpingEngine 生命周期管理器

    管理股票的启动/停止/重连，维护运行状态字典。
    """

    def __init__(self, engine: "ScalpingEngine"):
        self._engine = engine
        # 运行状态
        self._active_stocks: set[str] = set()
        self._day_highs: dict[str, float] = {}
        self._reconnect_attempts: dict[str, int] = {}
        self._last_data_time: dict[str, float] = {}

    # ------------------------------------------------------------------
    # 属性代理
    # ------------------------------------------------------------------

    @property
    def active_stocks(self) -> set[str]:
        return set(self._active_stocks)

    @property
    def day_highs(self) -> dict[str, float]:
        return dict(self._day_highs)

    def update_day_high(self, stock_code: str, price: float) -> None:
        """更新日内最高价"""
        current_high = self._day_highs.get(stock_code, 0.0)
        if price > current_high:
            self._day_highs[stock_code] = price

    def record_data_received(self, stock_code: str) -> None:
        """记录收到数据时间并重置重连计数"""
        self._reconnect_attempts[stock_code] = 0
        self._last_data_time[stock_code] = time.time()

    def is_active(self, stock_code: str) -> bool:
        return stock_code in self._active_stocks

    # ------------------------------------------------------------------
    # 启动
    # ------------------------------------------------------------------

    async def start(
        self,
        stock_codes: list[str],
        turnover_rates: dict[str, float] | None = None,
    ) -> "StartResult":
        """启动指定股票的 Scalping 数据流"""
        from simple_trade.services.scalping.engine import StartResult

        e = self._engine
        result = StartResult()

        # 1. 换手率筛选
        candidates = []
        for code in stock_codes:
            if turnover_rates and code in turnover_rates:
                rate = turnover_rates[code]
                if rate < e.MIN_TURNOVER_RATE:
                    result.filtered.append(code)
                    logger.info(
                        f"[{code}] 换手率 {rate:.2f}% < {e.MIN_TURNOVER_RATE}%，已过滤"
                    )
                    continue
            candidates.append(code)

        # 2. 分离新增和已存在
        for code in candidates:
            if code in self._active_stocks:
                result.existing.append(code)
            else:
                result.added.append(code)

        # 3. 数量上限检查
        total_after = len(self._active_stocks) + len(result.added)
        if total_after > e.MAX_STOCKS:
            result.rejected_reason = (
                f"超过最大监控数量限制: 当前 {len(self._active_stocks)} + "
                f"新增 {len(result.added)} = {total_after} > {e.MAX_STOCKS}"
            )
            logger.warning(result.rejected_reason)
            result.added.clear()
            return result

        if not result.added:
            logger.info("无新增股票需要启动")
            return result

        # 3.5 启动持久化服务（但不阻塞恢复数据）
        if e._persistence is not None:
            try:
                await e._persistence.start()
            except Exception as exc:
                logger.error(f"持久化服务启动失败: {exc}")

        # 4. 订阅管理（进程模式下 subscription_helper 为 None，订阅在 scalping_worker.py 中处理）
        try:
            if e._subscription_helper is not None:
                e._subscription_helper.set_priority_stocks(result.added)
                sub_result = e._subscription_helper.subscribe_target_stocks(None)
                logger.info(f"订阅结果: {sub_result}")

                # 等待订阅状态同步（最多 5 秒）
                if hasattr(e, '_subscription_manager') and e._subscription_manager:
                    for _ in range(50):
                        if e._subscription_manager.ticker_subscribed_stocks:
                            logger.info("订阅状态已同步")
                            break
                        await asyncio.sleep(0.1)
                    else:
                        logger.warning("订阅状态同步超时，但继续启动")
            else:
                logger.info("订阅管理跳过（子进程模式，TICKER/ORDER_BOOK 已在 worker 中订阅）")

        except Exception as exc:
            logger.error(f"订阅失败: {exc}")
            result.rejected_reason = f"订阅失败: {exc}"
            result.added.clear()
            return result

        # 5. 加入监控
        for code in result.added:
            self._active_stocks.add(code)
            self._reconnect_attempts[code] = 0
            self._last_data_time[code] = time.time()
            e._dispatcher.add_stock(code)
            logger.info(f"已启动 {code} 的 Scalping 数据流")

        # 控制台打印启动的股票列表
        print_status(
            f"【Scalping】已启动 {len(result.added)} 只股票: "
            f"{result.added[:10]}{'...' if len(result.added) > 10 else ''}",
            "ok"
        )
        if result.filtered:
            print_status(
                f"【Scalping】已过滤 {len(result.filtered)} 只低换手股: {result.filtered[:5]}",
                "info"
            )
        if result.existing:
            print_status(
                f"【Scalping】已存在 {len(result.existing)} 只: {result.existing[:5]}",
                "info"
            )

        # 6. 启动调度器
        if e._scheduler is not None:
            if not e._scheduler._running:
                await e._scheduler.start()

            # 始终使用 result.added 中已有 TICKER 订阅的股票加入调度器
            # （未订阅 TICKER 的股票轮询 get_rt_ticker 会失败，
            #   导致健康检查误报 + 重连风暴冲击 OpenD）
            stocks_to_add = result.added
            if hasattr(e, '_subscription_manager') and e._subscription_manager:
                ticker_subs = e._subscription_manager.ticker_subscribed_stocks
                if ticker_subs:
                    stocks_to_add = [c for c in result.added if c in ticker_subs]
                    skipped = len(result.added) - len(stocks_to_add)
                    if skipped > 0:
                        logger.info(
                            f"【Scalping】跳过 {skipped} 只未订阅TICKER的股票，"
                            f"仅监控 {len(stocks_to_add)} 只已订阅股票"
                        )
                logger.info(
                    f"【Scalping】加入调度器 {len(stocks_to_add)} 只股票"
                    f"（TICKER 订阅覆盖: {len(ticker_subs) if ticker_subs else 0}/{len(result.added)}）"
                )

            if stocks_to_add:
                await e._scheduler.add_stocks(stocks_to_add)
        elif e._data_poller is not None:
            for code in result.added:
                await e._data_poller.start(code)

        # 7. 恢复历史数据（在调度器启动后，使用后台任务不阻塞实时数据接收）
        if e._persistence is not None and result.added:
            asyncio.create_task(
                self._restore_data_background(result.added)
            )
            logger.info(f"【Scalping】后台任务: 恢复 {len(result.added)} 只股票的历史数据")

        return result

    async def _restore_data_background(self, stock_codes: list[str]) -> None:
        """后台恢复历史数据"""
        try:
            e = self._engine
            await e._persistence.restore_today_data(
                stock_codes=stock_codes,
                delta_calculator=e._delta_calculator,
                poc_calculator=e._poc_calculator,
                spoofing_filter=e._spoofing_filter,
                socket_manager=e._socket_manager,
            )
            logger.info(f"【Scalping】历史数据恢复完成: {len(stock_codes)} 只股票")
        except Exception as exc:
            logger.error(f"历史数据恢复失败: {exc}")

    # ------------------------------------------------------------------
    # 停止
    # ------------------------------------------------------------------

    async def stop(self, stock_codes: list[str] | None = None) -> None:
        """停止指定股票（或全部）的 Scalping 数据流"""
        e = self._engine
        codes_to_stop = (
            list(self._active_stocks) if stock_codes is None else stock_codes
        )

        # 先从调度器移除
        if e._scheduler is not None and codes_to_stop:
            await e._scheduler.remove_stocks(codes_to_stop)
        elif e._data_poller is not None:
            for code in codes_to_stop:
                await e._data_poller.stop(code)

        for code in codes_to_stop:
            self._active_stocks.discard(code)
            self._day_highs.pop(code, None)
            e._calc_scheduler.remove_stock(code)
            self._reconnect_attempts.pop(code, None)
            self._last_data_time.pop(code, None)
            e._dispatcher.remove_stock(code)
            # 重置各计算器状态
            e._delta_calculator.reset(code)
            e._tape_velocity.reset(code)
            e._spoofing_filter.reset(code)
            e._poc_calculator.reset(code)
            e._signal_engine.reset(code)
            if e._divergence_detector:
                e._divergence_detector.reset(code)
            if e._vwap_guard:
                e._vwap_guard.reset(code)
            if e._stop_loss_monitor:
                e._stop_loss_monitor.reset(code)
            if e._tick_credibility_filter:
                e._tick_credibility_filter.reset(code)
            logger.info(f"已停止 {code} 的 Scalping 数据流")

        if not self._active_stocks:
            if e._scheduler is not None:
                await e._scheduler.stop()
            if e._subscription_helper is not None:
                try:
                    e._subscription_helper.unsubscribe_all()
                except Exception as exc:
                    logger.warning(f"取消订阅失败: {exc}")
            if e._persistence is not None:
                try:
                    await e._persistence.stop()
                except Exception as exc:
                    logger.error(f"持久化服务停止失败: {exc}")

    # ------------------------------------------------------------------
    # 重连
    # ------------------------------------------------------------------

    async def reconnect(self, stock_code: str) -> None:
        """断线重连：5 秒间隔，最多 3 次，失败推送告警"""
        e = self._engine
        attempts = self._reconnect_attempts.get(stock_code, 0)

        while attempts < _MAX_RECONNECT_ATTEMPTS:
            attempts += 1
            self._reconnect_attempts[stock_code] = attempts
            print_status(
                f"【Scalping重连】[{stock_code}] 尝试重连 ({attempts}/{_MAX_RECONNECT_ATTEMPTS})",
                "warn"
            )

            await asyncio.sleep(_RECONNECT_DELAY_SEC)

            try:
                if e._subscription_helper is None:
                    logger.info(f"[{stock_code}] 重连跳过订阅（子进程模式）")
                    return
                e._subscription_helper.set_priority_stocks([stock_code])
                # subscribe_target_stocks 是同步阻塞的 Futu API 调用，
                # 使用 run_in_executor 避免阻塞事件循环
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None, e._subscription_helper.subscribe_target_stocks, None
                )
                print_status(f"【Scalping重连】[{stock_code}] 重连成功", "ok")
                self._reconnect_attempts[stock_code] = 0
                return
            except Exception as exc:
                print_status(
                    f"【Scalping重连】[{stock_code}] 重连失败: {type(exc).__name__}: {exc}",
                    "error"
                )

        # 3 次全部失败，推送告警
        print_status(
            f"【Scalping重连】[{stock_code}] 重连 {_MAX_RECONNECT_ATTEMPTS} 次均失败！",
            "error"
        )
        try:
            await e._socket_manager.emit_to_all(
                SocketEvent.ERROR,
                {
                    "error": f"Scalping 数据流断开: {stock_code}",
                    "code": "SCALPING_DISCONNECT",
                    "stock_code": stock_code,
                    "attempts": _MAX_RECONNECT_ATTEMPTS,
                },
            )
        except Exception as exc:
            logger.error(f"[{stock_code}] 推送告警失败: {exc}")

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """返回引擎状态"""
        now = time.time()
        stocks_status = {}
        for code in self._active_stocks:
            last_data = self._last_data_time.get(code)
            healthy = last_data is not None and (now - last_data) < 60.0
            stocks_status[code] = {
                "last_data_time": last_data,
                "healthy": healthy,
                "seconds_since_data": (
                    round(now - last_data, 1) if last_data else None
                ),
            }
        return {
            "active_count": len(self._active_stocks),
            "max_stocks": self._engine.MAX_STOCKS,
            "stocks": stocks_status,
            "scheduler_running": (
                self._engine._scheduler is not None
                and self._engine._scheduler._running
            ),
        }
