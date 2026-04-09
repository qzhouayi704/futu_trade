"""防撤单陷阱过滤器 - 监控 OrderBook 巨单，提取真实阻力/支撑线，检测虚假流动性"""

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from simple_trade.services.scalping.models import (
    FakeLiquidityAlertData,
    OrderBookData,
    PriceLevelAction,
    PriceLevelData,
    PriceLevelSide,
)
from simple_trade.websocket.events import SocketEvent

logger = logging.getLogger("scalping")


@dataclass
class _VolumeSnapshot:
    """某档位在某时刻的挂单量快照"""
    volume: int
    timestamp: float  # Unix 秒


@dataclass
class _TrackedLargeOrder:
    """被跟踪的疑似巨单"""
    price: float
    side: PriceLevelSide
    first_seen_time: float       # 首次检测到的时间（Unix 秒）
    initial_volume: int          # 首次检测到的挂单量
    last_volume: int             # 最近一次快照的挂单量
    confirmed: bool = False      # 是否已推送 CREATE 事件


@dataclass
class _FakeLiquidityTracker:
    """跟踪 Bid 侧大单"步步紧逼"行为"""
    move_path: list[float]           # 大单移动路径（价格列表）
    initial_volume: int              # 首次检测到的挂单量
    first_seen_time: float           # 首次检测时间（Unix 秒）
    confirmed_suspicious: bool = False  # 是否已标记为"疑似虚假流动性"
    last_mid_prices: list[float] = field(default_factory=list)  # 近期中间价快照


@dataclass
class _PriceLevelHistory:
    """某档位的历史挂单量记录"""
    snapshots: deque = field(default_factory=lambda: deque())


