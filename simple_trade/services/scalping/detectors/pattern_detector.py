"""
行为模式检测器（Pattern Detector）

每次 Delta flush 时由 ScalpingEngine 调用，基于最近的 Delta 历史
检测 8 种日内交易行为模式，通过 Socket 推送预警。

模式清单：
1. 诱多出货 — 价格涨 + 量缩 + 无大单
2. 压价吸筹 — 价格跌 + 量缩 + 无大卖单
3. 放量滞涨 — 价格横盘 + 量大 + Delta 转负
4. 缩量企稳 — 支撑位 + 量缩 + 价格不跌
5. 洗盘 — 急跌放量 + 快速恢复
6. 量价齐升 — 价格涨 + 量增 + Delta 正
7. 量价齐跌 — 价格跌 + 量增 + Delta 负
8. 流量突变 — Delta 符号大幅翻转
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger("scalping")

# 模式冷却期（秒）：同模式同股票在此时间内不重复触发
_PATTERN_COOLDOWN = 30.0


@dataclass
class PatternAlert:
    """行为模式预警"""
    stock_code: str
    pattern_type: str       # 模式标识
    direction: str          # "bullish" / "bearish" / "neutral"
    title: str              # 简短标题
    description: str        # 预警文案
    severity: str           # "warning" / "danger" / "info"
    score_contribution: float  # 对行动评分的贡献
    timestamp: str

    def to_dict(self) -> dict:
        return {
            "stock_code": self.stock_code,
            "pattern_type": self.pattern_type,
            "direction": self.direction,
            "title": self.title,
            "description": self.description,
            "severity": self.severity,
            "score_contribution": self.score_contribution,
            "timestamp": self.timestamp,
        }


@dataclass
class _DeltaPeriod:
    """简化的 Delta 周期数据（从 DeltaUpdateData 提取关键字段）"""
    delta: float
    volume: int
    open_price: float
    close_price: float
    high_price: float
    low_price: float
    big_order_volume: int
    timestamp: str


class PatternDetector:
    """行为模式检测器

    每次 Delta flush 后调用 detect()，基于最近 N 期 Delta 历史
    检测 8 种日内交易行为模式。
    """

    def __init__(
        self,
        lookback: int = 20,
        big_order_ratio_threshold: float = 0.10,
        volume_shrink_ratio: float = 0.85,
        volume_surge_ratio: float = 1.5,
        price_stall_ticks: int = 2,
        tick_size: float = 0.01,
    ):
        self._lookback = lookback
        self._big_order_threshold = big_order_ratio_threshold
        self._volume_shrink = volume_shrink_ratio
        self._volume_surge = volume_surge_ratio
        self._price_stall_ticks = price_stall_ticks
        self._tick_size = tick_size
        # 冷却期：(stock_code, pattern_type) -> 冷却结束 ISO 时间
        self._cooldowns: dict[tuple[str, str], float] = {}

    def detect(
        self,
        stock_code: str,
        delta_history: list,
        poc_price: Optional[float] = None,
        support_prices: Optional[list[float]] = None,
        vwap_value: Optional[float] = None,
    ) -> list[PatternAlert]:
        """检测所有行为模式

        Args:
            stock_code: 股票代码
            delta_history: 最近 N 期 DeltaUpdateData 列表
            poc_price: POC 价格
            support_prices: 支撑位价格列表
            vwap_value: VWAP 值

        Returns:
            检测到的 PatternAlert 列表
        """
        if len(delta_history) < 4:
            return []

        # 转换为简化结构
        periods = self._to_periods(delta_history)
        if len(periods) < 4:
            return []

        now = datetime.now().timestamp()
        alerts: list[PatternAlert] = []

        # 计算基准值
        volumes = [p.volume for p in periods]
        avg_vol = sum(volumes) / len(volumes) if volumes else 1
        deltas = [p.delta for p in periods]
        avg_delta = sum(abs(d) for d in deltas) / len(deltas) if deltas else 1

        recent3 = periods[-3:]
        latest = periods[-1]
        current_price = latest.close_price

        # === 模式 1: 诱多出货 ===
        alert = self._check_fake_rally(stock_code, recent3, now)
        if alert:
            alerts.append(alert)

        # === 模式 2: 压价吸筹 ===
        alert = self._check_fake_drop(stock_code, recent3, now)
        if alert:
            alerts.append(alert)

        # === 模式 3: 放量滞涨 ===
        alert = self._check_volume_stall_top(stock_code, recent3, avg_vol, now)
        if alert:
            alerts.append(alert)

        # === 模式 4: 缩量企稳 ===
        alert = self._check_volume_dry_bottom(
            stock_code, recent3, avg_vol, current_price,
            poc_price, support_prices, now,
        )
        if alert:
            alerts.append(alert)

        # === 模式 5: 洗盘 ===
        if len(periods) >= 4:
            alert = self._check_shakeout(stock_code, periods[-4:], avg_delta, avg_vol, now)
            if alert:
                alerts.append(alert)

        # === 模式 6: 量价齐升 ===
        alert = self._check_vol_price_up(stock_code, recent3, avg_delta, now)
        if alert:
            alerts.append(alert)

        # === 模式 7: 量价齐跌 ===
        alert = self._check_vol_price_down(stock_code, recent3, avg_delta, now)
        if alert:
            alerts.append(alert)

        # === 模式 8: 流量突变 ===
        if len(periods) >= 4:
            alert = self._check_flow_reversal(stock_code, periods[-4:], avg_delta, now)
            if alert:
                alerts.append(alert)

        return alerts

    # ================================================================
    # 8 种模式检测
    # ================================================================

    def _check_fake_rally(
        self, code: str, r3: list[_DeltaPeriod], now: float,
    ) -> Optional[PatternAlert]:
        """模式1: 诱多出货 — 价格涨+量缩+无大单"""
        if self._in_cooldown(code, "fake_rally", now):
            return None
        # 价格连涨
        if not all(p.close_price > p.open_price for p in r3):
            return None
        # 成交量递减
        vols = [p.volume for p in r3]
        if not (vols[0] > vols[1] > vols[2]):
            return None
        # 大单占比低
        total_vol = sum(p.volume for p in r3) or 1
        big_vol = sum(p.big_order_volume for p in r3)
        if big_vol / total_vol > self._big_order_threshold:
            return None

        self._set_cooldown(code, "fake_rally", now)
        return PatternAlert(
            stock_code=code,
            pattern_type="fake_rally",
            direction="bearish",
            title="虚假上涨",
            description=f"价格涨但量缩({vols[2]}←{vols[0]})、无大单({big_vol/total_vol:.0%})，警惕诱多",
            severity="warning",
            score_contribution=2.0,
            timestamp=datetime.now().isoformat(),
        )

    def _check_fake_drop(
        self, code: str, r3: list[_DeltaPeriod], now: float,
    ) -> Optional[PatternAlert]:
        """模式2: 压价吸筹 — 价格跌+量缩+无大卖单"""
        if self._in_cooldown(code, "fake_drop", now):
            return None
        if not all(p.close_price < p.open_price for p in r3):
            return None
        vols = [p.volume for p in r3]
        if not (vols[0] > vols[1] > vols[2]):
            return None
        total_vol = sum(p.volume for p in r3) or 1
        big_vol = sum(p.big_order_volume for p in r3)
        if big_vol / total_vol > self._big_order_threshold:
            return None

        self._set_cooldown(code, "fake_drop", now)
        return PatternAlert(
            stock_code=code,
            pattern_type="fake_drop",
            direction="bullish",
            title="虚假下跌",
            description=f"价格跌但量缩({vols[2]}←{vols[0]})、无大卖单，可能压价吸筹",
            severity="warning",
            score_contribution=2.0,
            timestamp=datetime.now().isoformat(),
        )

    def _check_volume_stall_top(
        self, code: str, r3: list[_DeltaPeriod], avg_vol: float, now: float,
    ) -> Optional[PatternAlert]:
        """模式3: 放量滞涨 — 价格横盘+量大+Delta转负"""
        if self._in_cooldown(code, "vol_stall_top", now):
            return None
        # 价格停滞
        prices = [p.close_price for p in r3]
        price_range = max(prices) - min(prices)
        if price_range > self._price_stall_ticks * self._tick_size:
            return None
        # 成交量放大
        recent_vol = sum(p.volume for p in r3) / 3
        if recent_vol < avg_vol * self._volume_surge:
            return None
        # Delta 转负
        if not (r3[-1].delta < 0 and r3[-2].delta < 0):
            return None

        self._set_cooldown(code, "vol_stall_top", now)
        return PatternAlert(
            stock_code=code,
            pattern_type="vol_stall_top",
            direction="bearish",
            title="放量滞涨",
            description=f"高位放量({recent_vol:.0f} vs 均值{avg_vol:.0f})但价格不涨，Delta转负，警惕出货",
            severity="danger",
            score_contribution=3.0,
            timestamp=datetime.now().isoformat(),
        )

    def _check_volume_dry_bottom(
        self, code: str, r3: list[_DeltaPeriod], avg_vol: float,
        current_price: float, poc: Optional[float],
        supports: Optional[list[float]], now: float,
    ) -> Optional[PatternAlert]:
        """模式4: 缩量企稳 — 支撑位+量缩+价格不跌"""
        if self._in_cooldown(code, "vol_dry_bottom", now):
            return None
        # 接近支撑
        near_support = False
        ref_price = None
        if poc and abs(current_price - poc) <= 5 * self._tick_size:
            near_support = True
            ref_price = poc
        if not near_support and supports:
            for sp in supports:
                if abs(current_price - sp) <= 5 * self._tick_size:
                    near_support = True
                    ref_price = sp
                    break
        if not near_support:
            return None
        # 成交量萎缩
        recent_vol = sum(p.volume for p in r3) / 3
        if recent_vol > avg_vol * 0.6:
            return None
        # 价格企稳
        prices = [p.close_price for p in r3]
        price_range = max(prices) - min(prices)
        if price_range > self._price_stall_ticks * self._tick_size:
            return None

        self._set_cooldown(code, "vol_dry_bottom", now)
        return PatternAlert(
            stock_code=code,
            pattern_type="vol_dry_bottom",
            direction="bullish",
            title="缩量企稳",
            description=f"支撑{ref_price:.2f}附近量缩({recent_vol:.0f} vs 均值{avg_vol:.0f})价稳，卖压耗尽",
            severity="info",
            score_contribution=3.0,
            timestamp=datetime.now().isoformat(),
        )

    def _check_shakeout(
        self, code: str, r4: list[_DeltaPeriod], avg_delta: float,
        avg_vol: float, now: float,
    ) -> Optional[PatternAlert]:
        """模式5: 洗盘 — 急跌放量+快速恢复"""
        if self._in_cooldown(code, "shakeout", now):
            return None
        # 寻找急跌期（倒数第 2 或 3 期）
        for i in range(len(r4) - 2, 0, -1):
            spike = r4[i]
            recovery = r4[i + 1]
            # 急跌：Delta 极端负值
            if spike.delta >= -avg_delta * 2:
                continue
            # 放量
            if spike.volume < avg_vol * 2:
                continue
            # 快速恢复：下期价格收回跌幅 70%+
            drop = spike.open_price - spike.low_price
            if drop <= 0:
                continue
            recovered = recovery.close_price - spike.low_price
            if recovered / drop < 0.7:
                continue

            self._set_cooldown(code, "shakeout", now)
            return PatternAlert(
                stock_code=code,
                pattern_type="shakeout",
                direction="bullish",
                title="疑似洗盘",
                description=f"急跌(Delta={spike.delta:.0f})后快速收回{recovered/drop:.0%}，止损盘被扫",
                severity="warning",
                score_contribution=2.0,
                timestamp=datetime.now().isoformat(),
            )
        return None

    def _check_vol_price_up(
        self, code: str, r3: list[_DeltaPeriod], avg_delta: float, now: float,
    ) -> Optional[PatternAlert]:
        """模式6: 量价齐升 — 价格涨+量增+Delta正"""
        if self._in_cooldown(code, "vol_price_up", now):
            return None
        if not all(p.close_price > p.open_price for p in r3):
            return None
        vols = [p.volume for p in r3]
        if not (vols[2] > vols[1] > vols[0]):
            return None
        total_delta = sum(p.delta for p in r3)
        if total_delta < avg_delta * 1.5:
            return None

        self._set_cooldown(code, "vol_price_up", now)
        return PatternAlert(
            stock_code=code,
            pattern_type="vol_price_up",
            direction="bullish",
            title="量价齐升",
            description=f"价格涨+量增+Delta强正({total_delta:.0f})，趋势健康",
            severity="info",
            score_contribution=2.0,
            timestamp=datetime.now().isoformat(),
        )

    def _check_vol_price_down(
        self, code: str, r3: list[_DeltaPeriod], avg_delta: float, now: float,
    ) -> Optional[PatternAlert]:
        """模式7: 量价齐跌 — 价格跌+量增+Delta负"""
        if self._in_cooldown(code, "vol_price_down", now):
            return None
        if not all(p.close_price < p.open_price for p in r3):
            return None
        vols = [p.volume for p in r3]
        if not (vols[2] > vols[1] > vols[0]):
            return None
        total_delta = sum(p.delta for p in r3)
        if total_delta > -avg_delta * 1.5:
            return None

        self._set_cooldown(code, "vol_price_down", now)
        return PatternAlert(
            stock_code=code,
            pattern_type="vol_price_down",
            direction="bearish",
            title="量价齐跌",
            description=f"价格跌+量增+Delta强负({total_delta:.0f})，回避做多",
            severity="danger",
            score_contribution=2.0,
            timestamp=datetime.now().isoformat(),
        )

    def _check_flow_reversal(
        self, code: str, r4: list[_DeltaPeriod], avg_delta: float, now: float,
    ) -> Optional[PatternAlert]:
        """模式8: 流量突变 — Delta符号大幅翻转"""
        if self._in_cooldown(code, "flow_reversal", now):
            return None
        prev_sum = sum(p.delta for p in r4[:-1])
        latest = r4[-1].delta
        # 符号翻转且力度够大
        if prev_sum * latest >= 0:
            return None
        if abs(latest) < avg_delta * 1.5:
            return None

        direction = "bullish" if latest > 0 else "bearish"
        arrow = "空→多" if latest > 0 else "多→空"
        self._set_cooldown(code, "flow_reversal", now)
        return PatternAlert(
            stock_code=code,
            pattern_type="flow_reversal",
            direction=direction,
            title="流量突变",
            description=f"流量{arrow} | Delta {latest:+.0f} (均值 {avg_delta:.0f})",
            severity="warning",
            score_contribution=1.0,
            timestamp=datetime.now().isoformat(),
        )

    # ================================================================
    # 辅助方法
    # ================================================================

    def _to_periods(self, delta_history: list) -> list[_DeltaPeriod]:
        """将 DeltaUpdateData 转为简化结构"""
        periods = []
        for d in delta_history[-self._lookback:]:
            try:
                periods.append(_DeltaPeriod(
                    delta=d.delta if hasattr(d, 'delta') else d.get('delta', 0),
                    volume=d.volume if hasattr(d, 'volume') else d.get('volume', 0),
                    open_price=d.open_price if hasattr(d, 'open_price') else d.get('open_price', 0),
                    close_price=d.close_price if hasattr(d, 'close_price') else d.get('close_price', 0),
                    high_price=d.high_price if hasattr(d, 'high_price') else d.get('high_price', 0),
                    low_price=d.low_price if hasattr(d, 'low_price') else d.get('low_price', 0),
                    big_order_volume=d.big_order_volume if hasattr(d, 'big_order_volume') else d.get('big_order_volume', 0),
                    timestamp=d.timestamp if hasattr(d, 'timestamp') else d.get('timestamp', ''),
                ))
            except Exception:
                continue
        return periods

    def _in_cooldown(self, code: str, pattern: str, now: float) -> bool:
        key = (code, pattern)
        return now < self._cooldowns.get(key, 0)

    def _set_cooldown(self, code: str, pattern: str, now: float) -> None:
        self._cooldowns[(code, pattern)] = now + _PATTERN_COOLDOWN

    def reset(self, stock_code: str) -> None:
        """重置指定股票的冷却期"""
        keys_to_remove = [k for k in self._cooldowns if k[0] == stock_code]
        for k in keys_to_remove:
            del self._cooldowns[k]
