"""
计算调度器 - 管理 POC/Delta 定期计算和指标发布。

从 engine.py 中提取，负责：
- _maybe_calc_poc()：定期 POC 计算
- _maybe_flush_delta()：定期 Delta flush
- _publish_scalping_metrics()：指标快照写入 StateManager
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from simple_trade.services.scalping.engine import ScalpingEngine

logger = logging.getLogger("scalping")

# POC 计算间隔（秒）
_POC_CALC_INTERVAL = 5.0
# Delta flush 间隔（秒）
_DELTA_FLUSH_INTERVAL = 10.0


class CalculationScheduler:
    """计算调度器 - 定期执行 POC 计算和 Delta flush"""

    def __init__(self, engine: "ScalpingEngine"):
        self._engine = engine
        self._last_poc_calc: dict[str, float] = {}
        self._last_delta_flush: dict[str, float] = {}

    # ------------------------------------------------------------------
    # POC 定期计算
    # ------------------------------------------------------------------

    async def maybe_calc_poc(
        self, stock_code: str, now_sec: float
    ) -> None:
        """每 _POC_CALC_INTERVAL 秒计算 POC"""
        last = self._last_poc_calc.get(stock_code, 0.0)
        if now_sec - last >= _POC_CALC_INTERVAL:
            self._last_poc_calc[stock_code] = now_sec
            try:
                await self._engine._poc_calculator.calculate_poc(stock_code)
            except Exception as e:
                logger.warning(f"[{stock_code}] calculate_poc 异常: {e}")

    # ------------------------------------------------------------------
    # Delta 定期 flush
    # ------------------------------------------------------------------

    async def maybe_flush_delta(
        self, stock_code: str, now_sec: float
    ) -> None:
        """每 _DELTA_FLUSH_INTERVAL 秒 flush Delta 累加数据"""
        last = self._last_delta_flush.get(stock_code, 0.0)
        if now_sec - last >= _DELTA_FLUSH_INTERVAL:
            self._last_delta_flush[stock_code] = now_sec
            # 先读取大单占比（flush 会重置 current_period 导致数据丢失）
            big_ratio = self._engine._delta_calculator.get_big_order_ratio(stock_code)
            try:
                await self._engine._delta_calculator.flush_period(stock_code)
            except Exception as e:
                logger.warning(
                    f"[{stock_code}] flush_period 异常: {e}"
                )
            # flush 后将指标快照写入 StateManager 供 Strategy 系统消费
            self.publish_scalping_metrics(stock_code, big_ratio)

    # ------------------------------------------------------------------
    # 指标发布
    # ------------------------------------------------------------------

    def publish_scalping_metrics(self, stock_code: str, big_ratio: float | None = None) -> None:
        """收集各计算器指标，写入 StateManager 供 Strategy 系统消费"""
        e = self._engine
        if e._state_manager is None:
            return
        try:
            from simple_trade.core.state.scalping_metrics import ScalpingMetrics

            # Delta
            recent = e._delta_calculator.get_recent_deltas(stock_code, 1)
            delta_val = recent[-1].delta if recent else 0.0
            delta_vol = recent[-1].volume if recent else 0
            if delta_val > 0:
                direction = "bullish"
            elif delta_val < 0:
                direction = "bearish"
            else:
                direction = "neutral"
            if big_ratio is None:
                big_ratio = e._delta_calculator.get_big_order_ratio(stock_code)

            # POC
            poc_price = 0.0
            poc_buy_ratio = 0.5
            poc_state = e._poc_calculator._states.get(stock_code)
            if poc_state and poc_state.last_poc_price is not None:
                poc_price = poc_state.last_poc_price
                price_key = f"{poc_price:.4f}"
                vbin = poc_state.volume_bins.get(price_key)
                if vbin:
                    poc_buy_ratio = vbin.buy_ratio

            # Tape Velocity
            tv_count = e._tape_velocity.get_window_count(stock_code)
            tv_baseline = e._tape_velocity.get_baseline_avg(stock_code)
            is_ignited = (
                tv_baseline > 0
                and tv_count / tv_baseline >= e._tape_velocity._ignition_multiplier
            ) if tv_baseline > 0 else False

            metrics = ScalpingMetrics(
                delta=delta_val,
                delta_volume=delta_vol,
                delta_direction=direction,
                big_order_ratio=round(big_ratio, 4),
                poc_price=poc_price,
                poc_buy_ratio=round(poc_buy_ratio, 3),
                tape_velocity_count=tv_count,
                tape_velocity_baseline=round(tv_baseline, 2),
                is_ignited=is_ignited,
            )
            e._state_manager.set_scalping_metrics(stock_code, metrics)
        except Exception as e:
            logger.debug(f"[{stock_code}] 发布 Scalping 指标失败: {e}")
