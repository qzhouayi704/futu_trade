#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UnifiedTradeDecisionEngine — 统一交易决策引擎

系统中唯一的交易创建入口。接收来自 IntradaySniper、PoolSnapshotScanner、
StockScorer 等信号源的标准化信号，通过共振确认后执行交易。

信号流:
  信号源 → on_signal() → 共振判断 → 门卫检查 → 仓位计算 → 执行/记录
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

from .models import (
    TradeSignalEvent,
    TradeDecision,
    RESONANCE_RULES,
    POSITION_CONFIG,
    RED_SIGNAL_ACTIONS,
    COOLDOWN_MINUTES,
    SNIPER_STRENGTH_MAP,
)

logger = logging.getLogger("decision_engine")


class UnifiedTradeDecisionEngine:
    """统一交易决策引擎"""

    def __init__(self, container, simulate: bool = True):
        """
        Args:
            container: BusinessServices 实例（通过 ServiceContainer.__getattr__ 可访问所有服务）
            simulate: True=模拟模式（记录但不下单），False=实盘模式
        """
        self.container = container
        self._simulate = simulate

        # 待处理信号缓存: stock_code → [TradeSignalEvent, ...]
        self._pending_signals: Dict[str, List[TradeSignalEvent]] = {}
        # 冷却名单: stock_code → 冷却截止时间
        self._cooldown: Dict[str, datetime] = {}
        # 今日决策记录（供前端查询）
        self._today_decisions: List[TradeDecision] = []

        logger.info(
            f"[DecisionEngine] 初始化完成 (模式={'模拟' if simulate else '实盘'})"
        )

    # ==================== 公共接口 ====================

    @property
    def simulate_mode(self) -> bool:
        return self._simulate

    def set_simulate(self, enabled: bool):
        """切换模拟/实盘模式"""
        old = self._simulate
        self._simulate = enabled
        logger.info(f"[DecisionEngine] 模式切换: {'模拟' if old else '实盘'} → {'模拟' if enabled else '实盘'}")

    def get_today_decisions(self) -> List[dict]:
        """获取今日所有决策（供 API 查询）"""
        return [d.to_dict() for d in self._today_decisions]

    def get_pending_signals(self, stock_code: str = '') -> List[dict]:
        """获取待处理信号"""
        if stock_code:
            signals = self._pending_signals.get(stock_code, [])
        else:
            signals = [s for lst in self._pending_signals.values() for s in lst]
        return [s.to_dict() for s in signals]

    # ==================== 信号入口 ====================

    async def on_signal(self, event: TradeSignalEvent):
        """统一信号入口 — 所有信号源都调用此方法"""
        logger.debug(
            f"[DecisionEngine] 收到信号: {event.source} {event.direction} "
            f"{event.stock_code} {event.stock_name} strength={event.strength}"
        )

        # 清理过期信号
        self._cleanup_expired_signals(event.stock_code)

        # 缓存信号
        self._pending_signals.setdefault(event.stock_code, []).append(event)

        # 分流处理
        if event.direction in ('SELL', 'WARN'):
            await self._handle_risk_signal(event)
        elif event.direction == 'BUY':
            await self._handle_buy_signal(event)

    async def on_sniper_signal(self, signal):
        """IntradaySniper 信号的便捷入口

        将 SniperSignal 转换为 TradeSignalEvent 后调用 on_signal。
        """
        strength = SNIPER_STRENGTH_MAP.get(signal.signal_type, 50.0)
        direction = 'SELL' if signal.is_red else 'BUY'
        if signal.signal_type in ('reversal_bear', 'sustained_out'):
            direction = 'WARN'

        event = TradeSignalEvent(
            source='sniper',
            stock_code=signal.stock_code,
            stock_name=signal.stock_name,
            direction=direction,
            strength=strength,
            price=signal.price,
            reason=signal.detail,
            sniper_signal_type=signal.signal_type,
        )
        await self.on_signal(event)

    async def on_anomaly_signal(self, alert: dict):
        """PoolSnapshotScanner 异动信号的便捷入口

        将评分通过的异动股 alert dict 转换为 TradeSignalEvent。
        """
        event = TradeSignalEvent(
            source='anomaly',
            stock_code=alert['code'],
            stock_name=alert['name'],
            direction='BUY',
            strength=min(alert.get('score', 0), 100),
            price=alert.get('price', 0),
            reason=f"异动评分{alert.get('score', 0)}分 ({alert.get('mode', '')}模式)",
            scorer_score=alert.get('score', 0),
            trade_params=alert.get('trade_params'),
        )
        await self.on_signal(event)

    # ==================== 买入信号处理 ====================

    async def _handle_buy_signal(self, event: TradeSignalEvent):
        """处理买入信号 → 共振判断 → 门卫 → 仓位 → 执行"""

        # 1. 冷却检查
        if self._is_in_cooldown(event.stock_code):
            logger.debug(f"[DecisionEngine] {event.stock_code} 在冷却期内，跳过")
            return

        # 2. 共振判断
        decision = self._evaluate_buy_resonance(event.stock_code)
        if decision is None:
            return

        # 3. 门卫检查
        guard_result = self._run_all_guards(event.stock_code, event.price)
        if not guard_result['passed']:
            logger.info(
                f"[DecisionEngine] 门卫拒绝 {event.stock_code}: {guard_result['reason']}"
            )
            return

        # 4. 仓位计算
        quantity = self._calculate_position(decision)
        if quantity <= 0:
            logger.info(f"[DecisionEngine] {event.stock_code} 仓位计算为0，跳过")
            return

        decision.quantity = quantity

        # 5. 执行
        await self._execute_decision(decision)

    def _evaluate_buy_resonance(self, stock_code: str) -> Optional[TradeDecision]:
        """共振判断 — 检查是否满足交易条件"""
        signals = self._pending_signals.get(stock_code, [])
        now = datetime.now()

        # 只看最近窗口内的 BUY 信号
        window = timedelta(minutes=RESONANCE_RULES['dual_source']['window_minutes'])
        recent = [s for s in signals if s.direction == 'BUY' and (now - s.timestamp) < window]

        if not recent:
            return None

        # 取最新信号的基础信息
        latest = recent[-1]
        all_sources = list(set(s.source for s in recent))

        # 提取交易参数（优先用 trade_params，否则用默认值）
        trade_params = {}
        for s in recent:
            if s.trade_params:
                trade_params = s.trade_params
                break

        base_decision = TradeDecision(
            stock_code=stock_code,
            stock_name=latest.stock_name,
            direction='BUY',
            price=latest.price,
            quantity=0,  # 稍后计算
            reason='',
            sources=all_sources,
            resonance_type='',
            simulated=self._simulate,
            buy_dip_pct=trade_params.get('buy_dip_pct', 1.0),
            take_profit_pct=trade_params.get('take_profit_pct', 10.0),
            stop_loss_pct=trade_params.get('stop_loss_pct', 8.0),
        )

        # 规则1: 双源共振
        sources = set(s.source for s in recent)
        if len(sources) >= RESONANCE_RULES['dual_source']['min_sources']:
            base_decision.resonance_type = 'dual_source'
            base_decision.reason = (
                f"双源共振({'+'.join(sources)}): "
                + '; '.join(s.reason for s in recent[-2:])
            )
            logger.info(
                f"[DecisionEngine] ✓ 双源共振 {stock_code} {latest.stock_name} "
                f"sources={sources}"
            )
            return base_decision

        # 规则2: 单源强信号 + 高评分
        cfg = RESONANCE_RULES['strong_single']
        strongest = max(recent, key=lambda s: s.strength)
        if strongest.strength >= cfg['min_strength']:
            scorer = self._get_scorer_score(stock_code)
            if scorer >= cfg['min_score']:
                base_decision.resonance_type = 'strong_single'
                base_decision.reason = (
                    f"强信号({strongest.source}, 强度{strongest.strength:.0f}) "
                    f"+ 高评分({scorer}): {strongest.reason}"
                )
                logger.info(
                    f"[DecisionEngine] ✓ 强信号共振 {stock_code} "
                    f"strength={strongest.strength} score={scorer}"
                )
                return base_decision

        # 规则3: 多重绿色(Sniper)
        cfg3 = RESONANCE_RULES['multi_green']
        sniper_types = set(
            s.sniper_signal_type for s in recent
            if s.source == 'sniper' and s.sniper_signal_type
        )
        if len(sniper_types) >= cfg3['min_distinct_types']:
            base_decision.resonance_type = 'multi_green'
            base_decision.reason = (
                f"多重绿色信号({'+'.join(sniper_types)}): "
                + '; '.join(s.reason for s in recent if s.source == 'sniper')
            )
            logger.info(
                f"[DecisionEngine] ✓ 多重绿色 {stock_code} types={sniper_types}"
            )
            return base_decision

        return None

    # ==================== 红色信号处理 ====================

    async def _handle_risk_signal(self, event: TradeSignalEvent):
        """处理红色/警告信号"""
        action = RED_SIGNAL_ACTIONS.get(event.sniper_signal_type, 'warn')

        if action == 'auto_sell':
            await self._handle_auto_sell(event)
            # 仅实际执行卖出后加入冷却名单
            self._cooldown[event.stock_code] = datetime.now() + timedelta(minutes=COOLDOWN_MINUTES)
        else:
            await self._handle_warn(event)
            # WARN 信号不加冷却，避免阻止买入信号

    async def _handle_auto_sell(self, event: TradeSignalEvent):
        """巨量砸盘 → 检查持仓并自动卖出"""
        try:
            futu_svc = getattr(self.container, 'futu_trade_service', None)
            if not futu_svc or not futu_svc.is_trade_ready():
                logger.warning(f"[DecisionEngine] 交易服务未就绪，无法自动卖出 {event.stock_code}")
                return

            positions = futu_svc.get_positions()
            if not positions.get('success'):
                return

            # 查找该股票的持仓
            held = None
            for pos in positions.get('positions', []):
                if pos.get('code') == event.stock_code:
                    held = pos
                    break

            if not held:
                logger.info(f"[DecisionEngine] {event.stock_code} 无持仓，跳过自动卖出")
                return

            qty = int(held.get('qty', 0))
            if qty <= 0:
                return

            decision = TradeDecision(
                stock_code=event.stock_code,
                stock_name=event.stock_name,
                direction='SELL',
                price=event.price,
                quantity=qty,
                reason=f"巨量砸盘自动止损: {event.reason}",
                sources=['sniper'],
                resonance_type='risk_auto_sell',
                simulated=self._simulate,
            )

            await self._execute_decision(decision)

        except Exception as e:
            logger.error(f"[DecisionEngine] 自动卖出异常 {event.stock_code}: {e}")

    async def _handle_warn(self, event: TradeSignalEvent):
        """风控预警 — 推送通知但不自动操作"""
        logger.info(
            f"[DecisionEngine] ⚠️ 风控预警 {event.stock_code} {event.stock_name}: "
            f"{event.reason}"
        )

        # 推送 WebSocket 预警
        try:
            socket_manager = getattr(self.container, '_socket_manager', None)
            if not socket_manager:
                from ...dependencies import get_socket_manager
                socket_manager = get_socket_manager()
            if socket_manager:
                await socket_manager.emit_to_all('trade_risk_warning', {
                    'stock_code': event.stock_code,
                    'stock_name': event.stock_name,
                    'signal_type': event.sniper_signal_type,
                    'reason': event.reason,
                    'price': event.price,
                    'timestamp': event.timestamp.isoformat(),
                })
        except Exception as e:
            logger.debug(f"[DecisionEngine] 预警推送失败: {e}")

    # ==================== 门卫检查 ====================

    def _run_all_guards(self, stock_code: str, price: float) -> Dict[str, Any]:
        """统一门卫检查入口"""
        try:
            # 1. 交易频率守卫
            guard = getattr(self.container, 'trade_frequency_guard', None)
            if guard:
                allowed, reason = guard.can_buy(stock_code)
                if not allowed:
                    return {'passed': False, 'reason': f"[频率] {reason}"}

            # 2. 交易阶段检查
            phase_mgr = getattr(self.container, 'trading_phase_manager', None)
            if phase_mgr:
                scorer_score = self._get_scorer_score(stock_code)
                allowed, reason = phase_mgr.should_buy(scorer_score)
                if not allowed:
                    return {'passed': False, 'reason': f"[阶段] {reason}"}

            # 3. 评分一票否决（盘中同股亏损次数检查）
            scorer = getattr(self.container, 'stock_scorer', None)
            if scorer:
                veto = scorer.check_intraday_veto(stock_code)
                if veto:
                    return {'passed': False, 'reason': f"[否决] {veto}"}

            # 4. 出货陷阱检测
            try:
                from ...services.analysis.flow.broker_consistency_filter import BrokerConsistencyFilter
                bf = BrokerConsistencyFilter(self.container)
                trap_result = bf.check_distribution_trap(stock_code, change_pct=0)
                if trap_result.is_trap:
                    return {
                        'passed': False,
                        'reason': f"[出货陷阱] 置信度{trap_result.trap_confidence:.0%}: {trap_result.reason}"
                    }
            except Exception as e:
                logger.debug(f"[DecisionEngine] 出货陷阱检测异常(放行): {e}")

            return {'passed': True, 'reason': ''}

        except Exception as e:
            # 门卫异常不阻止交易
            logger.warning(f"[DecisionEngine] 门卫检查异常(放行): {e}")
            return {'passed': True, 'reason': ''}

    # ==================== 仓位计算 ====================

    def _calculate_position(self, decision: TradeDecision) -> int:
        """全局仓位计算 — 按资金百分比动态计算，不限固定股数"""
        try:
            cfg = POSITION_CONFIG
            futu_svc = getattr(self.container, 'futu_trade_service', None)

            if not futu_svc:
                return 100  # 无交易服务时返回最小单位

            # 1. 检查持仓数量
            positions = futu_svc.get_positions()
            current_count = len(positions.get('positions', [])) if positions.get('success') else 0
            if current_count >= cfg['max_total_positions']:
                logger.info(f"[DecisionEngine] 持仓已满 ({current_count}/{cfg['max_total_positions']})")
                return 0

            # 2. 检查可用资金
            account = futu_svc.get_account_info()
            if not account.get('success'):
                return 100

            accounts = account.get('accounts', [])
            if not accounts:
                return 100

            available_cash = float(accounts[0].get('available_funds', 0))
            if available_cash <= 0:
                return 0

            reserve = available_cash * cfg['min_cash_reserve_pct']
            investable = available_cash - reserve
            if investable <= 0:
                return 0

            # 3. 按百分比计算（不再用固定股数上限）
            max_amount = investable * cfg['max_single_position_pct']
            if decision.price <= 0:
                return 100

            quantity = int(max_amount / decision.price / 100) * 100
            return max(quantity, 0)

        except Exception as e:
            logger.warning(f"[DecisionEngine] 仓位计算异常(使用最小单位): {e}")
            return 100

    # ==================== 执行 ====================

    async def _execute_decision(self, decision: TradeDecision):
        """执行交易决策"""
        self._today_decisions.append(decision)

        label = '模拟' if decision.simulated else '实盘'
        logger.info(
            f"[DecisionEngine] 🎯 {label}{decision.direction} "
            f"{decision.stock_code} {decision.stock_name} "
            f"x{decision.quantity} @{decision.price:.3f} "
            f"({decision.resonance_type}: {decision.reason})"
        )

        if decision.simulated:
            # 保存模拟交易记录到数据库
            try:
                futu_svc = getattr(self.container, 'futu_trade_service', None)
                if futu_svc and hasattr(futu_svc, 'order_manager'):
                    futu_svc.order_manager.create_simulated_record(
                        stock_code=decision.stock_code,
                        stock_name=decision.stock_name,
                        direction=decision.direction,
                        price=decision.price,
                        quantity=decision.quantity,
                        resonance_type=decision.resonance_type,
                        reason=decision.reason,
                        sources=','.join(decision.sources),
                    )
                    logger.info(f"[DecisionEngine] 💾 模拟记录已保存到数据库")
            except Exception as e:
                logger.warning(f"[DecisionEngine] 模拟记录保存失败: {e}")
            await self._push_trade_notification(decision)
            return

        # 实盘模式
        if decision.direction == 'BUY':
            await self._execute_buy(decision)
        elif decision.direction == 'SELL':
            await self._execute_sell(decision)

        await self._push_trade_notification(decision)

        # 买入后设置冷却
        if decision.direction == 'BUY':
            self._cooldown[decision.stock_code] = (
                datetime.now() + timedelta(minutes=COOLDOWN_MINUTES)
            )

    async def _execute_buy(self, decision: TradeDecision):
        """实盘买入 — 通过 AutoTradeService 创建交易任务"""
        try:
            auto_trade_svc = getattr(self.container, 'aggressive_trade_service', None)
            if not auto_trade_svc:
                # 直接尝试获取 AutoTradeService
                from ..aggressive import AutoTradeService
                auto_trade_svc = AutoTradeService(self.container)

            result = auto_trade_svc.start_auto_trade(
                stock_code=decision.stock_code,
                quantity=decision.quantity,
                zone='decision_engine',
                buy_dip_pct=decision.buy_dip_pct,
                sell_rise_pct=decision.take_profit_pct,
                stop_loss_pct=decision.stop_loss_pct,
                prev_close=decision.price,
            )

            if result.get('success'):
                logger.info(
                    f"[DecisionEngine] ✅ 交易任务创建成功 {decision.stock_code} "
                    f"入场价≈{decision.price * (1 - decision.buy_dip_pct / 100):.3f}"
                )
            else:
                logger.warning(
                    f"[DecisionEngine] ❌ 交易任务创建失败 {decision.stock_code}: "
                    f"{result.get('message', '')}"
                )

        except Exception as e:
            logger.error(f"[DecisionEngine] 买入执行异常 {decision.stock_code}: {e}")

    async def _execute_sell(self, decision: TradeDecision):
        """实盘卖出 — 市价单"""
        try:
            futu_svc = getattr(self.container, 'futu_trade_service', None)
            if not futu_svc or not futu_svc.is_trade_ready():
                logger.warning(f"[DecisionEngine] 交易服务未就绪，无法卖出 {decision.stock_code}")
                return

            from ...core.models import StockInfo
            stock = StockInfo(code=decision.stock_code, name=decision.stock_name)
            result = futu_svc.execute_trade(
                stock=stock,
                trade_type='SELL',
                price=decision.price,
                quantity=decision.quantity,
            )

            if result.get('success'):
                logger.info(f"[DecisionEngine] ✅ 卖出成功 {decision.stock_code}")
            else:
                logger.warning(
                    f"[DecisionEngine] ❌ 卖出失败 {decision.stock_code}: "
                    f"{result.get('message', '')}"
                )

        except Exception as e:
            logger.error(f"[DecisionEngine] 卖出执行异常 {decision.stock_code}: {e}")

    # ==================== 通知推送 ====================

    async def _push_trade_notification(self, decision: TradeDecision):
        """推送交易决策通知到前端"""
        try:
            socket_manager = getattr(self.container, '_socket_manager', None)
            if not socket_manager:
                from ...dependencies import get_socket_manager
                socket_manager = get_socket_manager()
            if socket_manager:
                await socket_manager.emit_to_all('trade_decision', decision.to_dict())
        except Exception as e:
            logger.debug(f"[DecisionEngine] 通知推送失败: {e}")

        # 企业微信推送
        try:
            wechat = getattr(self.container, 'wechat_alert_service', None)
            if wechat and wechat.enabled:
                from ..alert.wechat_alert import AlertLevel
                label = '🔵模拟' if decision.simulated else '🟢实盘'
                level = AlertLevel.INFO if decision.direction == 'BUY' else AlertLevel.CRITICAL
                await wechat.send(
                    level=level,
                    title=f"{label}{decision.direction} — {decision.stock_name}",
                    content=(
                        f"**{decision.stock_name}({decision.stock_code})**\n"
                        f"- 方向：{decision.direction}\n"
                        f"- 价格：{decision.price:.3f}\n"
                        f"- 数量：{decision.quantity}\n"
                        f"- 共振：{decision.resonance_type}\n"
                        f"- 原因：{decision.reason}"
                    ),
                    dedup_key=f"decision:{decision.stock_code}:{decision.direction}",
                )
        except Exception as e:
            logger.debug(f"[DecisionEngine] 微信推送失败: {e}")

    # ==================== 辅助方法 ====================

    def _get_scorer_score(self, stock_code: str) -> int:
        """获取 StockScorer 缓存的评分"""
        try:
            scorer = getattr(self.container, 'stock_scorer', None)
            if scorer:
                cached = scorer.get_score(stock_code)
                return cached.total_score if cached else 0
        except Exception:
            pass
        return 0

    def _is_in_cooldown(self, stock_code: str) -> bool:
        """检查是否在冷却期"""
        deadline = self._cooldown.get(stock_code)
        if deadline and datetime.now() < deadline:
            return True
        # 清理过期
        if deadline:
            del self._cooldown[stock_code]
        return False

    def _cleanup_expired_signals(self, stock_code: str):
        """清理过期信号（保留最近30分钟）"""
        signals = self._pending_signals.get(stock_code)
        if not signals:
            return
        cutoff = datetime.now() - timedelta(minutes=30)
        self._pending_signals[stock_code] = [
            s for s in signals if s.timestamp > cutoff
        ]

    def reset_daily(self):
        """每日重置（由系统协调器在收盘后调用）"""
        self._pending_signals.clear()
        self._cooldown.clear()
        self._today_decisions.clear()
        logger.info("[DecisionEngine] 每日重置完成")
