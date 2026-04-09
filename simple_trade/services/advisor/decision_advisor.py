#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""智能交易决策助理 - 核心编排引擎

场景检查逻辑已提取到 rule_checkers.py，本文件仅保留：
- evaluate 编排方法
- AI 增强
- 缓存管理 & 公开 API
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from .models import (
    AdviceType, Urgency,
    DecisionAdvice, PositionHealth, EvaluationContext,
    ADVICE_TYPE_LABELS,
)
from .health_evaluator import HealthEvaluator
from . import rule_checkers as rc

logger = logging.getLogger(__name__)


class DecisionAdvisor:
    """智能交易决策助理"""

    def __init__(
        self,
        health_evaluator: Optional[HealthEvaluator] = None,
        gemini_analyst=None,
    ):
        self._health_evaluator = health_evaluator or HealthEvaluator()
        self._gemini_analyst = gemini_analyst
        self._ai_enhanced = gemini_analyst is not None
        self._advice_cache: List[DecisionAdvice] = []
        self._health_cache: List[PositionHealth] = []
        self._last_evaluation_time: Optional[datetime] = None
        self._evaluation_history: List[Dict[str, Any]] = []
        self._max_history = 10

    def evaluate(self, ctx: EvaluationContext) -> List[DecisionAdvice]:
        """执行完整的决策评估"""
        if not ctx.positions:
            self._advice_cache = []
            self._health_cache = []
            return []

        # 1. 评估所有持仓健康度
        health_results = self._health_evaluator.evaluate_all(
            ctx.positions, ctx.quotes, ctx.kline_cache
        )
        self._health_cache = health_results
        quotes_map = ctx.quotes_map

        # 2. 调用各规则检查器（每个独立 try-except，单个失败不阻塞整体）
        advices: List[DecisionAdvice] = []
        checkers = [
            ("止损检查", lambda: rc.check_stop_loss(health_results, quotes_map)),
            ("弱势持仓", lambda: rc.check_health_advices(health_results)),
            ("换仓建议", lambda: rc.check_swap_opportunity(health_results, ctx.signals, quotes_map)),
            ("加仓建议", lambda: rc.check_add_position(health_results, quotes_map, ctx.kline_cache)),
            ("分批止盈", lambda: rc.check_partial_take_profit(ctx.positions, health_results)),
            ("持仓时间", lambda: rc.check_holding_time(health_results)),
        ]
        for name, checker in checkers:
            try:
                advices.extend(checker())
            except Exception as e:
                logger.warning(f"规则检查器[{name}]执行失败: {e}")

        # 去重 + 排序
        advices = self._deduplicate_and_sort(advices)
        self._save_to_history(advices, health_results)

        if self._is_advice_changed(advices):
            self._advice_cache = advices
            if advices:
                logger.info(f"【决策助理】生成 {len(advices)} 条建议")
        else:
            logger.debug(f"【决策助理】建议无变化，共 {len(advices)} 条")
            advices = self._advice_cache

        self._last_evaluation_time = datetime.now()
        return advices

    # ==================== AI 增强 ====================

    async def enhance_with_ai(
        self,
        advices: List[DecisionAdvice],
        ctx: EvaluationContext,
    ) -> List[DecisionAdvice]:
        """使用 Gemini 分析师对每个持仓做综合分析，可覆盖规则引擎的机械结论"""
        if not self._gemini_analyst or not self._gemini_analyst.is_available():
            return advices

        try:
            from .analyst.analyst_models import TriggerType, TriggerEvent

            quotes_map = ctx.quotes_map
            health_map = {h.stock_code: h for h in self._health_cache}

            # 为每个持仓构建分析（最多5个，按紧急度优先）
            position_codes = []
            for pos in ctx.positions:
                code = pos.get('stock_code', pos.get('code', ''))
                if code and code not in position_codes:
                    position_codes.append(code)

            # 优先分析有建议的持仓
            advised_codes = set()
            for a in advices:
                code = a.sell_stock_code or a.buy_stock_code or ''
                if code:
                    advised_codes.add(code)

            # 排序：有建议的优先
            sorted_codes = sorted(
                position_codes,
                key=lambda c: (c in advised_codes, health_map.get(c, None) is not None),
                reverse=True,
            )

            for stock_code in sorted_codes[:3]:  # 每次最多分析3个持仓
                health = health_map.get(stock_code)
                if not health:
                    continue

                # 查找该持仓对应的规则引擎建议
                matching_advice = None
                for a in advices:
                    code = a.sell_stock_code or a.buy_stock_code
                    if code == stock_code:
                        matching_advice = a
                        break

                # 如果已有 AI 分析结果，跳过
                if matching_advice and matching_advice.ai_analysis:
                    continue

                # 构建触发事件
                trigger = TriggerEvent(
                    trigger_type=TriggerType.MANUAL,
                    stock_code=stock_code,
                    stock_name=health.stock_name,
                    reason=f"持仓综合分析: {matching_advice.title if matching_advice else '定期评估'}",
                    priority=8,
                )

                rule_ref = {
                    'advice_type': matching_advice.advice_type.value,
                    'urgency': matching_advice.urgency.name,
                    'description': matching_advice.description,
                } if matching_advice else None

                health_dict = health.to_dict()

                # 构建板块信息
                sector_info = None
                plates = ctx.plate_data.get(stock_code, [])
                if plates:
                    sector_info = f"所属板块: {', '.join(plates)}"

                # 构建资金流数据
                quote = quotes_map.get(stock_code, {})
                capital_flow_data = None
                if quote:
                    capital_flow_data = {
                        'main_net_inflow': quote.get('main_net_inflow', 0),
                        'big_buy_ratio': quote.get('big_buy_ratio', 0),
                        'big_sell_ratio': quote.get('big_sell_ratio', 0),
                        'capital_score': quote.get('capital_score', 0),
                        'net_inflow_ratio': quote.get('net_inflow_ratio', 0),
                    }

                # 调用 Gemini 分析
                ai_result = await self._gemini_analyst.analyze(
                    trigger=trigger,
                    position_health=health_dict,
                    quote=quote,
                    klines=ctx.kline_cache.get(stock_code, []),
                    rule_advice=rule_ref,
                    sector_info=sector_info,
                    capital_flow_data=capital_flow_data,
                )

                if ai_result and matching_advice:
                    matching_advice.ai_analysis = ai_result.to_dict()
                    ai_tag = f"\n\n🤖 AI综合分析: {ai_result.reasoning}"
                    if ai_result.risk_warning:
                        ai_tag += f"\n⚠️ {ai_result.risk_warning}"
                    matching_advice.description += ai_tag

                    # AI 覆盖逻辑：高置信度下可修改建议紧急度
                    self._apply_ai_override(matching_advice, ai_result)

        except Exception as e:
            logger.warning(f"AI 增强失败（不影响规则引擎）: {e}")

        return advices

    @staticmethod
    def _apply_ai_override(advice: DecisionAdvice, ai_result) -> None:
        """根据 AI 分析结果调整规则引擎建议的紧急度

        当 AI 高置信度认为不应止损时，降低紧急度；
        当 AI 高置信度建议卖出但规则引擎没触发时，提升紧急度。
        """
        from .analyst.analyst_models import AnalystAction

        if ai_result.confidence < 0.6:
            return  # 置信度不够，不覆盖

        ai_action = ai_result.action

        # AI 认为应该持有/加仓，但规则引擎建议止损 → 降级紧急度
        if ai_action in (AnalystAction.HOLD, AnalystAction.BUY, AnalystAction.STRONG_BUY):
            if advice.advice_type == AdviceType.STOP_LOSS:
                if advice.urgency == Urgency.CRITICAL:
                    advice.urgency = Urgency.MEDIUM
                elif advice.urgency == Urgency.HIGH:
                    advice.urgency = Urgency.LOW
                advice.description += f"\n💡 AI建议({ai_result.confidence:.0%}置信度): 不急于止损"

        # AI 认为应该卖出，但规则引擎只建议减仓/持有 → 提升紧急度
        elif ai_action in (AnalystAction.SELL, AnalystAction.STRONG_SELL):
            if advice.advice_type in (AdviceType.REDUCE, AdviceType.HOLD):
                advice.urgency = Urgency.HIGH
                advice.description += f"\n🚨 AI建议({ai_result.confidence:.0%}置信度): 应果断卖出"

    # ==================== 工具方法 ====================

    @staticmethod
    def _deduplicate_and_sort(advices: List[DecisionAdvice]) -> List[DecisionAdvice]:
        """去重并按紧急程度排序"""
        seen: Dict[str, DecisionAdvice] = {}
        for a in advices:
            key = f"{a.sell_stock_code or ''}_{a.buy_stock_code or ''}_{a.advice_type.value}"
            existing = seen.get(key)
            if not existing or a.urgency.value > existing.urgency.value:
                seen[key] = a
        result = list(seen.values())
        result.sort(key=lambda x: x.urgency.value, reverse=True)
        return result

    def _is_advice_changed(self, new_advices: List[DecisionAdvice]) -> bool:
        """比较新旧建议列表是否有实质变化"""
        if len(new_advices) != len(self._advice_cache):
            return True
        new_fp = {self._advice_fingerprint(a) for a in new_advices}
        old_fp = {self._advice_fingerprint(a) for a in self._advice_cache}
        return new_fp != old_fp

    @staticmethod
    def _advice_fingerprint(advice: DecisionAdvice) -> str:
        return (
            f"{advice.advice_type.value}:"
            f"{advice.sell_stock_code or ''}:"
            f"{advice.buy_stock_code or ''}:"
            f"{advice.urgency.value}"
        )

    def _save_to_history(self, advices, health_results):
        record = {
            'timestamp': datetime.now().isoformat(),
            'advices': [a.to_dict() for a in advices],
            'health': [h.to_dict() for h in health_results],
            'summary': {
                'total_advices': len(advices),
                'critical_count': sum(1 for a in advices if a.urgency == Urgency.CRITICAL),
                'high_count': sum(1 for a in advices if a.urgency == Urgency.HIGH),
            }
        }
        self._evaluation_history.insert(0, record)
        if len(self._evaluation_history) > self._max_history:
            self._evaluation_history = self._evaluation_history[:self._max_history]

    # ==================== 公开 API ====================

    def get_cached_advices(self) -> List[DecisionAdvice]:
        return [a for a in self._advice_cache if not a.is_dismissed]

    def get_health_cache(self) -> List[PositionHealth]:
        return self._health_cache

    def dismiss_advice(self, advice_id: str) -> bool:
        for a in self._advice_cache:
            if a.id == advice_id:
                a.is_dismissed = True
                return True
        return False

    def get_advice_by_id(self, advice_id: str) -> Optional[DecisionAdvice]:
        for a in self._advice_cache:
            if a.id == advice_id:
                return a
        return None

    def get_summary(self) -> Dict[str, Any]:
        active = [a for a in self._advice_cache if not a.is_dismissed]
        type_counts: Dict[str, int] = {}
        for a in active:
            label = ADVICE_TYPE_LABELS.get(a.advice_type, a.advice_type.value)
            type_counts[label] = type_counts.get(label, 0) + 1
        return {
            'total_advices': len(active),
            'critical_count': sum(1 for a in active if a.urgency == Urgency.CRITICAL),
            'high_count': sum(1 for a in active if a.urgency == Urgency.HIGH),
            'type_counts': type_counts,
            'last_evaluation': (
                self._last_evaluation_time.isoformat()
                if self._last_evaluation_time else None
            ),
            'position_count': len(self._health_cache),
        }

    def get_evaluation_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self._evaluation_history[:limit]

    def load_from_db(self, records: List[Dict[str, Any]]) -> None:
        """从数据库记录恢复内存缓存"""
        if not records:
            return
        advices: List[DecisionAdvice] = []
        for r in records:
            try:
                advice = DecisionAdvice(
                    id=str(r['id']),
                    advice_type=AdviceType(r['advice_type']),
                    urgency=Urgency(r['urgency']),
                    title=r['title'],
                    description=r.get('description', ''),
                    sell_stock_code=r.get('sell_stock_code'),
                    sell_stock_name=r.get('sell_stock_name'),
                    sell_price=r.get('sell_price'),
                    buy_stock_code=r.get('buy_stock_code'),
                    buy_stock_name=r.get('buy_stock_name'),
                    buy_price=r.get('buy_price'),
                    quantity=r.get('quantity'),
                    sell_ratio=r.get('sell_ratio'),
                    created_at=r.get('created_at', ''),
                    is_dismissed=r.get('is_dismissed', False),
                    ai_analysis=r.get('ai_analysis'),
                )
                advices.append(advice)
            except (ValueError, KeyError) as e:
                logger.warning(f"跳过无效的数据库记录: {e}")
        if advices:
            self._advice_cache = advices
            logger.info(f"【决策助理】从数据库恢复 {len(advices)} 条建议")
