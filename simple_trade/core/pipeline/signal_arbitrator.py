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
        # P1: 资金流卖出/警告类信号
        'capital_flow_sell': 1,
        # P2: 资金流买入类信号
        'capital_flow_buy': 2,
        # P3: 策略信号
        'strategy': 3,
    }

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
        # 判断卖出信号中是否有高优先级来源
        has_high_priority_sell = any(
            self._get_priority(sig) <= 1  # P0/P1 only (风控卖出+资金流卖出)
            for sig in sell_alerts
        )

        if has_high_priority_sell:
            # 压制所有 BUY 信号
            suppressed_count = len(buy_signals)
            sell_reasons = [s.get('reason', '')[:30] for s in sell_alerts[:2]]

            logger.warning(
                f"[{stock_code}] 信号仲裁：压制 {suppressed_count} 个 BUY 信号，"
                f"因存在高优先级卖出/警告信号: {sell_reasons}"
            )

            # 保留卖出/警告 + 其他，丢弃买入
            return sell_alerts + other_signals
        else:
            # 低优先级的卖出信号不足以压制买入，全部保留
            return signals

    def _get_priority(self, signal: Dict) -> int:
        """获取信号的优先级（0=最高）"""
        source = signal.get('source', '')
        sig_type = signal.get('signal_type', '').upper()

        # IntradayRiskManager 的自动卖出
        if 'risk' in source.lower() or signal.get('message', '') in ('触发自动止损', '触发自动半仓止盈', '触发大单逃顶卖出'):
            return 0

        # 资金流信号
        if 'capital_flow' in source or 'flow_signal' in signal.get('action', ''):
            if sig_type in ('SELL', 'ALERT'):
                return 1
            else:
                return 2

        # 策略信号
        return 3
