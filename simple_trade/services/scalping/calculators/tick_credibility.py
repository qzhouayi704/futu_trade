"""
Tick 数据可信度过滤器（Tick Credibility Filter）

在 ScalpingEngine 的 on_tick 分发前执行数据清洗：
1. 过滤集合竞价 Tick（时间戳早于开盘时间的 Tick 直接丢弃）
2. 维护最近 100 笔成交量的滚动均值
3. 标记异常大单为 OUTLIER（成交量超过近 100 笔均值 50 倍），不计入 Delta 计算
4. 推送 TICK_OUTLIER 事件（包含成交价、成交量、均值倍数和时间戳）
5. 开盘后不足 100 笔时使用已有数据均值，不足 5 笔时不进行异常大单检测
"""

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from simple_trade.services.scalping.models import TickData

logger = logging.getLogger("scalping")

# TICK_OUTLIER 事件名（SocketEvent 枚举将在 task 10.2 中添加，暂用字符串）
_TICK_OUTLIER_EVENT = "tick_outlier"


@dataclass
class _StockCredibilityState:
    """单个股票的可信度过滤状态"""
    # 最近 N 笔成交量的滚动窗口
    volume_window: deque = field(default_factory=deque)


class TickCredibilityFilter:
    """Tick 数据可信度过滤器

    在 ScalpingEngine 的 on_tick 分发链路中位于所有下游计算器之前，
    负责过滤集合竞价 Tick 和标记异常大单为 OUTLIER。
    """

    def __init__(
        self,
        socket_manager,
        market_open_time: str = "09:30",
        outlier_multiplier: float = 50.0,
        rolling_window_size: int = 100,
        min_samples_for_detection: int = 5,
    ):
        """初始化 TickCredibilityFilter

        Args:
            socket_manager: SocketManager 实例，用于推送 TICK_OUTLIER 事件
            market_open_time: 开盘时间（HH:MM 格式），默认 "09:30"
            outlier_multiplier: 异常大单倍数阈值，默认 50.0
            rolling_window_size: 滚动均值窗口大小，默认 100
            min_samples_for_detection: 最少样本数才启用异常检测，默认 5
        """
        self._socket_manager = socket_manager
        self._outlier_multiplier = outlier_multiplier
        self._rolling_window_size = rolling_window_size
        self._min_samples_for_detection = min_samples_for_detection
        self._persistence = None
        self._states: dict[str, _StockCredibilityState] = {}

        # 解析开盘时间为 (hour, minute)
        parts = market_open_time.strip().split(":")
        self._open_hour = int(parts[0])
        self._open_minute = int(parts[1])

    def _get_state(self, stock_code: str) -> _StockCredibilityState:
        """获取或创建股票状态"""
        if stock_code not in self._states:
            self._states[stock_code] = _StockCredibilityState(
                volume_window=deque(maxlen=self._rolling_window_size)
            )
        return self._states[stock_code]

    def _is_before_market_open(self, timestamp_ms: float) -> bool:
        """判断时间戳是否早于开盘时间

        Args:
            timestamp_ms: Unix 时间戳（毫秒）

        Returns:
            True 表示早于开盘时间（集合竞价阶段）
        """
        # 将毫秒时间戳转换为 datetime（使用 UTC+8 中国时区）
        tz_cn = timezone(timedelta(hours=8))
        dt = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=tz_cn)
        tick_minutes = dt.hour * 60 + dt.minute
        open_minutes = self._open_hour * 60 + self._open_minute
        return tick_minutes < open_minutes

    def filter_tick(
        self, stock_code: str, tick: TickData
    ) -> tuple[bool, bool]:
        """过滤并验证 Tick 数据

        返回 (should_dispatch, is_outlier):
        - 集合竞价 Tick（时间戳早于开盘时间）→ (False, False)，直接丢弃
        - 异常大单（成交量 > 近 100 笔均值 × 50）→ (False, True)，标记 OUTLIER
        - 正常 Tick → (True, False)，分发至下游计算器

        Args:
            stock_code: 股票代码
            tick: 逐笔成交数据

        Returns:
            (should_dispatch, is_outlier) 元组
        """
        # 1. 过滤集合竞价 Tick
        if self._is_before_market_open(tick.timestamp):
            logger.debug(
                f"[{stock_code}] 丢弃集合竞价 Tick: "
                f"price={tick.price}, volume={tick.volume}"
            )
            return (False, False)

        state = self._get_state(stock_code)

        # 2. 异常大单检测
        avg_volume = self._calc_avg_volume(state)
        is_outlier = False

        if (
            avg_volume is not None
            and len(state.volume_window) >= self._min_samples_for_detection
            and tick.volume > avg_volume * self._outlier_multiplier
        ):
            is_outlier = True
            multiplier = tick.volume / avg_volume
            logger.info(
                f"[{stock_code}] 异常大单 OUTLIER: "
                f"price={tick.price}, volume={tick.volume}, "
                f"avg={avg_volume:.1f}, multiplier={multiplier:.1f}x"
            )
            # 异步推送 TICK_OUTLIER 事件
            self._emit_outlier_event(
                stock_code, tick, avg_volume, multiplier
            )
            # OUTLIER 不计入滚动窗口，不分发至下游
            return (False, True)

        # 3. 正常 Tick：加入滚动窗口
        state.volume_window.append(tick.volume)
        return (True, False)

    def get_rolling_avg_volume(
        self, stock_code: str
    ) -> Optional[float]:
        """获取最近 100 笔成交量的滚动均值

        Args:
            stock_code: 股票代码

        Returns:
            滚动均值，无数据时返回 None
        """
        state = self._get_state(stock_code)
        return self._calc_avg_volume(state)

    def reset(self, stock_code: str) -> None:
        """重置指定股票的滚动窗口

        Args:
            stock_code: 股票代码
        """
        if stock_code in self._states:
            del self._states[stock_code]
        logger.info(f"已重置 {stock_code} 的 Tick 可信度过滤状态")

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_avg_volume(
        state: _StockCredibilityState,
    ) -> Optional[float]:
        """计算滚动窗口内的成交量均值

        Returns:
            均值，窗口为空时返回 None
        """
        if not state.volume_window:
            return None
        return sum(state.volume_window) / len(state.volume_window)

    def _emit_outlier_event(
        self,
        stock_code: str,
        tick: TickData,
        avg_volume: float,
        multiplier: float,
    ) -> None:
        """异步推送 TICK_OUTLIER 事件（fire-and-forget）

        TickOutlierData 模型将在 task 10.1 中添加到 models.py，
        此处使用 dict 匹配其 schema。
        """
        tz_cn = timezone(timedelta(hours=8))
        dt = datetime.fromtimestamp(tick.timestamp / 1000.0, tz=tz_cn)

        event_data = {
            "stock_code": stock_code,
            "price": tick.price,
            "volume": tick.volume,
            "avg_volume": round(avg_volume, 2),
            "multiplier": round(multiplier, 2),
            "timestamp": dt.isoformat(),
        }

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._do_emit_outlier(event_data))
        except RuntimeError:
            # 没有运行中的事件循环（如测试环境），跳过推送
            logger.debug("无事件循环，跳过 TICK_OUTLIER 推送")

    async def _do_emit_outlier(self, event_data: dict) -> None:
        """实际执行 TICK_OUTLIER 事件推送"""
        try:
            await self._socket_manager.emit_to_all(
                _TICK_OUTLIER_EVENT,
                event_data,
            )
        except Exception as e:
            logger.warning(f"推送 TICK_OUTLIER 失败: {e}")
        if self._persistence:
            self._persistence.enqueue_event("tick_outlier", event_data)
