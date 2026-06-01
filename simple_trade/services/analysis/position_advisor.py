#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
持仓股票盘后操作建议引擎

收盘后自动为每只持仓股票生成明日操作建议（HOLD/ADD/REDUCE/EXIT），
结合资金流趋势、信号规则、大单强度、K线形态、盈亏状态等多维度分析。

由 DailyKlineUpdater 在盘后优选完成后自动调用。
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("position_advisor")


# ==================== 数据模型 ====================

@dataclass
class PositionAdvice:
    """持仓操作建议"""
    stock_code: str
    stock_name: str
    action: str = "HOLD"           # HOLD | ADD | REDUCE | EXIT
    confidence: float = 0.5        # 0-1
    reasons: List[str] = field(default_factory=list)
    stop_loss: float = 0.0         # 建议止损价
    take_profit: float = 0.0       # 建议止盈价
    key_price: float = 0.0         # 关键价位（加仓/减仓触发价）
    risk_level: str = "MEDIUM"     # LOW | MEDIUM | HIGH
    summary: str = ""              # 一句话总结
    flow_pattern: str = ""         # sustained_in | alternating | sustained_out
    flow_pattern_desc: str = ""    # 人类可读描述
    # 分析数据快照
    analysis: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['confidence'] = round(d['confidence'], 2)
        d['stop_loss'] = round(d['stop_loss'], 3)
        d['take_profit'] = round(d['take_profit'], 3)
        d['key_price'] = round(d['key_price'], 3)
        return d


# ==================== 核心引擎 ====================

