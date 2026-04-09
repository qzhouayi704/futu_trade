"""
多空净动量计算器（Delta Calculator）

使用 Lee-Ready 简化版算法判定成交方向，累加计算每个周期的净动量值。
支持 10 秒和 1 分钟两种累加周期。

Lee-Ready 简化版算法：
1. 成交价 == Ask → 买入（正值）
2. 成交价 == Bid → 卖出（负值）
3. 成交价在 Bid/Ask 之间 → 按距离归类：
   - 更接近 Ask → 买入
   - 更接近 Bid → 卖出
   - 正好在中间 → 参考 last_direction（Tick Test 回退）
   - 无 last_direction 记录 → 标记 NEUTRAL，不计入
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from simple_trade.services.scalping.models import (
    DeltaUpdateData,
    TickData,
    TickDirection,
)
from simple_trade.websocket.events import SocketEvent

logger = logging.getLogger("scalping")

# 四级订单分类阈值（按单笔成交金额）
_ORDER_TIER_SUPER_LARGE = 1_000_000.0   # 超大单 ≥ 100万
_ORDER_TIER_LARGE = 100_000.0           # 大单 10万-100万
_ORDER_TIER_MEDIUM = 20_000.0           # 中单 2万-10万
# 小单 < 2万（默认）

# 大单统计滚动窗口大小（保留最近 N 个周期的累计数据）
_BIG_ORDER_ROLLING_PERIODS = 30


@dataclass
class _PeriodAccumulator:
    """单个股票的周期累加状态"""
    delta: float = 0.0
    volume: int = 0
    tick_count: int = 0
    big_order_volume: int = 0  # 兼容旧逻辑（大单+超大单合计）
    # 四级成交量分类
    super_large_volume: int = 0    # 超大单成交量
    large_volume: int = 0          # 大单成交量
    medium_volume: int = 0         # 中单成交量
    small_volume: int = 0          # 小单成交量
    # 大单买卖方向拆分（超大单 + 大单）
    big_buy_volume: int = 0        # 大单主买量
    big_sell_volume: int = 0       # 大单主卖量
    # OHLC 价格追踪
    open_price: float = 0.0
    high_price: float = 0.0
    low_price: float = float('inf')
    close_price: float = 0.0




@dataclass
class _StockState:
    """单个股票的完整 Delta 状态"""
    current_period: _PeriodAccumulator = field(
        default_factory=_PeriodAccumulator
    )
    history: deque = field(default_factory=lambda: deque(maxlen=100))
    # 跨周期滚动窗口：(big_order_volume, total_volume) 每个周期一条
    rolling_big_order: deque = field(
        default_factory=lambda: deque(maxlen=_BIG_ORDER_ROLLING_PERIODS)
    )


class DeltaCalculator:
    """多空净动量计算器

    处理逐笔成交数据，使用 Lee-Ready 简化版算法判定方向，
    累加到当前周期。周期结束时通过 SocketManager 推送 DELTA_UPDATE 事件。
    """

    # 港股/美股最小成交量阈值
    _MARKET_MIN_VOLUME = {"HK": 100, "US": 1}

    def __init__(
        self,
        socket_manager,
        market: str = "HK",
        min_volume: Optional[int] = None,
        period_seconds: int = 10,
        persistence=None,
    ):
        """初始化 DeltaCalculator

        Args:
            socket_manager: SocketManager 实例，用于推送事件
            market: 市场标识（"HK" 或 "US"），用于动态设置 min_volume
            min_volume: 最小成交量阈值，None 时按市场自动设置
            period_seconds: 累加周期秒数（10 或 60）
            persistence: ScalpingPersistence 实例（可选），用于数据持久化
        """
        self._socket_manager = socket_manager
        self._min_volume = min_volume if min_volume is not None else self._MARKET_MIN_VOLUME.get(market, 100)
        self._period_seconds = period_seconds
        self._persistence = persistence
        self._states: dict[str, _StockState] = {}
        self._last_direction: dict[str, TickDirection] = {}
        self._last_price: dict[str, float] = {}


    def _get_state(self, stock_code: str) -> _StockState:
        """获取或创建股票状态"""
        if stock_code not in self._states:
            self._states[stock_code] = _StockState()
        return self._states[stock_code]

    def _classify_direction(
        self, stock_code: str, tick: TickData
    ) -> TickDirection:
        """NEUTRAL 回退：API 无法判定方向时直接归为中性，不计入 Delta

        仅当 Futu API 返回 NEUTRAL 时调用此方法。
        因为 API 不提供真实 ask/bid 价差，任何推断都不可靠，
        直接返回 NEUTRAL 以保证数据真实性。
        """
        return TickDirection.NEUTRAL

    def on_tick(self, stock_code: str, tick: TickData) -> TickDirection:
        """处理单笔 Tick，使用 Lee-Ready 简化版算法判定方向

        成交量 < min_volume 的 Tick 忽略，不计入净动量。
        每次判定后更新 last_direction。

        Args:
            stock_code: 股票代码
            tick: 逐笔成交数据

        Returns:
            判定后的成交方向（供 POCCalculator 等下游使用）
        """
        if tick.volume < self._min_volume:
            return TickDirection.NEUTRAL

        # 持久化逐笔数据（仅有效 Tick，volume >= min_volume）
        if self._persistence is not None:
            self._persistence.enqueue_ticker(tick)

        state = self._get_state(stock_code)
        acc = state.current_period

        # OHLC 价格追踪
        price = tick.price
        if acc.open_price == 0.0:
            acc.open_price = price
        if price > acc.high_price:
            acc.high_price = price
        if price < acc.low_price:
            acc.low_price = price
        acc.close_price = price

        # 优先使用 Futu API 提供的方向（ticker_direction 字段），
        # 仅当原始方向为 NEUTRAL 时才回退到 Lee-Ready 算法
        if tick.direction in (TickDirection.BUY, TickDirection.SELL):
            direction = tick.direction
        else:
            direction = self._classify_direction(stock_code, tick)

        # [DEBUG] 方向分布统计 — 每 200 笔输出一次
        if not hasattr(self, '_direction_counter'):
            self._direction_counter = {}
        key = stock_code
        if key not in self._direction_counter:
            self._direction_counter[key] = {"BUY": 0, "SELL": 0, "NEUTRAL": 0, "api_buy": 0, "api_sell": 0, "api_neutral": 0, "total": 0}
        c = self._direction_counter[key]
        c["total"] += 1
        c[direction.name] += 1
        c[f"api_{tick.direction.name.lower()}"] += 1
        if c["total"] % 200 == 0:
            logger.debug(
                f"[方向分布] {stock_code}: 最终 BUY={c['BUY']} SELL={c['SELL']} NEUTRAL={c['NEUTRAL']} | "
                f"API原始 buy={c['api_buy']} sell={c['api_sell']} neutral={c['api_neutral']} | "
                f"总计 {c['total']} 笔"
            )

        # 更新 last_direction（NEUTRAL 不更新，保留上一次有效方向）
        if direction != TickDirection.NEUTRAL:
            self._last_direction[stock_code] = direction

        if direction == TickDirection.BUY:
            acc.delta += tick.volume
            acc.volume += tick.volume
        elif direction == TickDirection.SELL:
            acc.delta -= tick.volume
            acc.volume += tick.volume
        # NEUTRAL: 不计入 Delta 也不计入 volume

        acc.tick_count += 1

        # 四级订单分类：按单笔成交金额分级
        turnover = tick.price * tick.volume
        is_buy = (direction == TickDirection.BUY)
        if turnover >= _ORDER_TIER_SUPER_LARGE:
            acc.super_large_volume += tick.volume
            acc.big_order_volume += tick.volume
            if is_buy:
                acc.big_buy_volume += tick.volume
            elif direction == TickDirection.SELL:
                acc.big_sell_volume += tick.volume
        elif turnover >= _ORDER_TIER_LARGE:
            acc.large_volume += tick.volume
            acc.big_order_volume += tick.volume
            if is_buy:
                acc.big_buy_volume += tick.volume
            elif direction == TickDirection.SELL:
                acc.big_sell_volume += tick.volume
        elif turnover >= _ORDER_TIER_MEDIUM:
            acc.medium_volume += tick.volume
        else:
            acc.small_volume += tick.volume

        return direction

    async def flush_period(
        self, stock_code: str
    ) -> Optional[DeltaUpdateData]:
        """结束当前累加周期，返回 DeltaUpdateData 并推送

        Args:
            stock_code: 股票代码

        Returns:
            DeltaUpdateData 或 None（如果没有数据）
        """
        state = self._get_state(stock_code)
        acc = state.current_period

        if acc.tick_count == 0:
            return None

        update = DeltaUpdateData(
            stock_code=stock_code,
            delta=acc.delta,
            volume=acc.volume,
            timestamp=datetime.now().isoformat(),
            period_seconds=self._period_seconds,
            open=acc.open_price if acc.open_price > 0 else None,
            high=acc.high_price if acc.high_price > 0 else None,
            low=acc.low_price if acc.low_price < float('inf') else None,
            close=acc.close_price if acc.close_price > 0 else None,
            big_order_volume=acc.big_order_volume,
            super_large_volume=acc.super_large_volume,
            large_volume=acc.large_volume,
            medium_volume=acc.medium_volume,
            small_volume=acc.small_volume,
            big_buy_volume=acc.big_buy_volume,
            big_sell_volume=acc.big_sell_volume,
        )

        state.history.append(update)

        # 将当前周期的大单统计加入滚动窗口
        state.rolling_big_order.append(
            (acc.big_order_volume, acc.volume)
        )

        if self._persistence is not None:
            try:
                self._persistence.enqueue_delta(update)
            except Exception as e:
                logger.warning(f"Delta 入队持久化失败: {e}")

        state.current_period = _PeriodAccumulator()

        try:
            await self._socket_manager.emit_to_all(
                SocketEvent.DELTA_UPDATE,
                update.model_dump(),
            )
        except Exception as e:
            logger.warning(f"推送 DELTA_UPDATE 失败: {e}")

        return update

    def get_current_period_stats(self, stock_code: str) -> tuple[float, int, int]:
        """获取当前周期的实时统计（不等待 flush）

        Returns:
            (delta, volume, tick_count)
        """
        state = self._get_state(stock_code)
        acc = state.current_period
        return acc.delta, acc.volume, acc.tick_count

    def get_big_order_ratio(self, stock_code: str) -> float:
        """获取大单成交量占比（滚动窗口 + 当前周期）

        Returns:
            大单成交量 / 总成交量，无数据时返回 0.0
        """
        state = self._get_state(stock_code)
        # 汇总滚动窗口历史
        total_big = 0
        total_vol = 0
        for big_vol, vol in state.rolling_big_order:
            total_big += big_vol
            total_vol += vol
        # 加上当前周期（尚未 flush 的数据）
        acc = state.current_period
        total_big += acc.big_order_volume
        total_vol += acc.volume
        if total_vol <= 0:
            return 0.0
        return total_big / total_vol

    def get_recent_deltas(
        self, stock_code: str, count: int = 20
    ) -> list[DeltaUpdateData]:
        """获取最近 N 个周期的 Delta 值

        Args:
            stock_code: 股票代码
            count: 获取数量，默认 20

        Returns:
            最近 N 个周期的 DeltaUpdateData 列表
        """
        state = self._get_state(stock_code)
        items = list(state.history)
        return items[-count:] if len(items) > count else items

    def reset(self, stock_code: str) -> None:
        """重置指定股票的累加状态

        Args:
            stock_code: 股票代码
        """
        if stock_code in self._states:
            del self._states[stock_code]
        if stock_code in self._last_direction:
            del self._last_direction[stock_code]
        logger.info(f"已重置 {stock_code} 的 Delta 累加状态")
