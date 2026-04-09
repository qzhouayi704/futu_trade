"""
行动评分器（Action Scorer）

基于 PatternDetector 检测到的行为模式 + 环境因子，
使用加分制综合评估做多/做空/离场机会。

≥ 4 分 → 关注提示（黄色）
≥ 6 分 → 行动提示（绿色/红色高亮）
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .pattern_detector import PatternAlert

logger = logging.getLogger("scalping")


@dataclass
class ActionSignal:
    """行动信号"""
    stock_code: str
    action: str             # "long" / "short" / "exit_long" / "exit_short"
    score: float            # 总分
    level: str              # "watch" (≥4) / "action" (≥6)
    components: list[dict]  # 各因子明细 [{name, score, detail}]
    stop_loss_ref: Optional[float]  # 参考止损价
    timestamp: str

    def to_dict(self) -> dict:
        return {
            "stock_code": self.stock_code,
            "action": self.action,
            "score": self.score,
            "level": self.level,
            "components": self.components,
            "stop_loss_ref": self.stop_loss_ref,
            "timestamp": self.timestamp,
        }


class ActionScorer:
    """行动评分器

    综合 PatternAlert + 环境因子，输出加分制评分。
    每次 PatternDetector 检测完成后调用。
    """

    WATCH_THRESHOLD = 4.0
    ACTION_THRESHOLD = 6.0

    def evaluate(
        self,
        stock_code: str,
        pattern_alerts: list[PatternAlert],
        current_price: float,
        delta_recent_sum: float,
        vwap_value: Optional[float] = None,
        poc_price: Optional[float] = None,
        support_prices: Optional[list[float]] = None,
        resistance_prices: Optional[list[float]] = None,
        ofi_value: Optional[float] = None,
        tick_size: float = 0.01,
    ) -> list[ActionSignal]:
        """评估做多/做空行动信号

        Returns:
            ActionSignal 列表（可能同时有做多和做空信号）
        """
        signals = []

        long_signal = self._score_long(
            stock_code, pattern_alerts, current_price,
            delta_recent_sum, vwap_value, poc_price,
            support_prices, ofi_value, tick_size,
        )
        if long_signal:
            signals.append(long_signal)

        short_signal = self._score_short(
            stock_code, pattern_alerts, current_price,
            delta_recent_sum, vwap_value, poc_price,
            resistance_prices, ofi_value, tick_size,
        )
        if short_signal:
            signals.append(short_signal)

        return signals

    def _score_long(
        self,
        stock_code: str,
        alerts: list[PatternAlert],
        price: float,
        delta_sum: float,
        vwap: Optional[float],
        poc: Optional[float],
        supports: Optional[list[float]],
        ofi: Optional[float],
        tick_size: float,
    ) -> Optional[ActionSignal]:
        """计算做多评分"""
        components = []
        total = 0.0

        # 来自模式检测的分数（bullish 模式）
        for a in alerts:
            if a.direction == "bullish":
                total += a.score_contribution
                components.append({
                    "name": a.title,
                    "score": a.score_contribution,
                    "detail": a.description,
                })

        # 环境因子：Delta 偏多
        if delta_sum > 0:
            s = 1.0
            total += s
            components.append({
                "name": "Delta偏多",
                "score": s,
                "detail": f"近期 Delta 合计 {delta_sum:+.0f}",
            })

        # 环境因子：价格在 VWAP 下方（有回归空间）
        if vwap and price < vwap:
            deviation = (vwap - price) / vwap * 100
            if deviation > 0.3:
                s = 1.0
                total += s
                components.append({
                    "name": "VWAP下方",
                    "score": s,
                    "detail": f"低于 VWAP {deviation:.1f}%，有回归空间",
                })

        # 环境因子：OFI（参考权重低）
        if ofi is not None and ofi > 0.2:
            s = 0.5
            total += s
            components.append({
                "name": "盘口偏多",
                "score": s,
                "detail": f"OFI={ofi:.2f}（参考）",
            })

        if total < self.WATCH_THRESHOLD:
            return None

        # 止损参考：最近支撑下方 3 Tick
        stop_loss = None
        if supports:
            nearest = min(supports, key=lambda sp: abs(price - sp))
            stop_loss = nearest - 3 * tick_size
        elif poc and price >= poc:
            stop_loss = poc - 3 * tick_size

        level = "action" if total >= self.ACTION_THRESHOLD else "watch"

        return ActionSignal(
            stock_code=stock_code,
            action="long",
            score=total,
            level=level,
            components=components,
            stop_loss_ref=round(stop_loss, 3) if stop_loss else None,
            timestamp=datetime.now().isoformat(),
        )

    def _score_short(
        self,
        stock_code: str,
        alerts: list[PatternAlert],
        price: float,
        delta_sum: float,
        vwap: Optional[float],
        poc: Optional[float],
        resistances: Optional[list[float]],
        ofi: Optional[float],
        tick_size: float,
    ) -> Optional[ActionSignal]:
        """计算做空/离场评分"""
        components = []
        total = 0.0

        # 来自模式检测的分数（bearish 模式）
        for a in alerts:
            if a.direction == "bearish":
                total += a.score_contribution
                components.append({
                    "name": a.title,
                    "score": a.score_contribution,
                    "detail": a.description,
                })

        # 环境因子：Delta 偏空
        if delta_sum < 0:
            s = 1.0
            total += s
            components.append({
                "name": "Delta偏空",
                "score": s,
                "detail": f"近期 Delta 合计 {delta_sum:+.0f}",
            })

        # 环境因子：VWAP 上方偏离大
        if vwap and price > vwap:
            deviation = (price - vwap) / vwap * 100
            if deviation > 1.0:
                s = 1.0
                total += s
                components.append({
                    "name": "VWAP上方偏离",
                    "score": s,
                    "detail": f"高于 VWAP {deviation:.1f}%，回归风险大",
                })

        # 环境因子：OFI（参考权重低）
        if ofi is not None and ofi < -0.2:
            s = 0.5
            total += s
            components.append({
                "name": "盘口偏空",
                "score": s,
                "detail": f"OFI={ofi:.2f}（参考）",
            })

        if total < self.WATCH_THRESHOLD:
            return None

        # 止损参考：最近阻力上方 3 Tick
        stop_loss = None
        if resistances:
            nearest = min(resistances, key=lambda rp: abs(price - rp))
            stop_loss = nearest + 3 * tick_size
        elif poc and price <= poc:
            stop_loss = poc + 3 * tick_size

        level = "action" if total >= self.ACTION_THRESHOLD else "watch"

        return ActionSignal(
            stock_code=stock_code,
            action="short",
            score=total,
            level=level,
            components=components,
            stop_loss_ref=round(stop_loss, 3) if stop_loss else None,
            timestamp=datetime.now().isoformat(),
        )
