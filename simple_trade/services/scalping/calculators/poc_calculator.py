"""
日内控制点计算器（POC Calculator）

实时维护 Price_Bin 哈希表，统计各价位买卖分离成交量，
计算成交量最大堆积区价格（POC）。

- 每笔 Tick 到达时将成交量按买卖方向累加到对应 Price_Bin
- calculate_poc 由外部调用者（ScalpingEngine）每 5 秒调用一次
- POC 变化时通过 SocketManager 推送 POC_UPDATE 事件
- 每日开盘时重置 Price_Bin
- 价格按 Tick Size 归一化，相邻 2 个 Tick 合并为一个 Bin
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from simple_trade.services.scalping.models import (
    PocUpdateData,
    TickData,
    TickDirection,
)
from simple_trade.websocket.events import SocketEvent

logger = logging.getLogger("scalping")

# 港股 Tick Size 分档表（价格上限, tick_size）
_HK_TICK_SIZES = [
    (0.25, 0.001), (0.50, 0.005), (10.0, 0.010),
    (20.0, 0.020), (100.0, 0.050), (200.0, 0.100),
    (500.0, 0.200), (1000.0, 0.500), (2000.0, 1.000),
    (5000.0, 2.000), (float("inf"), 5.000),
]


@dataclass
class _VolumeBin:
    """单个价位的买卖分离成交量"""
    buy_volume: int = 0
    sell_volume: int = 0

    @property
    def total(self) -> int:
        return self.buy_volume + self.sell_volume

    @property
    def buy_ratio(self) -> float:
        return self.buy_volume / self.total if self.total > 0 else 0.5


@dataclass
class _StockPocState:
    """单个股票的 POC 状态"""
    # Price_Bin: 归一化价格字符串 → _VolumeBin
    volume_bins: dict[str, _VolumeBin] = field(default_factory=dict)
    # 上次推送的 POC 价格，用于判断是否变化
    last_poc_price: Optional[float] = None
    # 上次计算 POC 的时间戳
    last_calc_time: float = 0.0


class POCCalculator:
    """日内控制点计算器

    维护 Price_Bin 哈希表，按 Tick Size 归一化价格，
    统计各价位买卖分离成交量，计算 POC（成交量最大的价位）。
    """

    def __init__(
        self,
        socket_manager,
        update_interval: float = 5.0,
        market: str = "HK",
        persistence=None,
    ):
        """初始化 POCCalculator

        Args:
            socket_manager: SocketManager 实例，用于推送 POC_UPDATE 事件
            update_interval: 最小计算间隔（秒），由外部调用者控制节奏
            market: 市场标识（"HK" 或 "US"），用于价格归一化
            persistence: ScalpingPersistence 实例（可选），用于数据持久化
        """
        self._socket_manager = socket_manager
        self._update_interval = update_interval
        self._market = market
        self._persistence = persistence
        self._states: dict[str, _StockPocState] = {}

    def _get_state(self, stock_code: str) -> _StockPocState:
        """获取或创建股票的 POC 状态"""
        if stock_code not in self._states:
            self._states[stock_code] = _StockPocState()
        return self._states[stock_code]

    @staticmethod
    def _get_hk_tick_size(price: float) -> float:
        """根据港股价格获取对应的 Tick Size"""
        for upper, tick_size in _HK_TICK_SIZES:
            if price < upper:
                return tick_size
        return 5.0

    def _normalize_price(self, price: float) -> str:
        """按 Tick Size 归一化价格，合并相邻 2 个 Tick 为一个 Bin

        Args:
            price: 原始价格

        Returns:
            归一化后的价格字符串（作为 dict key）
        """
        if self._market == "HK":
            tick_size = self._get_hk_tick_size(price)
        else:
            # 美股统一 0.01
            tick_size = 0.01
        bin_size = tick_size * 2
        normalized = round(price / bin_size) * bin_size
        return f"{normalized:.4f}"

    def on_tick(
        self,
        stock_code: str,
        tick: TickData,
        direction: Optional[TickDirection] = None,
    ) -> None:
        """将成交量按买卖方向累加到对应 Price_Bin

        Args:
            stock_code: 股票代码
            tick: 逐笔成交数据
            direction: 成交方向（来自 DeltaCalculator），None 时按 NEUTRAL 处理
        """
        state = self._get_state(stock_code)
        price_key = self._normalize_price(tick.price)

        if price_key not in state.volume_bins:
            state.volume_bins[price_key] = _VolumeBin()
        vbin = state.volume_bins[price_key]

        effective_dir = direction or TickDirection.NEUTRAL
        if effective_dir == TickDirection.BUY:
            vbin.buy_volume += tick.volume
        elif effective_dir == TickDirection.SELL:
            vbin.sell_volume += tick.volume
        else:
            # NEUTRAL 按 50/50 分配
            half = tick.volume // 2
            vbin.buy_volume += half
            vbin.sell_volume += tick.volume - half

    async def calculate_poc(
        self, stock_code: str
    ) -> Optional[PocUpdateData]:
        """计算当前 POC 值，若变化则通过 SocketManager 推送

        Args:
            stock_code: 股票代码

        Returns:
            PocUpdateData 或 None（无数据或 POC 未变化）
        """
        state = self._get_state(stock_code)

        if not state.volume_bins:
            return None

        # 找到成交量最大的价位
        poc_price_key = max(
            state.volume_bins,
            key=lambda k: state.volume_bins[k].total,
        )
        poc_bin = state.volume_bins[poc_price_key]
        poc_price = float(poc_price_key)
        poc_volume = poc_bin.total

        # POC 未变化时不推送
        if state.last_poc_price == poc_price:
            return None

        state.last_poc_price = poc_price

        # 构建兼容的 volume_profile（总量）
        volume_profile = {
            k: vbin.total for k, vbin in state.volume_bins.items()
        }

        update = PocUpdateData(
            stock_code=stock_code,
            poc_price=poc_price,
            poc_volume=poc_volume,
            poc_buy_ratio=round(poc_bin.buy_ratio, 3),
            volume_profile=volume_profile,
            timestamp=datetime.now().isoformat(),
        )

        if self._persistence is not None:
            try:
                self._persistence.enqueue_poc(
                    stock_code, poc_price, volume_profile,
                )
            except Exception as e:
                logger.warning(f"POC 入队持久化失败: {e}")

        try:
            await self._socket_manager.emit_to_all(
                SocketEvent.POC_UPDATE,
                update.model_dump(),
            )
        except Exception as e:
            logger.warning(f"推送 POC_UPDATE 失败: {e}")

        return update

    def get_volume_profile(self, stock_code: str) -> dict[float, int]:
        """获取完整的价位成交量分布（供前端渲染）"""
        state = self._get_state(stock_code)
        return {
            float(price_key): vbin.total
            for price_key, vbin in state.volume_bins.items()
        }

    def get_buy_sell_profile(
        self, stock_code: str,
    ) -> dict[float, tuple[int, int]]:
        """获取买卖分离的价位成交量分布（供前端双色渲染）

        Returns:
            价位(float) → (buy_volume, sell_volume) 的字典
        """
        state = self._get_state(stock_code)
        return {
            float(k): (vbin.buy_volume, vbin.sell_volume)
            for k, vbin in state.volume_bins.items()
        }

    def reset(self, stock_code: str) -> None:
        """每日开盘重置 Price_Bin 哈希表"""
        if stock_code in self._states:
            del self._states[stock_code]
        logger.info(f"已重置 {stock_code} 的 POC 状态")