class SpoofingFilter:
    """防撤单陷阱过滤器 - 检测巨单、判断撤销/突破、检测虚假流动性"""

    def __init__(
        self,
        socket_manager,
        volume_multiplier: float = 5.0,
        survive_seconds_min: float = 3.0,
        survive_seconds_max: float = 5.0,
        history_window_seconds: float = 60.0,
        proximity_ticks: int = 5,
        tick_size: float = 0.01,
        persistence=None,
    ):
        self._socket_manager = socket_manager
        self._persistence = persistence
        self._volume_multiplier = volume_multiplier
        self._survive_seconds_min = survive_seconds_min
        self._survive_seconds_max = survive_seconds_max
        self._history_window_seconds = history_window_seconds
        self._proximity_ticks = proximity_ticks
        self._tick_size = tick_size

        # stock_code -> { price -> _PriceLevelHistory }
        self._histories: dict[str, dict[float, _PriceLevelHistory]] = {}
        # stock_code -> { price -> _TrackedLargeOrder }
        self._tracked: dict[str, dict[float, _TrackedLargeOrder]] = {}
        # stock_code -> list[PriceLevelData] (已确认的活跃阻力/支撑线)
        self._active_levels: dict[str, list[PriceLevelData]] = {}
        # stock_code -> list[_FakeLiquidityTracker] (虚假流动性跟踪器)
        self._fake_liquidity_trackers: dict[str, list[_FakeLiquidityTracker]] = {}
        # stock_code -> list[float] (最近中间价快照，用于停滞检测)
        self._recent_mid_prices: dict[str, list[tuple[float, float]]] = {}

    def _get_history(self, stock_code: str, price: float) -> _PriceLevelHistory:
        """获取或创建某档位的历史记录"""
        if stock_code not in self._histories:
            self._histories[stock_code] = {}
        price_map = self._histories[stock_code]
        if price not in price_map:
            price_map[price] = _PriceLevelHistory()
        return price_map[price]

    def _compute_rolling_avg(self, stock_code: str, price: float, now: float) -> Optional[float]:
        """计算某档位最近 history_window_seconds 秒的挂单量滚动均值"""
        hist = self._get_history(stock_code, price)
        if not hist.snapshots:
            return None
        cutoff = now - self._history_window_seconds
        # 清理过期快照
        while hist.snapshots and hist.snapshots[0].timestamp < cutoff:
            hist.snapshots.popleft()
        if not hist.snapshots:
            return None
        total = sum(s.volume for s in hist.snapshots)
        return total / len(hist.snapshots)

    def _record_snapshot(self, stock_code: str, price: float, volume: int, now: float) -> None:
        """记录某档位的挂单量快照"""
        hist = self._get_history(stock_code, price)
        hist.snapshots.append(_VolumeSnapshot(volume=volume, timestamp=now))

    def _get_mid_price(self, order_book: OrderBookData) -> Optional[float]:
        if not order_book.ask_levels or not order_book.bid_levels:
            return None
        return (order_book.ask_levels[0].price + order_book.bid_levels[0].price) / 2.0

    def _is_price_close(self, price: float, mid_price: float) -> bool:
        return abs(price - mid_price) < self._proximity_ticks * self._tick_size

    def _build_current_book_map(
        self, order_book: OrderBookData, mid_price: float,
    ) -> dict[float, tuple[int, PriceLevelSide]]:
        """将 OrderBook 转换为 { price: (volume, side) } 映射"""
        book_map: dict[float, tuple[int, PriceLevelSide]] = {}
        for level in order_book.ask_levels:
            book_map[level.price] = (level.volume, PriceLevelSide.RESISTANCE)
        for level in order_book.bid_levels:
            book_map[level.price] = (level.volume, PriceLevelSide.SUPPORT)
        return book_map

    async def _emit_event(
        self, stock_code: str, price: float, volume: int,
        side: PriceLevelSide, action: PriceLevelAction,
    ) -> PriceLevelData:
        """构建并推送 PriceLevelData 事件"""
        event_map = {
            PriceLevelAction.CREATE: SocketEvent.PRICE_LEVEL_CREATE,
            PriceLevelAction.REMOVE: SocketEvent.PRICE_LEVEL_REMOVE,
            PriceLevelAction.BREAK: SocketEvent.PRICE_LEVEL_BREAK,
        }
        data = PriceLevelData(
            stock_code=stock_code,
            price=price,
            volume=volume,
            side=side,
            action=action,
            timestamp=datetime.now().isoformat(),
        )
        try:
            await self._socket_manager.emit_to_all(
                event_map[action], data.model_dump()
            )
        except Exception as e:
            logger.warning(f"推送 {action.value} 事件失败: {e}")

        if self._persistence is not None:
            try:
                self._persistence.enqueue_price_level(data)
            except Exception as e:
                logger.warning(f"阻力/支撑线入队持久化失败: {e}")

        return data

    def _add_active_level(self, stock_code: str, level: PriceLevelData) -> None:
        """添加到活跃阻力/支撑线列表"""
        if stock_code not in self._active_levels:
            self._active_levels[stock_code] = []
        self._active_levels[stock_code].append(level)

    def _remove_active_level(self, stock_code: str, price: float) -> None:
        """从活跃列表中移除指定价格的阻力/支撑线"""
        if stock_code not in self._active_levels:
            return
        self._active_levels[stock_code] = [
            lv for lv in self._active_levels[stock_code]
            if lv.price != price
        ]

    async def on_order_book(
        self, stock_code: str, order_book: OrderBookData
    ) -> None:
        """处理 OrderBook 快照，检测巨单、更新计时器、判断撤销/突破。"""
        mid_price = self._get_mid_price(order_book)
        if mid_price is None:
            return

        now = order_book.timestamp / 1000.0  # 毫秒 → 秒
        book_map = self._build_current_book_map(order_book, mid_price)

        # 1. 检测新巨单（先计算均值，再记录快照）
        for price, (volume, side) in book_map.items():
            avg = self._compute_rolling_avg(stock_code, price, now)
            self._record_snapshot(stock_code, price, volume, now)
            if avg is None or avg <= 0:
                continue

            tracked_map = self._tracked.setdefault(stock_code, {})
            if volume >= avg * self._volume_multiplier:
                # 新巨单：尚未跟踪则开始跟踪
                if price not in tracked_map:
                    tracked_map[price] = _TrackedLargeOrder(
                        price=price, side=side, first_seen_time=now,
                        initial_volume=volume, last_volume=volume,
                    )
                    logger.debug(f"[{stock_code}] 检测到疑似巨单: price={price}, volume={volume}, avg={avg:.0f}")
                else:
                    # 更新最近挂单量
                    tracked_map[price].last_volume = volume
            elif price in tracked_map:
                # 已跟踪但挂单量降到阈值以下，仍需更新 last_volume
                tracked_map[price].last_volume = volume

        # 2. 检查已跟踪巨单的状态
        tracked_map = self._tracked.get(stock_code, {})
        prices_to_remove: list[float] = []

        for price, order in list(tracked_map.items()):
            current_volume = book_map.get(price, (0, order.side))[0]
            survived = now - order.first_seen_time

            # 巨单消失判定：绝对阈值 OR 单次快照下降速率 > 40%
            abs_vanished = current_volume < order.initial_volume * 0.3
            rapid_decline = (
                order.last_volume > 0
                and (order.last_volume - current_volume) / order.last_volume > 0.4
            )
            volume_vanished = abs_vanished or rapid_decline
            if price not in book_map or volume_vanished:
                await self._handle_disappeared(
                    stock_code, order, current_volume,
                    survived, mid_price, prices_to_remove
                )
            elif not order.confirmed and survived >= self._survive_seconds_max:
                # 存活超过上限，确认为真实阻力/支撑
                level = await self._emit_event(
                    stock_code, price, current_volume,
                    order.side, PriceLevelAction.CREATE,
                )
                self._add_active_level(stock_code, level)
                order.confirmed = True
                side_name = '阻力' if order.side == PriceLevelSide.RESISTANCE else '支撑'
                logger.info(f"[{stock_code}] 巨单确认为{side_name}线: price={price}, survived={survived:.1f}s")

        # 清理已处理的跟踪记录
        for price in prices_to_remove:
            tracked_map.pop(price, None)

        # 3. 检测虚假流动性（步步紧逼）
        await self._check_fake_liquidity(stock_code, order_book, mid_price, now)

    async def _check_fake_liquidity(
        self, stock_code: str, order_book: OrderBookData,
        mid_price: float, now: float,
    ) -> None:
        """检测 Bid/Ask 双侧大单"步步紧逼"虚假流动性行为"""
        # 记录中间价快照（用于停滞检测）
        mid_list = self._recent_mid_prices.setdefault(stock_code, [])
        mid_list.append((mid_price, now))
        mid_list[:] = [(p, t) for p, t in mid_list if now - t <= 5.0]

        # Bid 侧：大单上移 + 价格上涨 → 虚假支撑
        await self._check_fake_liquidity_side(
            stock_code, order_book.bid_levels, mid_price, now, mid_list, is_bid=True,
        )
        # Ask 侧：大单下移 + 价格下跌 → 虚假阻力（压盘）
        await self._check_fake_liquidity_side(
            stock_code, order_book.ask_levels, mid_price, now, mid_list, is_bid=False,
        )

    async def _check_fake_liquidity_side(
        self, stock_code: str, levels: list,
        mid_price: float, now: float,
        mid_list: list[tuple[float, float]], is_bid: bool,
    ) -> None:
        """单侧虚假流动性检测（Bid 或 Ask）"""
        side_key = f"{stock_code}_{'bid' if is_bid else 'ask'}"
        trackers = self._fake_liquidity_trackers.setdefault(side_key, [])

        large_prices: dict[float, int] = {}
        for level in levels:
            avg = self._compute_rolling_avg(stock_code, level.price, now)
            if avg and avg > 0 and level.volume >= avg * self._volume_multiplier:
                large_prices[level.price] = level.volume

        updated_trackers: list[_FakeLiquidityTracker] = []
        matched_prices: set[float] = set()

        for tracker in trackers:
            last_price = tracker.move_path[-1]
            best_match: float | None = None
            for price, vol in large_prices.items():
                if price not in matched_prices:
                    if is_bid and price > last_price:
                        if best_match is None or price < best_match:
                            best_match = price
                    elif not is_bid and price < last_price:
                        if best_match is None or price > best_match:
                            best_match = price

            last_mid = tracker.last_mid_prices[-1]
            mid_moved = (mid_price > last_mid) if is_bid else (mid_price < last_mid)
            if best_match is not None and mid_moved:
                tracker.move_path.append(best_match)
                tracker.last_mid_prices.append(mid_price)
                matched_prices.add(best_match)
                if len(tracker.move_path) >= 3 and not tracker.confirmed_suspicious:
                    tracker.confirmed_suspicious = True
                    side_name = "Bid" if is_bid else "Ask"
                    logger.info(f"[{stock_code}] {side_name}侧疑似虚假流动性: path={tracker.move_path}")
                updated_trackers.append(tracker)
            elif best_match is None and tracker.confirmed_suspicious:
                await self._emit_fake_liquidity_if_stagnant(
                    stock_code, tracker, mid_list, now
                )
            elif last_price in large_prices:
                matched_prices.add(last_price)
                tracker.last_mid_prices.append(mid_price)
                updated_trackers.append(tracker)

        for price, vol in large_prices.items():
            if price not in matched_prices:
                updated_trackers.append(_FakeLiquidityTracker(
                    move_path=[price], initial_volume=vol,
                    first_seen_time=now, last_mid_prices=[mid_price],
                ))
        self._fake_liquidity_trackers[side_key] = updated_trackers

    async def _emit_fake_liquidity_if_stagnant(
        self, stock_code: str, tracker: _FakeLiquidityTracker,
        mid_list: list[tuple[float, float]], now: float,
    ) -> None:
        """已确认的虚假流动性大单消失时，检查价格停滞并推送警报"""
        cutoff = now - 3.0
        recent = [p for p, t in mid_list if t >= cutoff]
        if len(recent) < 2:
            return
        if max(recent) - min(recent) >= 2 * self._tick_size:
            return
        data = FakeLiquidityAlertData(
            stock_code=stock_code,
            disappear_price=tracker.move_path[-1],
            original_volume=tracker.initial_volume,
            tracking_duration=now - tracker.first_seen_time,
            move_path=tracker.move_path,
            timestamp=datetime.now().isoformat(),
        )
        try:
            await self._socket_manager.emit_to_all(SocketEvent.FAKE_LIQUIDITY_ALERT, data.model_dump())
        except Exception as e:
            logger.warning(f"推送虚假流动性警报失败: {e}")

    async def _handle_disappeared(
        self, stock_code: str, order: _TrackedLargeOrder,
        current_volume: int, survived: float,
        mid_price: float, prices_to_remove: list[float],
    ) -> None:
        """处理巨单消失"""
        price = order.price
        if survived < self._survive_seconds_min:
            prices_to_remove.append(price)
            return

        is_close = self._is_price_close(price, mid_price)
        was_consumed = self._is_consumed(order, current_volume)

        if was_consumed:
            await self._emit_event(stock_code, price, current_volume, order.side, PriceLevelAction.BREAK)
            self._remove_active_level(stock_code, price)
        elif is_close:
            await self._emit_event(stock_code, price, current_volume, order.side, PriceLevelAction.REMOVE)
            self._remove_active_level(stock_code, price)
        else:
            self._remove_active_level(stock_code, price)

        prices_to_remove.append(price)

    def _is_consumed(self, order: _TrackedLargeOrder, current_volume: int) -> bool:
        """判断巨单是否被市场成交吃透（逐步被吃掉而非一次性撤单）"""
        if current_volume > 0:
            return False
        return order.last_volume < order.initial_volume * 0.5

    def get_active_levels(self, stock_code: str) -> list[PriceLevelData]:
        """获取当前有效的阻力/支撑线（供 SignalEngine 使用）"""
        return list(self._active_levels.get(stock_code, []))

    def reset(self, stock_code: str) -> None:
        """重置指定股票的所有状态"""
        self._histories.pop(stock_code, None)
        self._tracked.pop(stock_code, None)
        self._active_levels.pop(stock_code, None)
        self._fake_liquidity_trackers.pop(stock_code, None)
        self._recent_mid_prices.pop(stock_code, None)
        logger.info(f"已重置 {stock_code} 的 SpoofingFilter 状态")
