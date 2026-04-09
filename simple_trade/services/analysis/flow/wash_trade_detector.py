#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对倒/虚假资金检测器 + 资金可信度评估

检测模式:
  1. 对倒 (wash_trade): 短窗口内同价位买卖量对称
  2. 虚假深度 (fake_depth): 大单成交但盘口深度无显著变化
  3. OFI背离 (ofi_divergence): Delta>0但OFI持续为负

资金可信度: 根据告警历史扣分, base=1.0
"""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from simple_trade.services.scalping.engine import ScalpingEngine

logger = logging.getLogger("scalping.wash_trade")

# 窗口配置
_WASH_WINDOW_SEC = 10      # 对倒检测窗口(秒)
_SYMMETRY_THRESHOLD = 0.35 # 买卖对称度阈值
_VOLUME_RATIO_MIN = 0.05   # 同价占比最低阈值
_OFI_NEG_RATIO = 0.6       # OFI背离: 负值占比阈值
_ALERT_COOLDOWN = 60       # 同类告警冷却时间(秒)


@dataclass
class WashTradeAlert:
    """对倒/虚假资金告警"""
    stock_code: str
    alert_type: str       # "wash_trade" / "fake_depth" / "ofi_divergence"
    severity: str         # "high" / "medium" / "low"
    description: str
    timestamp: float


@dataclass
class _TickWindow:
    """短窗口Tick聚合"""
    price_buys: dict = field(default_factory=lambda: defaultdict(float))
    price_sells: dict = field(default_factory=lambda: defaultdict(float))
    total_volume: float = 0.0
    start_time: float = 0.0


class WashTradeDetector:
    """对倒/虚假资金检测器"""

    def __init__(self, engine: "ScalpingEngine"):
        self._engine = engine
        # stock_code → _TickWindow
        self._windows: dict[str, _TickWindow] = {}
        # stock_code → [WashTradeAlert] (最近10条)
        self._alerts: dict[str, list[WashTradeAlert]] = defaultdict(list)
        # 冷却: (stock_code, alert_type) → last_alert_time
        self._cooldown: dict[tuple[str, str], float] = {}

    def on_tick(self, stock_code: str, price: float, volume: float,
                is_buy: bool, timestamp: float) -> Optional[WashTradeAlert]:
        """逐笔成交回调 — 对倒检测"""
        w = self._windows.get(stock_code)
        now = timestamp or time.time()

        # 窗口过期则重置
        if w is None or (now - w.start_time) > _WASH_WINDOW_SEC:
            w = _TickWindow(start_time=now)
            self._windows[stock_code] = w

        # 按价位聚合买卖量
        price_key = f"{price:.4f}"
        if is_buy:
            w.price_buys[price_key] += volume
        else:
            w.price_sells[price_key] += volume
        w.total_volume += volume

        # 窗口内数据量不足则跳过检测
        if w.total_volume < 100:
            return None

        # 检测同价位买卖对称
        alert = self._check_wash_trade(stock_code, w, now)
        return alert

    def on_order_book(self, stock_code: str, bid_depths: list[float],
                      ask_depths: list[float], timestamp: float) -> Optional[WashTradeAlert]:
        """盘口更新回调 — 虚假深度检测（简化版）"""
        # 简化: 检测盘口总深度是否与大单成交匹配
        # 完整实现需记录前后盘口状态差异, 这里用简化逻辑
        return None  # 后续迭代实现

    def check_ofi_divergence(self, stock_code: str) -> Optional[WashTradeAlert]:
        """OFI背离检测 — 在 publish_scalping_metrics 中调用"""
        try:
            e = self._engine
            # 检查近期Delta是否为正（"资金流入"）
            recent = e._delta_calculator.get_recent_deltas(stock_code, 3)
            if not recent or len(recent) < 2:
                return None
            avg_delta = sum(d.delta for d in recent) / len(recent)
            if avg_delta <= 0:
                return None  # Delta非正, 不需检测

            # 检查OFI是否持续为负
            ofi_calc = e._ofi_calculator
            if not ofi_calc:
                return None
            history = ofi_calc.get_history(stock_code)
            if not history or len(history) < 3:
                return None
            recent_ofi = [v for _, v in history[-5:]]
            neg_count = sum(1 for v in recent_ofi if v < 0)
            neg_ratio = neg_count / len(recent_ofi)

            if neg_ratio >= _OFI_NEG_RATIO:
                return self._emit_alert(
                    stock_code, "ofi_divergence", "medium",
                    f"Delta显示资金流入但OFI有{neg_ratio:.0%}为负, 盘口卖压实际偏强"
                )
        except Exception:
            pass
        return None

    def get_alerts(self, stock_code: str, limit: int = 5) -> list[WashTradeAlert]:
        """获取指定股票的最近告警"""
        return self._alerts.get(stock_code, [])[-limit:]

    def evaluate_credibility(self, stock_code: str) -> tuple[float, list[str]]:
        """评估资金可信度: 返回 (0~1的可信度, 风险因素列表)"""
        alerts = self._alerts.get(stock_code, [])
        now = time.time()
        # 只考虑最近5分钟的告警
        recent = [a for a in alerts if now - a.timestamp < 300]

        base = 1.0
        factors = []
        penalties = {
            "wash_trade": 0.3,
            "fake_depth": 0.2,
            "ofi_divergence": 0.15,
        }
        seen_types = set()
        for alert in recent:
            if alert.alert_type not in seen_types:
                seen_types.add(alert.alert_type)
                penalty = penalties.get(alert.alert_type, 0.1)
                base -= penalty
                factor_names = {
                    "wash_trade": "检测到对倒交易",
                    "fake_depth": "盘口深度异常",
                    "ofi_divergence": "资金方向与盘口矛盾",
                }
                factors.append(factor_names.get(alert.alert_type, alert.alert_type))

        return max(0.0, round(base, 2)), factors

    # ---- 内部方法 ----

    def _check_wash_trade(self, stock_code: str, w: _TickWindow,
                          now: float) -> Optional[WashTradeAlert]:
        """检测窗口内同价位买卖对称"""
        if w.total_volume <= 0:
            return None

        total_symmetric = 0.0
        for price_key in set(w.price_buys.keys()) & set(w.price_sells.keys()):
            buy_vol = w.price_buys[price_key]
            sell_vol = w.price_sells[price_key]
            if buy_vol > 0 and sell_vol > 0:
                symmetry = min(buy_vol, sell_vol) / max(buy_vol, sell_vol)
                if symmetry > _SYMMETRY_THRESHOLD:
                    total_symmetric += min(buy_vol, sell_vol) * 2

        sym_ratio = total_symmetric / w.total_volume
        if sym_ratio > _VOLUME_RATIO_MIN:
            return self._emit_alert(
                stock_code, "wash_trade",
                "high" if sym_ratio > 0.15 else "medium",
                f"同价位买卖对称度{sym_ratio:.0%}, 疑似对倒"
            )
        return None

    def _emit_alert(self, stock_code: str, alert_type: str,
                    severity: str, desc: str) -> Optional[WashTradeAlert]:
        """发出告警（带冷却）"""
        now = time.time()
        key = (stock_code, alert_type)
        last = self._cooldown.get(key, 0)
        if now - last < _ALERT_COOLDOWN:
            return None

        self._cooldown[key] = now
        alert = WashTradeAlert(
            stock_code=stock_code,
            alert_type=alert_type,
            severity=severity,
            description=desc,
            timestamp=now,
        )
        self._alerts[stock_code].append(alert)
        # 保留最近10条
        if len(self._alerts[stock_code]) > 10:
            self._alerts[stock_code] = self._alerts[stock_code][-10:]

        logger.info(f"[{stock_code}] 🔶 {alert_type}: {desc}")
        return alert
