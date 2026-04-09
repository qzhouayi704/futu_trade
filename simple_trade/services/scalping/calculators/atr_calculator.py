"""
ATR（Average True Range）计算器

基于 ATR 的动态止损/止盈系统，根据市场波动率自动调整止损止盈距离。

止损策略：
    止损价 = 入场价 - 2 * ATR(14)

止盈策略：
    初始止盈价 = 入场价 + 3 * ATR(14)  # 风险回报比 1.5:1

    追踪止盈：
    - 价格每上涨 0.5 * ATR，止盈价上移 0.3 * ATR
    - 直到价格回撤触发止盈

应用场景：
- 高波动率股票：止损距离自动放宽
- 低波动率股票：止损距离收紧，避免被噪音扫损
"""
import logging
from collections import deque
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("scalping")


@dataclass
class KlineBar:
    """K线数据"""
    timestamp: float  # Unix 时间戳（秒）
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class StopLossTakeProfitLevels:
    """止损止盈价位"""
    entry_price: float  # 入场价
    stop_loss: float  # 止损价
    take_profit: float  # 止盈价
    trailing_take_profit: Optional[float] = None  # 追踪止盈价（如果已启动）
    atr_value: float = 0.0  # 当前 ATR 值


class ATRCalculator:
    """
    ATR 计算器

    基于 1 分钟 K 线计算 ATR，用于动态止损/止盈。
    """

    def __init__(
        self,
        period: int = 14,
        stop_loss_multiplier: float = 2.0,
        take_profit_multiplier: float = 3.0,
        trailing_trigger_multiplier: float = 0.5,
        trailing_step_multiplier: float = 0.3,
    ):
        """
        初始化 ATR 计算器

        Args:
            period: ATR 计算周期（默认 14）
            stop_loss_multiplier: 止损倍数（默认 2.0）
            take_profit_multiplier: 止盈倍数（默认 3.0）
            trailing_trigger_multiplier: 追踪止盈触发倍数（默认 0.5）
            trailing_step_multiplier: 追踪止盈步进倍数（默认 0.3）
        """
        self.period = period
        self.stop_loss_multiplier = stop_loss_multiplier
        self.take_profit_multiplier = take_profit_multiplier
        self.trailing_trigger_multiplier = trailing_trigger_multiplier
        self.trailing_step_multiplier = trailing_step_multiplier

        # 存储 K 线数据：stock_code -> deque[KlineBar]
        self._kline_data: dict[str, deque[KlineBar]] = {}

        # 存储 ATR 值：stock_code -> float
        self._atr_values: dict[str, float] = {}

    def add_kline(self, stock_code: str, kline: KlineBar) -> None:
        """
        添加 K 线数据

        Args:
            stock_code: 股票代码
            kline: K 线数据
        """
        if stock_code not in self._kline_data:
            self._kline_data[stock_code] = deque(maxlen=self.period + 1)

        self._kline_data[stock_code].append(kline)

        # 如果数据足够，计算 ATR
        if len(self._kline_data[stock_code]) >= self.period:
            atr = self._calculate_atr(stock_code)
            self._atr_values[stock_code] = atr

    def _calculate_true_range(self, current: KlineBar, previous: Optional[KlineBar]) -> float:
        """
        计算真实波幅（True Range）

        TR = max(high - low, |high - prev_close|, |low - prev_close|)

        Args:
            current: 当前 K 线
            previous: 前一根 K 线

        Returns:
            真实波幅
        """
        if previous is None:
            return current.high - current.low

        tr1 = current.high - current.low
        tr2 = abs(current.high - previous.close)
        tr3 = abs(current.low - previous.close)

        return max(tr1, tr2, tr3)

    def _calculate_atr(self, stock_code: str) -> float:
        """
        计算 ATR（Average True Range）

        使用简单移动平均法：ATR = SMA(TR, period)

        Args:
            stock_code: 股票代码

        Returns:
            ATR 值
        """
        klines = list(self._kline_data[stock_code])

        if len(klines) < self.period:
            return 0.0

        # 计算最近 period 个 TR 值
        tr_values = []
        for i in range(1, len(klines)):
            tr = self._calculate_true_range(klines[i], klines[i - 1])
            tr_values.append(tr)

        # 取最近 period 个 TR 值
        recent_tr = tr_values[-self.period:]

        # 计算平均值
        atr = sum(recent_tr) / len(recent_tr)

        return atr

    def get_atr(self, stock_code: str) -> Optional[float]:
        """
        获取当前 ATR 值

        Args:
            stock_code: 股票代码

        Returns:
            ATR 值，如果数据不足则返回 None
        """
        return self._atr_values.get(stock_code)

    def calculate_stop_loss_take_profit(
        self,
        stock_code: str,
        entry_price: float,
        direction: str = "long",
    ) -> Optional[StopLossTakeProfitLevels]:
        """
        计算止损止盈价位

        Args:
            stock_code: 股票代码
            entry_price: 入场价
            direction: 方向（"long" 或 "short"，目前只支持 long）

        Returns:
            StopLossTakeProfitLevels 对象，如果 ATR 数据不足则返回 None
        """
        atr = self.get_atr(stock_code)

        if atr is None or atr <= 0:
            logger.warning(f"[{stock_code}] ATR 数据不足，无法计算止损止盈")
            return None

        if direction == "long":
            stop_loss = entry_price - (self.stop_loss_multiplier * atr)
            take_profit = entry_price + (self.take_profit_multiplier * atr)
        else:
            # 暂不支持做空
            logger.warning(f"[{stock_code}] 暂不支持做空方向的止损止盈计算")
            return None

        return StopLossTakeProfitLevels(
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            atr_value=atr,
        )

    def update_trailing_take_profit(
        self,
        levels: StopLossTakeProfitLevels,
        current_price: float,
    ) -> StopLossTakeProfitLevels:
        """
        更新追踪止盈价位

        当价格达到初始止盈目标后，启动追踪止盈：
        - 价格每上涨 0.5 * ATR，止盈价上移 0.3 * ATR
        - 直到价格回撤触发止盈

        Args:
            levels: 当前止损止盈价位
            current_price: 当前价格

        Returns:
            更新后的 StopLossTakeProfitLevels 对象
        """
        # 如果价格还未达到初始止盈目标，不启动追踪
        if current_price < levels.take_profit:
            return levels

        # 如果还未启动追踪止盈，初始化为初始止盈价
        if levels.trailing_take_profit is None:
            levels.trailing_take_profit = levels.take_profit

        # 计算价格相对入场价的涨幅（以 ATR 为单位）
        price_gain_in_atr = (current_price - levels.entry_price) / levels.atr_value

        # 计算应该上移的次数
        trigger_threshold = self.take_profit_multiplier + self.trailing_trigger_multiplier
        if price_gain_in_atr >= trigger_threshold:
            # 计算新的追踪止盈价
            num_steps = int((price_gain_in_atr - self.take_profit_multiplier) / self.trailing_trigger_multiplier)
            new_trailing = levels.take_profit + (num_steps * self.trailing_step_multiplier * levels.atr_value)

            # 只有当新价格更高时才更新
            if new_trailing > levels.trailing_take_profit:
                levels.trailing_take_profit = new_trailing
                logger.info(
                    f"追踪止盈上移: 入场价={levels.entry_price:.3f}, "
                    f"当前价={current_price:.3f}, "
                    f"新止盈价={levels.trailing_take_profit:.3f}"
                )

        return levels

    def should_stop_loss(self, levels: StopLossTakeProfitLevels, current_price: float) -> bool:
        """
        判断是否触发止损

        Args:
            levels: 止损止盈价位
            current_price: 当前价格

        Returns:
            True 表示触发止损
        """
        return current_price <= levels.stop_loss

    def should_take_profit(self, levels: StopLossTakeProfitLevels, current_price: float) -> bool:
        """
        判断是否触发止盈

        Args:
            levels: 止损止盈价位
            current_price: 当前价格

        Returns:
            True 表示触发止盈
        """
        # 如果已启动追踪止盈，使用追踪止盈价
        if levels.trailing_take_profit is not None:
            return current_price <= levels.trailing_take_profit

        # 否则使用初始止盈价
        return current_price >= levels.take_profit

    def reset(self, stock_code: str) -> None:
        """
        重置指定股票的数据

        Args:
            stock_code: 股票代码
        """
        if stock_code in self._kline_data:
            del self._kline_data[stock_code]
        if stock_code in self._atr_values:
            del self._atr_values[stock_code]