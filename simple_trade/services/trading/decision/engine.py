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
import json
import logging
import os
import time
from datetime import date, datetime, timedelta
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
        # 持仓缓存（避免同一信号处理流程中重复调 Futu API）
        self._positions_cache: Optional[dict] = None
        self._positions_cache_ts: float = 0

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
        基于回测结论：高涨幅+巨量抢筹胜率更高，高涨幅+巨量砸盘多为假信号。
        """
        strength = SNIPER_STRENGTH_MAP.get(signal.signal_type, 50.0)
        direction = 'SELL' if signal.is_red else 'BUY'
        if signal.signal_type in ('reversal_bear', 'sustained_out'):
            direction = 'WARN'

        # === 涨幅感知调整（回测数据支撑） ===
        # 巨量抢筹: 涨8~12%时76.9%胜率, 涨12~20%时91.7%胜率
        # 巨量砸盘: 涨5%+时仅25~50%胜率（假信号）
        gain_pct = self._get_intraday_gain(signal.stock_code, signal.price)
        reason_suffix = ""

        if gain_pct is not None and signal.signal_type == 'mega_buy' and gain_pct >= 5:
            # 高涨幅+巨量抢筹=动能确认，提升强度
            if gain_pct >= 12:
                strength = min(strength * 1.5, 100)
                reason_suffix = f" [动能加成+50%: 已涨{gain_pct:.1f}%]"
            elif gain_pct >= 8:
                strength = min(strength * 1.3, 100)
                reason_suffix = f" [动能加成+30%: 已涨{gain_pct:.1f}%]"
            else:
                strength = min(strength * 1.15, 100)
                reason_suffix = f" [动能加成+15%: 已涨{gain_pct:.1f}%]"

        elif gain_pct is not None and signal.signal_type == 'mega_sell' and gain_pct >= 5:
            # 高涨幅+巨量砸盘=假信号概率高，降级为WARN
            direction = 'WARN'
            strength = strength * 0.5
            reason_suffix = f" [高涨幅砸盘降级: 已涨{gain_pct:.1f}%, 假信号概率高]"

        # === 席位验证与持仓优先权调整 ===
        if signal.signal_type == 'mega_buy':
            futu_svc = getattr(self.container, 'futu_trade_service', None)
            is_held = False
            if futu_svc:
                try:
                    pos_res = self._get_cached_positions(futu_svc)
                    if pos_res.get('success'):
                        is_held = any(p.get('code') == signal.stock_code for p in pos_res.get('positions', []))
                except Exception as e:
                    logger.debug(f"检查持仓股异常: {e}")

            # 如果不是持仓股，且席位验证不是高置信度（散户主导或出货警示），则降级信号强度，使其不能单独触发交易
            sig_severity = getattr(signal, 'severity', 'high')
            if not is_held and sig_severity != 'high':
                strength = 50.0
                reason_suffix += " [席位降级: 非持仓股且无机构席位确认]"

        event = TradeSignalEvent(
            source='sniper',
            stock_code=signal.stock_code,
            stock_name=signal.stock_name,
            direction=direction,
            strength=strength,
            price=signal.price,
            reason=signal.detail + reason_suffix,
            sniper_signal_type=signal.signal_type,
        )
        await self.on_signal(event)

    async def on_anomaly_signal(self, alert: dict):
        """PoolSnapshotScanner 资金建仓信号的便捷入口

        将评分通过的异动股 alert dict 转换为 TradeSignalEvent。
        资金流通道：跳过共振判断，直接进入门卫。
        """
        event = TradeSignalEvent(
            source='anomaly',
            stock_code=alert['code'],
            stock_name=alert['name'],
            direction='BUY',
            strength=min(alert.get('score', 0), 100),
            price=alert.get('price', 0),
            reason=f"资金建仓{alert.get('score', 0)}分 ({alert.get('mode', '')}模式)",
            scorer_score=alert.get('score', 0),
            capital_score=alert.get('capital_score', 0),
            trade_params=alert.get('trade_params'),
        )
        await self.on_signal(event)

    # ==================== 买入信号处理 ====================

    async def _handle_buy_signal(self, event: TradeSignalEvent):
        """处理买入信号

        双通道设计：
          资金流通道(anomaly): Scanner+StockScorer已双层验证 → 跳过共振 → 门卫 → 执行
          Sniper通道:       共振判断 → 门卫 → 执行
        """
        pipeline = {
            'source': event.source,
            'direction': event.direction,
            'strength': event.strength,
            'reason': event.reason,
            'sniper_type': event.sniper_signal_type,
        }

        # 1. 冷却检查
        if self._is_in_cooldown(event.stock_code):
            logger.debug(f"[DecisionEngine] {event.stock_code} 在冷却期内，跳过")
            self._save_pipeline_record(event, 'rejected', '冷却期内', {}, {}, pipeline)
            return

        # 2. 通道分流
        if event.source == 'anomaly':
            # 资金流通道：Scanner+StockScorer已双层验证，跳过共振
            decision = self._build_direct_decision(event)
            resonance_info = {
                'matched': True,
                'type': 'capital_direct',
                'reason': f'资金流直通: 资金评分{event.capital_score:.0f} + 评分{event.scorer_score}',
            }
            logger.info(
                f"[DecisionEngine] ✓ 资金流直通 {event.stock_code} {event.stock_name} "
                f"capital={event.capital_score:.0f} scorer={event.scorer_score}"
            )
        else:
            # Sniper等其他来源走原共振逻辑
            decision = self._evaluate_buy_resonance(event.stock_code)
            resonance_info = {
                'matched': decision is not None,
                'type': decision.resonance_type if decision else None,
                'reason': decision.reason if decision else '未满足共振条件',
            }
            if decision is None:
                self._save_pipeline_record(event, 'waiting', '等待共振确认', resonance_info, {}, pipeline)
                return

        # 3. 门卫检查
        guard_result = self._run_all_guards(event.stock_code, event.price)
        guard_info = {
            'passed': guard_result['passed'],
            'reason': guard_result.get('reason', ''),
        }
        if not guard_result['passed']:
            logger.info(f"[DecisionEngine] 门卫拒绝 {event.stock_code}: {guard_result['reason']}")
            self._save_pipeline_record(event, 'rejected', f"门卫拒绝: {guard_result['reason']}", resonance_info, guard_info, pipeline)
            return

        # 4. 仓位计算
        quantity = self._calculate_position(decision)
        if quantity <= 0:
            logger.info(f"[DecisionEngine] {event.stock_code} 仓位计算为0，跳过")
            self._save_pipeline_record(event, 'rejected', '仓位计算为0', resonance_info, guard_info, pipeline)
            return

        decision.quantity = quantity

        # 5. 执行
        await self._execute_decision(decision)
        self._save_pipeline_record(event, 'executed', f"{decision.resonance_type}: 执行{decision.direction}", resonance_info, guard_info, pipeline)

    def _build_direct_decision(self, event: TradeSignalEvent) -> TradeDecision:
        """资金流通道：直接构建交易决策（跳过共振）

        Scanner已验证资金建仓 + StockScorer已评分通过，
        无需等待第二个信号源。
        """
        trade_params = event.trade_params or {}
        return TradeDecision(
            stock_code=event.stock_code,
            stock_name=event.stock_name,
            direction='BUY',
            price=event.price,
            quantity=0,  # 稍后由 _calculate_position 计算
            reason=event.reason,
            sources=['anomaly'],
            resonance_type='capital_direct',
            simulated=self._simulate,
            buy_dip_pct=trade_params.get('buy_dip_pct', 1.0),
            take_profit_pct=trade_params.get('take_profit_pct', 5.0),
            trailing_stop_pct=trade_params.get('trailing_stop_pct', 3.0),
            stop_loss_pct=trade_params.get('stop_loss_pct', 3.0),
        )

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
            take_profit_pct=trade_params.get('take_profit_pct', 5.0),   # 修复: 原10.0与默认值矛盾
            stop_loss_pct=trade_params.get('stop_loss_pct', 5.0),       # 修复: 原8.0, 回测优化→5.0
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

            positions = self._get_cached_positions(futu_svc)
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

    # ==================== 涨幅感知 ====================

    def _get_intraday_gain(self, stock_code: str, current_price: float) -> Optional[float]:
        """获取当日涨幅(%) — 当前价 vs 昨收价

        Returns: 涨幅百分比，获取失败返回 None
        """
        try:
            quote_cache = getattr(self.container, 'quote_cache', None)
            if not quote_cache:
                return None
            quotes = quote_cache.get_quotes_for_codes([stock_code])
            if stock_code not in quotes:
                return None
            prev_close = quotes[stock_code].get('prev_close', 0)
            if prev_close <= 0:
                return None
            return round((current_price - prev_close) / prev_close * 100, 2)
        except Exception:
            return None

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
                bf = BrokerConsistencyFilter(self.container.futu_client)
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
            positions = self._get_cached_positions(futu_svc)
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

    def _get_cached_positions(self, futu_svc=None) -> dict:
        """获取持仓（5秒缓存，避免同一信号处理流程中重复调用 Futu API）"""
        now = time.time()
        if self._positions_cache is not None and (now - self._positions_cache_ts) < 5:
            return self._positions_cache
        if futu_svc is None:
            futu_svc = getattr(self.container, 'futu_trade_service', None)
        if not futu_svc:
            return {'success': False, 'positions': []}
        try:
            result = futu_svc.get_positions()
            self._positions_cache = result
            self._positions_cache_ts = now
            return result
        except Exception:
            return {'success': False, 'positions': []}

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

    # ==================== 信号流水记录 ====================

    def _save_pipeline_record(
        self, event: TradeSignalEvent, final_action: str,
        final_reason: str, resonance_info: dict, guard_info: dict, raw: dict,
    ):
        """将信号处理流水写入数据库"""
        try:
            db = getattr(self.container, 'db_manager', None)
            if not db:
                return
            today = date.today().isoformat()
            db.execute_update(
                '''INSERT INTO signal_pipeline
                   (trade_date, timestamp, stock_code, stock_name, source,
                    direction, strength, resonance_result, guard_result,
                    final_action, final_reason, raw_detail)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                (today, event.timestamp.isoformat(), event.stock_code,
                 event.stock_name, event.source, event.direction,
                 event.strength, json.dumps(resonance_info, ensure_ascii=False),
                 json.dumps(guard_info, ensure_ascii=False),
                 final_action, final_reason,
                 json.dumps(raw, ensure_ascii=False)),
            )
        except Exception as e:
            logger.debug(f"[DecisionEngine] 流水记录写入失败: {e}")

        # WebSocket 实时推送
        try:
            import asyncio
            socket_manager = getattr(self.container, '_socket_manager', None)
            if not socket_manager:
                from ...dependencies import get_socket_manager
                socket_manager = get_socket_manager()
            if socket_manager:
                asyncio.create_task(socket_manager.emit_to_all('signal_pipeline', {
                    'stock_code': event.stock_code,
                    'stock_name': event.stock_name,
                    'source': event.source,
                    'direction': event.direction,
                    'strength': event.strength,
                    'final_action': final_action,
                    'final_reason': final_reason,
                    'resonance': resonance_info,
                    'guard': guard_info,
                    'timestamp': event.timestamp.isoformat(),
                }))
        except Exception:
            pass

    def get_signal_pipeline(self, limit: int = 50, trade_date: str = '') -> List[dict]:
        """查询信号流水记录（供 API 调用）"""
        try:
            db = getattr(self.container, 'db_manager', None)
            if not db:
                return []
            if not trade_date:
                trade_date = date.today().isoformat()
            with db.get_connection() as conn:
                rows = conn.execute(
                    '''SELECT id, trade_date, timestamp, stock_code, stock_name,
                              source, direction, strength, resonance_result,
                              guard_result, final_action, final_reason, raw_detail
                       FROM signal_pipeline
                       WHERE trade_date = ?
                       ORDER BY id DESC LIMIT ?''',
                    (trade_date, limit),
                ).fetchall()
            result = []
            for r in rows:
                result.append({
                    'id': r[0], 'trade_date': r[1], 'timestamp': r[2],
                    'stock_code': r[3], 'stock_name': r[4],
                    'source': r[5], 'direction': r[6], 'strength': r[7],
                    'resonance': json.loads(r[8]) if r[8] else {},
                    'guard': json.loads(r[9]) if r[9] else {},
                    'final_action': r[10], 'final_reason': r[11],
                    'raw_detail': json.loads(r[12]) if r[12] else {},
                })
            return result
        except Exception as e:
            logger.error(f"[DecisionEngine] 查询流水失败: {e}")
            return []

    def get_screening_analysis(self, stock_code: str) -> dict:
        """获取单只股票的7环节筛选分析（供选股工作台分析按钮调用）"""
        result = {'stock_code': stock_code, 'stages': {}}
        try:
            # ① StockScorer 评分
            scorer = getattr(self.container, 'stock_scorer', None)
            if scorer:
                cached = scorer.get_score(stock_code)
                if cached:
                    result['stages']['scorer'] = {
                        'passed': cached.total_score >= 60,
                        'score': cached.total_score,
                        'mode': getattr(cached, 'mode', ''),
                        'details': getattr(cached, 'details', []),
                        'veto': getattr(cached, 'veto_reason', None),
                    }
                else:
                    result['stages']['scorer'] = {'passed': False, 'score': 0, 'reason': '无缓存评分'}

            # ② 盘中狙击信号
            sniper = getattr(self.container, 'intraday_sniper', None)
            if sniper:
                today_sigs = [s for s in sniper.get_today_signals() if s.get('stock_code') == stock_code]
                result['stages']['sniper'] = {
                    'has_signal': len(today_sigs) > 0,
                    'signals': today_sigs[-5:],  # 最近5条
                }

            # ③ 经纪商一致性
            try:
                from ...services.analysis.flow.broker_consistency_filter import BrokerConsistencyFilter
                bf = BrokerConsistencyFilter(self.container.futu_client)
                trap = bf.check_distribution_trap(stock_code, change_pct=0)
                result['stages']['broker'] = {
                    'is_trap': trap.is_trap,
                    'confidence': trap.trap_confidence,
                    'reason': trap.reason,
                }
            except Exception:
                result['stages']['broker'] = {'is_trap': False, 'confidence': 0, 'reason': '检测异常'}

            # ④ 信号仲裁
            try:
                arbitrator = getattr(self.container, 'signal_arbitrator', None)
                if arbitrator and hasattr(arbitrator, 'get_stock_status'):
                    arb_status = arbitrator.get_stock_status(stock_code)
                    result['stages']['arbitrator'] = arb_status
                else:
                    result['stages']['arbitrator'] = {'status': 'unknown'}
            except Exception:
                result['stages']['arbitrator'] = {'status': 'unknown'}

            # ⑤ 共振状态
            decision = self._evaluate_buy_resonance(stock_code)
            result['stages']['resonance'] = {
                'matched': decision is not None,
                'type': decision.resonance_type if decision else None,
            }

            # ⑥ 门卫检查
            quote_cache = getattr(self.container, 'quote_cache', None)
            price = 0
            if quote_cache:
                quotes = quote_cache.get_quotes_for_codes([stock_code])
                if stock_code in quotes:
                    price = quotes[stock_code].get('last_price', 0)
            if price > 0:
                guard = self._run_all_guards(stock_code, price)
                result['stages']['guard'] = guard
            else:
                result['stages']['guard'] = {'passed': True, 'reason': '无报价数据，跳过'}

            # ⑦ 今日流水记录
            pipeline = self.get_signal_pipeline(limit=10, trade_date=date.today().isoformat())
            result['stages']['pipeline'] = [p for p in pipeline if p['stock_code'] == stock_code][:5]

        except Exception as e:
            logger.error(f"[DecisionEngine] 筛选分析异常 {stock_code}: {e}")
            result['error'] = str(e)

        return result

    def log_daily_screening_summary(self):
        """收盘后输出当天股票池筛选总结到日志文件（数据盘）"""
        try:
            today = date.today().isoformat()
            # 确定日志目录（与数据库同级）
            config = getattr(self.container, 'config', None)
            db_path = getattr(config, 'database_path', 'simple_trade/data/trade.db') if config else 'simple_trade/data/trade.db'
            log_dir = os.path.join(os.path.dirname(db_path), 'logs')
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, f'screening_{today}.log')

            # 查询当天所有流水
            records = self.get_signal_pipeline(limit=500, trade_date=today)

            lines = []
            lines.append(f"=" * 80)
            lines.append(f"盘后筛选总结 — {today}")
            lines.append(f"=" * 80)
            lines.append(f"总信号数: {len(records)}")

            # 按股票分组
            by_stock: Dict[str, list] = {}
            for r in records:
                by_stock.setdefault(r['stock_code'], []).append(r)

            for code, recs in sorted(by_stock.items()):
                name = recs[0].get('stock_name', code)
                executed = [r for r in recs if r['final_action'] == 'executed']
                rejected = [r for r in recs if r['final_action'] == 'rejected']
                waiting = [r for r in recs if r['final_action'] == 'waiting']
                lines.append(f"\n--- {name}({code}) ---")
                lines.append(f"  执行: {len(executed)}  拒绝: {len(rejected)}  等待: {len(waiting)}")
                for r in recs:
                    lines.append(
                        f"  [{r['timestamp'][11:16]}] "
                        f"{r['source']:8s} {r['direction']:4s} "
                        f"强度{r['strength']:5.0f} → {r['final_action']:8s} | {r['final_reason']}"
                    )

            content = '\n'.join(lines)
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write(content)

            logger.info(f"[DecisionEngine] 📝 盘后筛选日志已写入: {log_file} ({len(records)}条记录, {len(by_stock)}只股票)")

        except Exception as e:
            logger.error(f"[DecisionEngine] 盘后日志写入失败: {e}")