class PositionAdvisor:
    """持仓操作建议引擎"""

    def __init__(self, db_manager, container=None):
        self.db = db_manager
        self.container = container

    async def generate_all_advice(self, positions: List[dict]) -> List[PositionAdvice]:
        """
        为所有持仓股票生成操作建议

        Args:
            positions: 持仓列表 [{'stock_code': ..., 'stock_name': ..., 'qty': ...,
                        'cost_price': ..., 'nominal_price': ..., 'pl_ratio': ...}]
        Returns:
            PositionAdvice 列表
        """
        if not positions:
            return []

        results = []
        for pos in positions:
            code = pos.get('stock_code', pos.get('code', ''))
            if not code or pos.get('qty', 0) <= 0:
                continue
            try:
                advice = self._analyze_position(pos)
                results.append(advice)
            except Exception as e:
                logger.error(f"[PositionAdvisor] {code} 分析异常: {e}")

        # 持久化到数据库
        self._save_advice_batch(results)

        logger.info(
            f"[PositionAdvisor] 完成 {len(results)} 只持仓分析: "
            + ", ".join(f"{a.stock_name}={a.action}" for a in results)
        )
        return results

    def _analyze_position(self, pos: dict) -> PositionAdvice:
        """分析单只持仓股票"""
        code = pos.get('stock_code', pos.get('code', ''))
        name = pos.get('stock_name', pos.get('name', code))
        cost = pos.get('cost_price', 0) or pos.get('avg_price', 0)
        current = pos.get('nominal_price', 0) or pos.get('current_price', 0)
        pl_ratio = pos.get('pl_ratio', 0) or pos.get('profit_loss_pct', 0)

        advice = PositionAdvice(stock_code=code, stock_name=name)

        # 1. 资金流模式
        flow_pattern, flow_desc, cont_days = self._classify_flow_pattern(code)
        advice.flow_pattern = flow_pattern
        advice.flow_pattern_desc = flow_desc

        # 2. 资金流信号（今日触发的规则）
        signals = self._get_today_signals(code)
        buy_signals = [s for s in signals if s.get('signal_type') == 'BUY']
        sell_signals = [s for s in signals if s.get('signal_type') == 'SELL']

        # 3. 资金评分 + 大单
        cap_data = self._get_capital_data(code)
        capital_score = cap_data.get('capital_score', 50)
        net_inflow_ratio = cap_data.get('net_inflow_ratio', 0)
        big_order = self._get_big_order_data(code)
        big_ratio = big_order.get('buy_sell_ratio', 1.0)
        order_strength = big_order.get('order_strength', 0)

        # 4. K线分析
        kline_info = self._analyze_kline(code, current)
        kline_pos = kline_info.get('position', 0.5)
        support = kline_info.get('support', 0)
        resistance = kline_info.get('resistance', 0)

        # 5. 隔夜筛选评分
        screen_score = self._get_screen_score(code)

        # 6. 分析数据快照
        advice.analysis = {
            'flow_pattern': flow_pattern,
            'cont_days': cont_days,
            'capital_score': capital_score,
            'net_inflow_ratio': round(net_inflow_ratio, 4),
            'big_ratio': round(big_ratio, 2),
            'order_strength': round(order_strength, 2),
            'kline_pos': round(kline_pos, 3),
            'support': round(support, 3),
            'resistance': round(resistance, 3),
            'screen_score': screen_score,
            'pl_ratio': round(pl_ratio, 2),
            'buy_signal_count': len(buy_signals),
            'sell_signal_count': len(sell_signals),
        }

        # ========== 决策逻辑 ==========
        score = 50  # 基准分（0-100, >65=ADD, 40-65=HOLD, 25-40=REDUCE, <25=EXIT）

        # 维度1: 资金流趋势 (±25分)
        if flow_pattern == 'sustained_in':
            score += min(25, cont_days * 5)
            advice.reasons.append(f"资金持续流入{cont_days}天")
        elif flow_pattern == 'sustained_out':
            score -= min(25, cont_days * 5)
            advice.reasons.append(f"⚠️ 资金持续流出{cont_days}天")
        else:
            score -= 5
            advice.reasons.append("资金交替进出，方向不明")

        # 维度2: 资金流信号 (±15分)
        for sig in buy_signals:
            rule_id = sig.get('rule_id', '')
            conf = sig.get('confidence', 0.5)
            if rule_id == 'R12':
                score += 15
                advice.reasons.append(f"R12 资金趋势共振 (置信度{conf})")
            elif rule_id == 'R11':
                score += 10
                advice.reasons.append(f"R11 资金持续流入信号")
            elif rule_id == 'R1':
                score += 8
                advice.reasons.append(f"R1 资金净流入建仓")

        for sig in sell_signals:
            rule_id = sig.get('rule_id', '')
            conf = sig.get('confidence', 0.5)
            if rule_id == 'R10':
                score -= 12
                advice.reasons.append(f"⚠️ R10 量价背离 (置信度{conf})")
            elif rule_id == 'R3':
                score -= 8
                advice.reasons.append(f"⚠️ R3 流入不足逢高卖")

        # 维度3: 大单强度 (±10分)
        if big_ratio >= 2.0:
            score += 10
            advice.reasons.append(f"大单强买（买卖比{big_ratio:.1f}）")
        elif big_ratio <= 0.6:
            score -= 10
            advice.reasons.append(f"⚠️ 大单偏空（买卖比{big_ratio:.1f}）")
        elif order_strength < -0.3:
            score -= 7
            advice.reasons.append(f"⚠️ 尾盘大单转空（强度{order_strength:.2f}）")

        # 维度4: K线位置 (±10分)
        if kline_pos <= 0.3:
            score += 8
            advice.reasons.append(f"K线低位({kline_pos:.0%})，空间较大")
        elif kline_pos >= 0.8:
            score -= 8
            advice.reasons.append(f"K线高位({kline_pos:.0%})，注意回调风险")

        # 维度5: 盈亏状态 (±8分)
        if pl_ratio >= 10:
            score -= 5
            advice.reasons.append(f"浮盈{pl_ratio:.1f}%，注意止盈")
        elif pl_ratio <= -8:
            score -= 8
            advice.reasons.append(f"⚠️ 浮亏{pl_ratio:.1f}%，接近止损线")

        # 维度6: 隔夜筛选 (±5分)
        if screen_score >= 80:
            score += 5
            advice.reasons.append(f"隔夜筛选高分({screen_score:.0f}分)")
        elif screen_score <= 0:
            score -= 3
            advice.reasons.append("未入选隔夜筛选")

        # ========== 映射到 action ==========
        if score >= 65:
            advice.action = 'ADD'
            advice.confidence = min(0.95, score / 100)
            advice.risk_level = 'LOW'
        elif score >= 40:
            advice.action = 'HOLD'
            advice.confidence = 0.6
            advice.risk_level = 'MEDIUM'
        elif score >= 25:
            advice.action = 'REDUCE'
            advice.confidence = min(0.85, (65 - score) / 40)
            advice.risk_level = 'HIGH'
        else:
            advice.action = 'EXIT'
            advice.confidence = min(0.9, (40 - score) / 40)
            advice.risk_level = 'HIGH'

        # ========== 价位计算 ==========
        if current > 0:
            advice.stop_loss = round(support * 0.98, 3) if support > 0 else round(current * 0.92, 3)
            advice.take_profit = round(resistance * 1.01, 3) if resistance > 0 else round(current * 1.08, 3)

            if advice.action == 'ADD':
                advice.key_price = round(current * 0.99, 3)  # 低吸1%
            elif advice.action == 'REDUCE':
                advice.key_price = round(current * 1.02, 3)  # 反弹2%减仓
            else:
                advice.key_price = current

        # ========== 一句话总结 ==========
        action_map = {'ADD': '加仓', 'HOLD': '持有', 'REDUCE': '减仓', 'EXIT': '清仓'}
        advice.summary = (
            f"{action_map[advice.action]} | "
            f"{advice.flow_pattern_desc} | "
            f"资金评分{capital_score:.0f} | "
            f"大单比{big_ratio:.1f} | "
            f"止损{advice.stop_loss:.2f}"
        )

        return advice

    # ==================== 资金流模式分类 ====================

    def _classify_flow_pattern(self, code: str) -> Tuple[str, str, int]:
        """
        分析近10日资金流入/流出模式

        Returns: (pattern, description, cont_days)
        """
        try:
            rows = self.db.execute_query(
                "SELECT net_inflow FROM capital_flow_daily "
                "WHERE stock_code = ? ORDER BY date DESC LIMIT 10",
                (code,)
            )
            if not rows:
                return 'alternating', '无资金流数据', 0

            # 连续流入天数
            in_days = 0
            for r in rows:
                if r[0] and r[0] > 0:
                    in_days += 1
                else:
                    break

            # 连续流出天数
            out_days = 0
            for r in rows:
                if r[0] and r[0] < 0:
                    out_days += 1
                else:
                    break

            if in_days >= 3:
                return 'sustained_in', f'持续流入{in_days}天', in_days
            elif out_days >= 3:
                return 'sustained_out', f'持续流出{out_days}天', out_days
            else:
                # 计算交替程度
                if len(rows) >= 4:
                    signs = [1 if (r[0] or 0) > 0 else -1 for r in rows[:7]]
                    changes = sum(1 for i in range(1, len(signs)) if signs[i] != signs[i-1])
                    if changes >= 3:
                        return 'alternating', '资金交替进出', 0
                if in_days >= 1:
                    return 'sustained_in', f'流入{in_days}天', in_days
                elif out_days >= 1:
                    return 'sustained_out', f'流出{out_days}天', out_days
                return 'alternating', '资金方向不明', 0

        except Exception as e:
            logger.debug(f"[PositionAdvisor] 资金流模式分析失败 {code}: {e}")
            return 'alternating', '分析异常', 0

    # ==================== 数据读取 ====================

    def _get_today_signals(self, code: str) -> List[dict]:
        """获取今日资金流信号"""
        try:
            rows = self.db.execute_query(
                "SELECT rule_id, rule_name, signal_type, confidence, reason "
                "FROM capital_flow_signals "
                "WHERE stock_code = ? AND date(created_at) = date('now') "
                "ORDER BY created_at DESC",
                (code,)
            )
            if not rows:
                return []
            return [
                {'rule_id': r[0], 'rule_name': r[1], 'signal_type': r[2],
                 'confidence': r[3], 'reason': r[4]}
                for r in rows
            ]
        except Exception:
            return []

    def _get_capital_data(self, code: str) -> dict:
        """读取资金流缓存"""
        try:
            rows = self.db.execute_query(
                "SELECT capital_score, net_inflow_ratio, big_order_buy_ratio, main_net_inflow "
                "FROM capital_flow_cache WHERE stock_code = ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (code,)
            )
            if rows:
                return {
                    'capital_score': rows[0][0] or 50,
                    'net_inflow_ratio': rows[0][1] or 0,
                    'big_order_buy_ratio': rows[0][2] or 0,
                    'main_net_inflow': rows[0][3] or 0,
                }
        except Exception:
            pass
        return {'capital_score': 50, 'net_inflow_ratio': 0,
                'big_order_buy_ratio': 0, 'main_net_inflow': 0}

    def _get_big_order_data(self, code: str) -> dict:
        """获取最近大单数据"""
        try:
            rows = self.db.execute_query(
                "SELECT buy_sell_ratio, order_strength "
                "FROM big_order_tracking WHERE stock_code = ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (code,)
            )
            if rows:
                return {
                    'buy_sell_ratio': rows[0][0] or 1.0,
                    'order_strength': rows[0][1] or 0,
                }
        except Exception:
            pass
        return {'buy_sell_ratio': 1.0, 'order_strength': 0}

    def _analyze_kline(self, code: str, current_price: float) -> dict:
        """K线分析：位置、支撑、压力"""
        result = {'position': 0.5, 'support': 0, 'resistance': 0}
        try:
            rows = self.db.execute_query(
                "SELECT high_price, low_price, close_price FROM kline_data "
                "WHERE stock_code = ? ORDER BY time_key DESC LIMIT 20",
                (code,)
            )
            if not rows or len(rows) < 5:
                return result

            highs = [r[0] for r in rows if r[0]]
            lows = [r[1] for r in rows if r[1]]
            closes = [r[2] for r in rows if r[2]]

            if highs and lows:
                h, l = max(highs), min(lows)
                if h > l and current_price > 0:
                    result['position'] = (current_price - l) / (h - l)

            # 支撑位：近5日最低价中位数
            if len(lows) >= 5:
                recent_lows = sorted(lows[:5])
                result['support'] = recent_lows[len(recent_lows) // 2]
            elif lows:
                result['support'] = min(lows[:5])

            # 压力位：近20日最高价
            if highs:
                result['resistance'] = max(highs)

        except Exception as e:
            logger.debug(f"[PositionAdvisor] K线分析失败 {code}: {e}")
        return result

    def _get_screen_score(self, code: str) -> float:
        """获取最近隔夜筛选评分"""
        try:
            rows = self.db.execute_query(
                "SELECT candidates_json FROM overnight_screen_results "
                "ORDER BY screen_date DESC LIMIT 1"
            )
            if rows and rows[0][0]:
                candidates = json.loads(rows[0][0])
                for c in candidates:
                    if c.get('stock_code') == code:
                        return c.get('total_score', 0)
        except Exception:
            pass
        return 0

    # ==================== 持久化 ====================

    def _save_advice_batch(self, advices: List[PositionAdvice]):
        """批量保存到数据库"""
        if not advices:
            return
        today = date.today().isoformat()

        # 确保表存在
        try:
            self.db.execute_update("""
                CREATE TABLE IF NOT EXISTS position_advice (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_date TEXT NOT NULL,
                    stock_code VARCHAR(20) NOT NULL,
                    stock_name TEXT,
                    action TEXT NOT NULL,
                    confidence REAL DEFAULT 0,
                    reasons TEXT,
                    stop_loss REAL,
                    take_profit REAL,
                    key_price REAL,
                    risk_level TEXT,
                    summary TEXT,
                    flow_pattern TEXT,
                    flow_pattern_desc TEXT,
                    analysis_data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(trade_date, stock_code)
                )
            """)
        except Exception:
            pass

        for a in advices:
            try:
                self.db.execute_update(
                    """INSERT OR REPLACE INTO position_advice
                       (trade_date, stock_code, stock_name, action, confidence,
                        reasons, stop_loss, take_profit, key_price, risk_level,
                        summary, flow_pattern, flow_pattern_desc, analysis_data)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (today, a.stock_code, a.stock_name, a.action, a.confidence,
                     json.dumps(a.reasons, ensure_ascii=False),
                     a.stop_loss, a.take_profit, a.key_price, a.risk_level,
                     a.summary, a.flow_pattern, a.flow_pattern_desc,
                     json.dumps(a.analysis, ensure_ascii=False)),
                )
            except Exception as e:
                logger.warning(f"[PositionAdvisor] 保存建议失败 {a.stock_code}: {e}")

    # ==================== API 查询 ====================

    def get_latest_advice(self) -> List[dict]:
        """获取最新一次的操作建议（供 API 调用）"""
        try:
            rows = self.db.execute_query(
                "SELECT trade_date, stock_code, stock_name, action, confidence, "
                "reasons, stop_loss, take_profit, key_price, risk_level, "
                "summary, flow_pattern, flow_pattern_desc, analysis_data, created_at "
                "FROM position_advice "
                "WHERE trade_date = (SELECT MAX(trade_date) FROM position_advice) "
                "ORDER BY action DESC, confidence DESC"
            )
            if not rows:
                return []
            result = []
            for r in rows:
                result.append({
                    'trade_date': r[0],
                    'stock_code': r[1],
                    'stock_name': r[2],
                    'action': r[3],
                    'confidence': r[4],
                    'reasons': json.loads(r[5]) if r[5] else [],
                    'stop_loss': r[6],
                    'take_profit': r[7],
                    'key_price': r[8],
                    'risk_level': r[9],
                    'summary': r[10],
                    'flow_pattern': r[11],
                    'flow_pattern_desc': r[12],
                    'analysis': json.loads(r[13]) if r[13] else {},
                    'created_at': r[14],
                })
            return result
        except Exception as e:
            logger.error(f"[PositionAdvisor] 查询建议失败: {e}")
            return []

    # ==================== 企业微信推送 ====================

    async def push_wechat_alerts(self, advices: List[PositionAdvice]):
        """推送减仓/清仓建议到企业微信"""
        try:
            wechat = getattr(self.container, 'wechat_alert_service', None) if self.container else None
            if not wechat or not wechat.enabled:
                return

            alerts = [a for a in advices if a.action in ('REDUCE', 'EXIT')]
            if not alerts:
                return

            from ..trading.alert.wechat_alert import AlertLevel

            for a in alerts:
                emoji = '🔴' if a.action == 'EXIT' else '🟡'
                action_cn = '清仓' if a.action == 'EXIT' else '减仓'
                level = AlertLevel.CRITICAL if a.action == 'EXIT' else AlertLevel.WARNING

                content = (
                    f"**{a.stock_name}({a.stock_code})**\n"
                    f"- 建议：{action_cn}（置信度 {a.confidence:.0%}）\n"
                    f"- 资金模式：{a.flow_pattern_desc}\n"
                    f"- 止损价：{a.stop_loss:.3f}\n"
                    f"- 理由：{'；'.join(a.reasons[:3])}\n"
                    f"- 风险等级：{a.risk_level}"
                )

                await wechat.send(
                    level=level,
                    title=f"{emoji} 盘后{action_cn}建议 — {a.stock_name}",
                    content=content,
                    dedup_key=f"position_advice:{a.stock_code}:{a.action}:{date.today().isoformat()}",
                )

            logger.info(f"[PositionAdvisor] 已推送 {len(alerts)} 条减仓/清仓建议到企业微信")

        except Exception as e:
            logger.warning(f"[PositionAdvisor] 企业微信推送失败: {e}")
