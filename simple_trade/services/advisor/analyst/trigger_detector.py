#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""触发条件检测器 - 决定何时调用 Gemini 分析"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from .analyst_models import TriggerType, TriggerEvent
from ..models import Urgency, DecisionAdvice

logger = logging.getLogger(__name__)


class TriggerDetector:
    """触发条件检测器

    检测价格异动、资金异动、高紧急度建议、突发新闻等条件，
    决定何时调用 Gemini 进行深度分析。
    """

    def __init__(self, config: Optional[dict] = None):
        cfg = config or {}
        self.price_surge_threshold = cfg.get('price_surge_threshold', 2.0)
        self.price_plunge_threshold = cfg.get('price_plunge_threshold', -2.0)
        self.capital_anomaly_threshold = cfg.get('capital_anomaly_threshold', 0.5)
        self.cooldown_seconds = cfg.get('cooldown_seconds', 300)

        # 冷却记录
        self._last_trigger_time: Dict[str, datetime] = {}
        # 价格历史（用于检测1分钟内变化）
        self._price_history: Dict[str, List[Tuple[datetime, float]]] = {}

    def detect_triggers(
        self,
        quotes: List[Dict],
        advices: List[DecisionAdvice],
        news_events: Optional[List[Dict]] = None,
    ) -> List[TriggerEvent]:
        """检测所有触发条件，返回需要分析的事件列表"""
        triggers: List[TriggerEvent] = []
        triggered_codes = set()

        for quote in quotes:
            stock_code = quote.get('code', '') or quote.get('stock_code', '')
            if not stock_code or self._is_in_cooldown(stock_code):
                continue

            # 1. 价格异动检测
            price_trigger = self._detect_price_anomaly(quote)
            if price_trigger:
                triggers.append(price_trigger)
                triggered_codes.add(stock_code)
                continue

            # 2. 资金异动检测
            capital_trigger = self._detect_capital_anomaly(quote)
            if capital_trigger:
                triggers.append(capital_trigger)
                triggered_codes.add(stock_code)

        # 3. 高紧急度建议检测
        for advice in advices:
            if advice.urgency in (Urgency.CRITICAL, Urgency.HIGH):
                stock_code = advice.sell_stock_code or advice.buy_stock_code or ''
                if stock_code and stock_code not in triggered_codes:
                    if not self._is_in_cooldown(stock_code):
                        triggers.append(TriggerEvent(
                            trigger_type=TriggerType.HIGH_URGENCY_ADVICE,
                            stock_code=stock_code,
                            stock_name=advice.sell_stock_name or advice.buy_stock_name or '',
                            reason=f"规则引擎{advice.urgency.name}级别: {advice.title}",
                            priority=advice.urgency.value,
                        ))
                        triggered_codes.add(stock_code)

        # 4. 突发新闻检测
        if news_events:
            for news in news_events:
                if not news.get('is_breaking'):
                    continue
                for stock_code in news.get('related_stocks', []):
                    if stock_code not in triggered_codes and not self._is_in_cooldown(stock_code):
                        triggers.append(TriggerEvent(
                            trigger_type=TriggerType.BREAKING_NEWS,
                            stock_code=stock_code,
                            stock_name=news.get('stock_name', ''),
                            reason=f"突发新闻: {news.get('title', '')[:50]}",
                            priority=8,
                        ))
                        triggered_codes.add(stock_code)

        # 按优先级排序
        triggers.sort(key=lambda x: x.priority, reverse=True)
        return triggers

    def _detect_price_anomaly(self, quote: Dict) -> Optional[TriggerEvent]:
        """检测价格异动（1分钟内变化超过阈值）"""
        stock_code = quote.get('code', '') or quote.get('stock_code', '')
        current_price = quote.get('last_price', 0) or quote.get('price', 0)
        if not current_price or not stock_code:
            return None

        now = datetime.now()

        # 更新价格历史
        if stock_code not in self._price_history:
            self._price_history[stock_code] = []

        history = self._price_history[stock_code]
        history.append((now, current_price))

        # 清理1分钟前的数据
        cutoff = now - timedelta(minutes=1)
        history[:] = [(t, p) for t, p in history if t > cutoff]

        if len(history) < 2:
            return None

        # 计算1分钟内变化
        oldest_price = history[0][1]
        if oldest_price <= 0:
            return None
        change_pct = (current_price - oldest_price) / oldest_price * 100

        if change_pct >= self.price_surge_threshold:
            return TriggerEvent(
                trigger_type=TriggerType.PRICE_SURGE,
                stock_code=stock_code,
                stock_name=quote.get('name', quote.get('stock_name', '')),
                reason=f"1分钟内拉升 {change_pct:+.2f}%",
                priority=9,
            )
        elif change_pct <= self.price_plunge_threshold:
            return TriggerEvent(
                trigger_type=TriggerType.PRICE_PLUNGE,
                stock_code=stock_code,
                stock_name=quote.get('name', quote.get('stock_name', '')),
                reason=f"1分钟内下跌 {change_pct:+.2f}%",
                priority=10,
            )
        return None

    def _detect_capital_anomaly(self, quote: Dict) -> Optional[TriggerEvent]:
        """检测资金异动"""
        stock_code = quote.get('code', '') or quote.get('stock_code', '')
        big_order_strength = quote.get('big_order_strength', 0)

        if abs(big_order_strength) >= self.capital_anomaly_threshold:
            direction = "大单买入" if big_order_strength > 0 else "大单卖出"
            return TriggerEvent(
                trigger_type=TriggerType.CAPITAL_ANOMALY,
                stock_code=stock_code,
                stock_name=quote.get('name', quote.get('stock_name', '')),
                reason=f"{direction}强度 {big_order_strength:+.2f}",
                priority=7,
            )
        return None

    def _is_in_cooldown(self, stock_code: str) -> bool:
        """检查是否在冷却期内"""
        last_time = self._last_trigger_time.get(stock_code)
        if not last_time:
            return False
        return (datetime.now() - last_time).total_seconds() < self.cooldown_seconds

    def mark_triggered(self, stock_code: str):
        """标记已触发，开始冷却"""
        self._last_trigger_time[stock_code] = datetime.now()

    def create_manual_trigger(self, stock_code: str, stock_name: str) -> TriggerEvent:
        """创建手动触发事件"""
        return TriggerEvent(
            trigger_type=TriggerType.MANUAL,
            stock_code=stock_code,
            stock_name=stock_name,
            reason="手动触发 AI 分析",
            priority=10,
        )
