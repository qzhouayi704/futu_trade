"""
Scalping 数据持久化服务

负责将 Scalping 引擎的计算数据异步批量写入 SQLite，
并在引擎启动时从数据库恢复当日数据到各计算器内存。
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from simple_trade.services.scalping.calculators.poc_calculator import _VolumeBin
from simple_trade.services.scalping.models import (
    DeltaUpdateData,
    OrderBookData,
    PriceLevelAction,
    PriceLevelData,
    PriceLevelSide,
    ScalpingSignalData,
    TickData,
)
from simple_trade.websocket.events import SocketEvent

if TYPE_CHECKING:
    from simple_trade.database.core.db_manager import DatabaseManager

logger = logging.getLogger(__name__)

# flush 间隔（秒）
FLUSH_INTERVAL = 5
# 逐笔数据每次 INSERT 的最大行数（避免长时间占用 write_queue worker）
_TICKER_CHUNK_SIZE = 500
# 逐笔数据队列上限（超过后丢弃最旧数据，防止内存无限增长）
_TICKER_QUEUE_MAX = 50000


class ScalpingPersistence:
    """Scalping 数据持久化服务

    通过内存队列 + 后台定时 flush 实现异步批量写入，
    不阻塞实时计算主循环。
    """

    def __init__(self, db_manager: DatabaseManager) -> None:
        self._db_manager = db_manager
        # 5 个内存队列（新增 ticker_queue）
        self._signal_queue: list[tuple] = []
        self._delta_queue: list[tuple] = []
        self._poc_queue: list[tuple] = []
        self._level_queue: list[tuple] = []
        self._ticker_queue: list[tuple] = []
        self._event_queue: list[tuple] = []
        # 后台任务
        self._flush_task: asyncio.Task | None = None
        self._running = False

    # ================================================================
    # 生命周期
    # ================================================================

    async def start(self) -> None:
        """启动后台 flush 定时任务"""
        if self._running:
            return
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())

        # 启动时清理旧数据（后台任务，不阻塞启动）
        asyncio.create_task(self._cleanup_old_data_background())

        logger.info("ScalpingPersistence 已启动，flush 间隔 %ds（后台清理进行中）", FLUSH_INTERVAL)

    async def _cleanup_old_data_background(self) -> None:
        """后台清理旧数据任务"""
        try:
            await self.cleanup_old_data()
            logger.info("后台数据清理完成")
        except Exception as e:
            logger.error(f"后台数据清理失败: {e}")

    async def stop(self) -> None:
        """执行最终 flush，取消后台任务"""
        self._running = False
        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None
        # 最终 flush
        await self.flush()
        logger.info("ScalpingPersistence 已停止")

    # ================================================================
    # 入队方法（纯内存操作，零 I/O）
    # ================================================================

    def enqueue_signal(self, signal: ScalpingSignalData) -> None:
        """入队交易信号"""
        trade_date = datetime.now().strftime("%Y-%m-%d")
        self._signal_queue.append((
            signal.stock_code,
            signal.signal_type.value,
            signal.trigger_price,
            signal.support_price,
            json.dumps(signal.conditions, ensure_ascii=False),
            trade_date,
        ))

    def enqueue_delta(self, delta: DeltaUpdateData) -> None:
        """入队 Delta 记录"""
        trade_date = datetime.now().strftime("%Y-%m-%d")
        self._delta_queue.append((
            delta.stock_code,
            delta.delta,
            delta.volume,
            delta.period_seconds,
            trade_date,
        ))

    def enqueue_poc(
        self,
        stock_code: str,
        poc_price: float,
        volume_profile: dict[str, int],
    ) -> None:
        """入队 POC 快照"""
        trade_date = datetime.now().strftime("%Y-%m-%d")
        self._poc_queue.append((
            stock_code,
            poc_price,
            json.dumps(volume_profile, ensure_ascii=False),
            trade_date,
        ))

    def enqueue_price_level(self, level: PriceLevelData) -> None:
        """入队阻力/支撑线事件"""
        trade_date = datetime.now().strftime("%Y-%m-%d")
        self._level_queue.append((
            level.stock_code,
            level.price,
            level.volume,
            level.side.value,
            level.action.value,
            trade_date,
        ))

    def enqueue_ticker(self, tick: TickData) -> None:
        """入队逐笔成交数据"""
        # 队列上限保护：超过阈值时丢弃最旧的 10% 数据
        if len(self._ticker_queue) >= _TICKER_QUEUE_MAX:
            drop_count = _TICKER_QUEUE_MAX // 10
            self._ticker_queue = self._ticker_queue[drop_count:]
            logger.warning(
                "逐笔数据队列溢出，丢弃最旧 %d 条（剩余 %d 条）",
                drop_count, len(self._ticker_queue),
            )
        trade_date = datetime.now().strftime("%Y-%m-%d")
        self._ticker_queue.append((
            tick.stock_code,
            tick.price,
            tick.volume,
            tick.price * tick.volume,  # turnover
            tick.direction.name,
            int(tick.timestamp),
            trade_date,
        ))

    def enqueue_event(self, event_type: str, data: dict) -> None:
        """入队交易事件（诱多/诱空、假突破、动能点火等）"""
        stock_code = data.get("stock_code", "")
        trade_date = datetime.now().strftime("%Y-%m-%d")
        self._event_queue.append((
            stock_code,
            event_type,
            json.dumps(data, ensure_ascii=False, default=str),
            trade_date,
        ))

    # ================================================================
    # 批量写入
    # ================================================================

    async def flush(self) -> None:
        """将所有队列数据批量写入数据库"""
        # 交换队列引用（CPython GIL 保证原子性）
        signal_batch = self._signal_queue
        self._signal_queue = []
        delta_batch = self._delta_queue
        self._delta_queue = []
        poc_batch = self._poc_queue
        self._poc_queue = []
        level_batch = self._level_queue
        self._level_queue = []
        ticker_batch = self._ticker_queue
        self._ticker_queue = []
        event_batch = self._event_queue
        self._event_queue = []

        await self._flush_signals(signal_batch)
        await self._flush_deltas(delta_batch)
        await self._flush_pocs(poc_batch)
        await self._flush_levels(level_batch)
        await self._flush_tickers(ticker_batch)
        await self._flush_events(event_batch)

    async def _flush_signals(self, batch: list[tuple]) -> None:
        if not batch:
            return
        try:
            future = self._db_manager.write_queue.submit(
                self._db_manager.execute_many,
                "INSERT INTO scalping_signals "
                "(stock_code, signal_type, trigger_price, support_price, conditions, trade_date) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                batch,
            )
            await asyncio.wait_for(
                asyncio.to_thread(future.result),
                timeout=20.0
            )
        except Exception as e:
            logger.error("Scalping 信号 flush 失败: %s", e, exc_info=True)

    async def _flush_deltas(self, batch: list[tuple]) -> None:
        if not batch:
            return
        try:
            future = self._db_manager.write_queue.submit(
                self._db_manager.execute_many,
                "INSERT INTO scalping_delta_history "
                "(stock_code, delta, volume, period_seconds, trade_date) "
                "VALUES (?, ?, ?, ?, ?)",
                batch,
            )
            await asyncio.wait_for(
                asyncio.to_thread(future.result),
                timeout=20.0
            )
        except Exception as e:
            logger.error("Scalping Delta flush 失败: %s", e, exc_info=True)

    async def _flush_pocs(self, batch: list[tuple]) -> None:
        if not batch:
            return
        try:
            future = self._db_manager.write_queue.submit(
                self._db_manager.execute_many,
                "INSERT OR REPLACE INTO scalping_poc_snapshot "
                "(stock_code, poc_price, volume_profile, trade_date, updated_at) "
                "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
                batch,
            )
            await asyncio.wait_for(
                asyncio.to_thread(future.result),
                timeout=20.0
            )
        except Exception as e:
            logger.error("Scalping POC flush 失败: %s", e, exc_info=True)

    async def _flush_levels(self, batch: list[tuple]) -> None:
        if not batch:
            return
        try:
            future = self._db_manager.write_queue.submit(
                self._db_manager.execute_many,
                "INSERT INTO scalping_price_levels "
                "(stock_code, price, volume, side, action, trade_date) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                batch,
            )
            await asyncio.wait_for(
                asyncio.to_thread(future.result),
                timeout=30.0
            )
        except Exception as e:
            logger.warning("Scalping 阻力/支撑线 flush 失败: %s", e)

    async def _flush_tickers(self, batch: list[tuple]) -> None:
        """批量写入逐笔数据（分块写入，避免长时间占用 write_queue）"""
        if not batch:
            return
        sql = (
            "INSERT OR IGNORE INTO ticker_data "
            "(stock_code, price, volume, turnover, direction, timestamp, trade_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)"
        )
        total = len(batch)
        written = 0
        for i in range(0, total, _TICKER_CHUNK_SIZE):
            chunk = batch[i : i + _TICKER_CHUNK_SIZE]
            try:
                future = self._db_manager.write_queue.submit(
                    self._db_manager.execute_many, sql, chunk,
                )
                await asyncio.wait_for(
                    asyncio.to_thread(future.result),
                    timeout=30.0,
                )
                written += len(chunk)
            except asyncio.TimeoutError:
                logger.warning(
                    "逐笔数据 flush 超时（chunk %d-%d / %d），跳过剩余",
                    i, i + len(chunk), total,
                )
                break
            except Exception as e:
                logger.error(
                    "逐笔数据 flush 失败（chunk %d-%d / %d）: %s",
                    i, i + len(chunk), total, e,
                )
        if written > 0 and total > _TICKER_CHUNK_SIZE:
            logger.debug("逐笔数据 flush 完成: %d / %d 条", written, total)

    async def _flush_events(self, batch: list[tuple]) -> None:
        if not batch:
            return
        try:
            future = self._db_manager.write_queue.submit(
                self._db_manager.execute_many,
                "INSERT INTO scalping_events "
                "(stock_code, event_type, event_data, trade_date) "
                "VALUES (?, ?, ?, ?)",
                batch,
            )
            await asyncio.wait_for(
                asyncio.to_thread(future.result),
                timeout=60.0
            )
        except Exception as e:
            logger.error("Scalping 事件 flush 失败: %s", e, exc_info=True)

    # ================================================================
    # 数据恢复（Task 4.1 实现）
    # ================================================================

    async def restore_today_data(
        self,
        stock_codes: list[str],
        delta_calculator=None,
        poc_calculator=None,
        spoofing_filter=None,
        socket_manager=None,
    ) -> None:
        """从数据库恢复当日数据到各计算器内存"""
        if not stock_codes:
            return
        trade_date = datetime.now().strftime("%Y-%m-%d")
        placeholders = ",".join("?" for _ in stock_codes)
        base_params = (*stock_codes, trade_date)

        await self._restore_deltas(placeholders, base_params, delta_calculator)
        await self._restore_poc(placeholders, base_params, poc_calculator)
        await self._restore_levels(placeholders, base_params, spoofing_filter)
        await self._restore_signals(placeholders, base_params, socket_manager)
        await self._restore_events(placeholders, base_params, socket_manager)

    async def get_today_events(self, stock_code: str) -> list[dict]:
        """查询指定股票当日所有交易事件（供快照 API 使用）"""
        trade_date = datetime.now().strftime("%Y-%m-%d")
        try:
            rows = await self._db_manager.async_execute_query(
                "SELECT event_type, event_data, created_at "
                "FROM scalping_events "
                "WHERE stock_code = ? AND trade_date = ? "
                "ORDER BY id ASC",
                (stock_code, trade_date),
            )
            events = []
            for row in rows:
                event = json.loads(row[1])
                event["_event_type"] = row[0]
                event["_created_at"] = row[2]
                events.append(event)
            return events
        except Exception as e:
            logger.error("查询当日事件失败: %s", e)
            return []

    async def _restore_events(
        self, placeholders: str, params: tuple, socket_manager,
    ) -> None:
        """恢复交易事件并推送给前端"""
        if socket_manager is None:
            return
        try:
            rows = await self._db_manager.async_execute_query(
                f"SELECT event_type, event_data "
                f"FROM scalping_events "
                f"WHERE stock_code IN ({placeholders}) AND trade_date = ? "
                f"ORDER BY id ASC",
                params,
            )
            # 事件类型 -> SocketEvent 映射
            event_mapping = {
                "trap_alert": SocketEvent.TRAP_ALERT,
                "fake_breakout": SocketEvent.FAKE_BREAKOUT_ALERT,
                "true_breakout": SocketEvent.TRUE_BREAKOUT_CONFIRM,
                "momentum_ignition": SocketEvent.MOMENTUM_IGNITION,
                "vwap_extension": SocketEvent.VWAP_EXTENSION_ALERT,
                # tick_outlier 使用字符串事件名
            }
            for row in rows:
                event_type_str, event_data_json = row[0], row[1]
                event_data = json.loads(event_data_json)
                socket_event = event_mapping.get(event_type_str)
                if socket_event:
                    try:
                        await socket_manager.emit_to_all(socket_event, event_data)
                    except Exception:
                        pass
                elif event_type_str == "tick_outlier":
                    try:
                        await socket_manager.emit_to_all("tick_outlier", event_data)
                    except Exception:
                        pass
            logger.info("恢复交易事件: %d 条", len(rows))
        except Exception as e:
            logger.error("恢复交易事件失败: %s", e)

    async def _restore_deltas(
        self, placeholders: str, params: tuple, calculator,
    ) -> None:
        """恢复 Delta 历史到 DeltaCalculator"""
        if calculator is None:
            return
        try:
            rows = await self._db_manager.async_execute_query(
                f"SELECT stock_code, delta, volume, period_seconds "
                f"FROM scalping_delta_history "
                f"WHERE stock_code IN ({placeholders}) AND trade_date = ? "
                f"ORDER BY id ASC",
                params,
            )
            for row in rows:
                code, delta, volume, period_sec = row[0], row[1], row[2], row[3]
                state = calculator._get_state(code)
                state.history.append(DeltaUpdateData(
                    stock_code=code,
                    delta=delta,
                    volume=volume,
                    timestamp=datetime.now().isoformat(),
                    period_seconds=period_sec,
                ))
            logger.info("恢复 Delta 历史: %d 条记录", len(rows))
        except Exception as e:
            logger.error("恢复 Delta 历史失败: %s", e)

    async def _restore_poc(
        self, placeholders: str, params: tuple, calculator,
    ) -> None:
        """恢复 POC 快照到 POCCalculator"""
        if calculator is None:
            return
        try:
            rows = await self._db_manager.async_execute_query(
                f"SELECT stock_code, poc_price, volume_profile "
                f"FROM scalping_poc_snapshot "
                f"WHERE stock_code IN ({placeholders}) AND trade_date = ?",
                params,
            )
            for row in rows:
                code, poc_price, profile_json = row[0], row[1], row[2]
                volume_profile = json.loads(profile_json)
                state = calculator._get_state(code)
                # 将 volume_profile (dict[str, int]) 转换为 volume_bins (dict[str, _VolumeBin])
                # 由于持久化时只保存了总量，恢复时将总量平均分配给买卖双方
                state.volume_bins = {
                    price_key: _VolumeBin(
                        buy_volume=total_volume // 2,
                        sell_volume=total_volume - total_volume // 2,
                    )
                    for price_key, total_volume in volume_profile.items()
                }
                state.last_poc_price = poc_price
            logger.debug("恢复 POC 快照: %d 条记录", len(rows))
        except Exception as e:
            logger.error("恢复 POC 快照失败: %s", e)

    async def _restore_levels(
        self, placeholders: str, params: tuple, spoofing_filter,
    ) -> None:
        """恢复活跃阻力/支撑线到 SpoofingFilter"""
        if spoofing_filter is None:
            return
        try:
            rows = await self._db_manager.async_execute_query(
                f"SELECT stock_code, price, volume, side, action "
                f"FROM scalping_price_levels "
                f"WHERE stock_code IN ({placeholders}) AND trade_date = ? "
                f"ORDER BY id ASC",
                params,
            )
            # 按 (stock_code, price) 追踪最终状态
            final_state: dict[tuple[str, float], tuple] = {}
            for row in rows:
                key = (row[0], row[1])
                final_state[key] = (row[0], row[1], row[2], row[3], row[4])

            restored = 0
            for (_code, _price), (code, price, volume, side, action) in final_state.items():
                if action == PriceLevelAction.CREATE.value:
                    level = PriceLevelData(
                        stock_code=code,
                        price=price,
                        volume=volume,
                        side=PriceLevelSide(side),
                        action=PriceLevelAction.CREATE,
                        timestamp=datetime.now().isoformat(),
                    )
                    spoofing_filter._add_active_level(code, level)
                    restored += 1
            logger.info("恢复活跃阻力/支撑线: %d 条", restored)
        except Exception as e:
            logger.error("恢复阻力/支撑线失败: %s", e)

    async def _restore_signals(
        self, placeholders: str, params: tuple, socket_manager,
    ) -> None:
        """恢复交易信号并推送给前端"""
        if socket_manager is None:
            return
        try:
            rows = await self._db_manager.async_execute_query(
                f"SELECT stock_code, signal_type, trigger_price, "
                f"support_price, conditions, created_at "
                f"FROM scalping_signals "
                f"WHERE stock_code IN ({placeholders}) AND trade_date = ? "
                f"ORDER BY id ASC",
                params,
            )
            for row in rows:
                signal_data = {
                    "stock_code": row[0],
                    "signal_type": row[1],
                    "trigger_price": row[2],
                    "support_price": row[3],
                    "conditions": json.loads(row[4]) if row[4] else [],
                    "timestamp": row[5] or datetime.now().isoformat(),
                }
                try:
                    await socket_manager.emit_to_all(
                        SocketEvent.SCALPING_SIGNAL, signal_data,
                    )
                except Exception:
                    pass
            logger.info("恢复交易信号: %d 条", len(rows))
        except Exception as e:
            logger.error("恢复交易信号失败: %s", e)

    # ================================================================
    # 快照查询（从 engine._get_db_snapshot 移入）
    # ================================================================

    async def get_today_snapshot(self, stock_code: str) -> dict | None:
        """从数据库查询当日快照数据

        Args:
            stock_code: 股票代码

        Returns:
            快照字典或 None
        """
        trade_date = datetime.now().strftime("%Y-%m-%d")
        params = (stock_code, trade_date)

        try:
            # Delta 历史
            delta_rows = await self._db_manager.async_execute_query(
                "SELECT stock_code, delta, volume, period_seconds "
                "FROM scalping_delta_history "
                "WHERE stock_code = ? AND trade_date = ? "
                "ORDER BY id DESC LIMIT 60",
                params,
            )
            delta_data = [
                {"stock_code": r[0], "delta": r[1], "volume": r[2],
                 "period_seconds": r[3], "timestamp": datetime.now().isoformat()}
                for r in reversed(delta_rows)
            ]

            # POC 快照
            poc_rows = await self._db_manager.async_execute_query(
                "SELECT poc_price, volume_profile "
                "FROM scalping_poc_snapshot "
                "WHERE stock_code = ? AND trade_date = ?",
                params,
            )
            poc_data = None
            if poc_rows:
                poc_price = poc_rows[0][0]
                volume_profile = json.loads(poc_rows[0][1])
                poc_data = {
                    "stock_code": stock_code,
                    "poc_price": poc_price,
                    "poc_volume": volume_profile.get(str(poc_price), 0),
                    "volume_profile": volume_profile,
                    "timestamp": datetime.now().isoformat(),
                }

            # 活跃阻力/支撑位
            level_rows = await self._db_manager.async_execute_query(
                "SELECT stock_code, price, volume, side, action "
                "FROM scalping_price_levels "
                "WHERE stock_code = ? AND trade_date = ? "
                "ORDER BY id ASC",
                params,
            )
            final: dict[float, tuple] = {}
            for r in level_rows:
                if r[4] == "create":
                    final[r[1]] = r
                else:
                    final.pop(r[1], None)
            price_levels = [
                {"stock_code": r[0], "price": r[1], "volume": r[2],
                 "side": r[3], "action": "create",
                 "timestamp": datetime.now().isoformat()}
                for r in final.values()
            ]

            if not delta_data and poc_data is None and not price_levels:
                return None

            return {
                "stock_code": stock_code,
                "delta_data": delta_data,
                "poc_data": poc_data,
                "price_levels": price_levels,
                "vwap_value": None,
            }
        except Exception as e:
            logger.error(f"[{stock_code}] 从数据库获取快照失败: {e}")
            return None

    # ================================================================
    # 数据清理（Task 7.1 实现）
    # ================================================================

    async def cleanup_old_data(self, days: int = 7) -> None:
        """删除 N 天前的历史数据（通过 write_queue 序列化，避免锁冲突）"""
        try:
            cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        except Exception as e:
            logger.error("计算清理截止日期失败: %s", e)
            return

        tables = [
            "ticker_data",
            "scalping_signals",
            "scalping_delta_history",
            "scalping_poc_snapshot",
            "scalping_price_levels",
            "scalping_events",
        ]
        for table in tables:
            try:
                sql = f"DELETE FROM {table} WHERE trade_date < ?"
                future = self._db_manager.write_queue.submit(
                    self._db_manager.execute_update, sql, (cutoff_date,),
                )
                deleted = await asyncio.wait_for(
                    asyncio.to_thread(future.result), timeout=30.0,
                )
                if deleted and deleted > 0:
                    logger.info("清理 %s: 删除 %d 条过期记录", table, deleted)
            except Exception as e:
                logger.error("清理 %s 失败: %s", table, e)


    # ================================================================
    # 内部方法
    # ================================================================

    async def _flush_loop(self) -> None:
        """后台定时 flush 循环"""
        flush_count = 0
        while self._running:
            try:
                await asyncio.sleep(FLUSH_INTERVAL)
                flush_count += 1

                # 记录 flush 前队列大小
                q_sizes = {
                    "signal": len(self._signal_queue),
                    "delta": len(self._delta_queue),
                    "poc": len(self._poc_queue),
                    "level": len(self._level_queue),
                    "ticker": len(self._ticker_queue),
                    "event": len(self._event_queue),
                }
                total_pending = sum(q_sizes.values())

                import time
                t0 = time.time()
                await self.flush()
                flush_duration = time.time() - t0

                # 每 12 次（约 60 秒）输出一次诊断
                if flush_count % 12 == 1 or flush_duration > 5.0:
                    non_zero = {k: v for k, v in q_sizes.items() if v > 0}
                    logger.info(
                        f"[Persistence诊断] flush#{flush_count} | "
                        f"待写入:{total_pending}条 {non_zero} | "
                        f"耗时:{flush_duration:.2f}s"
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Scalping flush 循环异常: %s", e)

