#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全链路信号一致性仲裁器 (Signal Arbitrator)

在所有引擎（IntradayRisk, CapitalFlow, Strategy）输出信号后，
进行全局一致性检查，消除矛盾信号，确保前端只收到统一结论。

优先级规则（从高到低）：
  P0: IntradayRiskManager 自动卖出 — 物理价格破位，不可覆盖
  P1: CapitalFlow SELL/ALERT 信号 — 资金流出类
  P2: CapitalFlow BUY 信号 — 资金流入类
  P3: Strategy 策略信号 — 技术面信号

矛盾消解规则：
  当同一股票同时出现 P0 层的 SELL/ALERT 和 P2/P3 层的 BUY 时，
  压制所有 BUY 信号，只保留 SELL/ALERT。
"""

import logging
from typing import Dict, List, Set

logger = logging.getLogger("signal_arbitrator")


class SignalArbitrator:
    """信号一致性仲裁器"""

    # 信号来源 → 优先级映射（数值越小优先级越高）
    SOURCE_PRIORITY = {
        # P0: 自动风控卖出（最高优先级）
        'intraday_risk': 0,
        # P1: 真正的资金流卖出信号（R2主力净流出/R7跌破VWAP/R13日内波段高抛）
        'capital_flow_sell': 1,
        # P2: 买入质量警告（R3流入不足/R4资金转正力度弱/R10量价背离）
        #     不压制BUY，而是附加为 risk_notes 供 DecisionEngine 参考
        'capital_flow_buy_warning': 2,
        # P3: 策略信号
        'strategy': 3,
    }

    # 买入质量警告规则（P2）：这些规则的 SELL/ALERT 不应压制 BUY
    _BUY_QUALITY_WARNING_RULES = {'r3', 'r4', 'r10'}

    def arbitrate(self, signals: List[Dict]) -> List[Dict]:
        """
        仲裁所有信号，消除矛盾

        Args:
            signals: 所有引擎产生的 trade_action 列表

        Returns:
            仲裁后的信号列表（矛盾 BUY 信号被压制）
        """
        if not signals or len(signals) <= 1:
            return signals

        # 按股票代码分组
        by_stock: Dict[str, List[Dict]] = {}
        for sig in signals:
            code = sig.get('stock_code', 'UNKNOWN')
            by_stock.setdefault(code, []).append(sig)

        result: List[Dict] = []
        for code, stock_signals in by_stock.items():
            result.extend(self._arbitrate_stock(code, stock_signals))

        return result

    def _arbitrate_stock(self, stock_code: str, signals: List[Dict]) -> List[Dict]:
        """对单只股票的信号进行仲裁"""
        # 分类
        sell_alerts: List[Dict] = []
        buy_signals: List[Dict] = []
        other_signals: List[Dict] = []

        for sig in signals:
            sig_type = sig.get('signal_type', '').upper()
            if sig_type in ('SELL', 'ALERT', 'DANGER'):
                sell_alerts.append(sig)
            elif sig_type == 'BUY':
                buy_signals.append(sig)
            else:
                other_signals.append(sig)

        # 无矛盾：只有单方向信号
        if not sell_alerts or not buy_signals:
            return signals

        # 有矛盾：同一股票同时出现 SELL/ALERT 和 BUY
        # 区分 P0/P1（真正的卖出信号）和 P2（买入质量警告）
        p0_p1_sells: List[Dict] = []
        p2_warnings: List[Dict] = []

        for sig in sell_alerts:
            priority = self._get_priority(sig)
            if priority <= 1:
                p0_p1_sells.append(sig)
            else:
                p2_warnings.append(sig)

        if p0_p1_sells:
            # 存在真正的高优先级卖出信号（P0/P1）→ 压制所有 BUY
            suppressed_count = len(buy_signals)
            sell_reasons = [s.get('reason', '')[:30] for s in p0_p1_sells[:2]]

            logger.warning(
                f"[{stock_code}] 信号仲裁：压制 {suppressed_count} 个 BUY 信号，"
                f"因存在高优先级卖出/警告信号(P0/P1): {sell_reasons}"
            )

            # 保留卖出/警告 + 其他，丢弃买入
            return sell_alerts + other_signals
        elif p2_warnings:
            # 仅有 P2 买入质量警告 → 不压制 BUY，但将警告附加到 BUY 信号
            risk_notes = [w.get('reason', '') for w in p2_warnings]
            risk_rules = [self._extract_rule_id(w) for w in p2_warnings]

            for buy_sig in buy_signals:
                buy_sig['risk_notes'] = risk_notes
                buy_sig['risk_rules'] = risk_rules

            logger.info(
                f"[{stock_code}] 信号仲裁：放行 {len(buy_signals)} 个 BUY 信号，"
                f"附加 {len(p2_warnings)} 条买入质量警告(P2): "
                f"{[r[:25] for r in risk_notes[:2]]}"
            )

            # 保留 BUY（带 risk_notes）+ 其他，移除 P2 警告（已合并到 BUY 中）
            return buy_signals + other_signals
        else:
            # 无高优先级信号，全部保留
            return signals

    def _get_priority(self, signal: Dict) -> int:
        """获取信号的优先级（0=最高）

        P0: IntradayRiskManager 自动卖出 — 不可覆盖
        P1: 资金流真正的卖出信号（R2主力净流出/R7跌破VWAP/R13日内波段高抛）
        P2: 买入质量警告（R3流入不足/R4资金转正/R10量价背离）— 不压制BUY
        P3: 策略信号
        """
        source = signal.get('source', '')
        sig_type = signal.get('signal_type', '').upper()

        # IntradayRiskManager 的自动卖出
        if 'risk' in source.lower() or signal.get('message', '') in ('触发自动止损', '触发自动半仓止盈', '触发大单逃顶卖出'):
            return 0

        # 资金流信号 — 区分真正卖出(P1)和买入质量警告(P2)
        if 'capital_flow' in source or 'flow_signal' in signal.get('action', ''):
            rule_id = self._extract_rule_id(signal)
            if rule_id in self._BUY_QUALITY_WARNING_RULES:
                return 2  # P2: 买入质量警告，不压制 BUY
            if sig_type in ('SELL', 'ALERT'):
                return 1  # P1: 真正的卖出信号
            else:
                return 2  # 其他资金流信号

        # 策略信号
        return 3

    @staticmethod
    def _extract_rule_id(signal: Dict) -> str:
        """从信号中提取 rule_id（小写）"""
        # 优先从 flow_signal_detail 获取
        detail = signal.get('flow_signal_detail', {})
        if detail and detail.get('rule_id'):
            return detail['rule_id'].lower()
        # 从 action 字段提取: flow_signal_r3 → r3
        action = signal.get('action', '')
        if action.startswith('flow_signal_'):
            return action.replace('flow_signal_', '')
        return ''
