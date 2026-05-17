#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
个股深度分析服务

整合四大信号源（快速扫描 + 操盘规则 + 交易策略 + 技术指标/K线形态），
从 DB 读取资金流、活跃度、K线数据，生成加权综合判定。

零 API 调用，纯 DB 读取，<1秒返回。
"""

import logging
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from ..market_data.stock_profile_tagger import StockProfileTagger
from .key_levels_calculator import KeyLevelsCalculator

logger = logging.getLogger("stock_insight")


class StockInsightService:
    """个股深度分析服务"""

    # 信号权重
    WEIGHT_QUICK_SCAN = 3
    WEIGHT_FLOW_RULE = 2
    WEIGHT_TRADE_STRATEGY = 2
    WEIGHT_TECHNICAL = 1

    def __init__(self, db_manager):
        self.db = db_manager
        self._tagger = StockProfileTagger()
        self._levels_calc = KeyLevelsCalculator()

    def analyze(self, stock_code: str,
                quick_scan_result: Optional[dict] = None,
                flow_signals: Optional[list] = None) -> dict:
        """
        执行完整的个股深度分析

        Args:
            stock_code: 股票代码 (e.g. "HK.02701")
            quick_scan_result: 前端传入的 QuickScan 结果（可选，避免重复计算）
            flow_signals: 前端传入的操盘规则信号（可选）

        Returns:
            完整分析结果 dict
        """
        # 1. 基础信息
        stock_name = self._get_stock_name(stock_code)

        # 2. K线数据 → 技术指标 + K线形态
        klines = self._load_klines(stock_code, limit=30)
        technicals = self._calc_technicals(klines)
        kline_pattern = self._calc_kline_pattern(klines)

        # 2b. 股票行为标签
        stock_tag = self._tagger.tag_stock(stock_code, klines)

        # 2c. 关键价位
        key_levels = self._levels_calc.calculate(klines, stock_tag.label)

        # 3. 资金流时间线
        capital_flow = self._load_capital_flow(stock_code)

        # 4. 资金评分
        capital_score = self._load_capital_score(stock_code)

        # 5. 活跃度趋势
        activity = self._load_activity(stock_code)

        # 6. 交易策略信号（从 trade_signals 表）
        trade_strategy_signals = self._load_trade_signals(stock_code)

        # 7. 信号整合
        signals = self._collect_signals(
            quick_scan_result=quick_scan_result,
            flow_signals=flow_signals or [],
            trade_strategy_signals=trade_strategy_signals,
            technicals=technicals,
            kline_pattern=kline_pattern,
            capital_score=capital_score,
        )

        # 8. 综合判定
        verdict = self._generate_verdict(signals, quick_scan_result)

        return {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "last_kline_date": klines[-1].get("time_key", "")[:10] if klines else "",
            "stock_tag": stock_tag.to_dict(),
            "key_levels": key_levels.to_dict(),
            "capital_flow": capital_flow,
            "capital_score": capital_score,
            "activity": activity,
            "kline_pattern": kline_pattern,
            "signals": signals,
            "verdict": verdict,
        }

    # ==================== 数据读取 ====================

    def _get_stock_name(self, stock_code: str) -> str:
        try:
            rows = self.db.execute_query(
                "SELECT name FROM stocks WHERE code = ?", (stock_code,)
            )
            return rows[0][0] if rows else stock_code
        except Exception:
            return stock_code

    def _load_klines(self, stock_code: str, limit: int = 30) -> list:
        """加载K线数据（排除当天未完成K线，技术指标只用已收盘数据）"""
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            rows = self.db.execute_query("""
                SELECT time_key, open_price, high_price, low_price, close_price,
                       volume, turnover_rate
                FROM kline_data WHERE stock_code = ? AND date(time_key) < ?
                ORDER BY time_key DESC LIMIT ?
            """, (stock_code, today, limit))
            if not rows:
                return []
            cols = ["time_key", "open_price", "high_price", "low_price", "close_price",
                    "volume", "turnover_rate"]
            klines = [dict(zip(cols, r)) for r in rows]
            klines.reverse()
            return klines
        except Exception as e:
            logger.warning(f"加载K线失败 {stock_code}: {e}")
            return []

    def _load_capital_flow(self, stock_code: str) -> dict:
        timeline = []
        continuity_days = 0
        try:
            rows = self.db.execute_query("""
                SELECT date, net_inflow FROM capital_flow_daily
                WHERE stock_code = ? ORDER BY date DESC LIMIT 10
            """, (stock_code,))
            if rows:
                for r in rows:
                    timeline.append({
                        "date": r[0][-5:] if r[0] else "",  # MM-DD
                        "net_inflow": r[1] or 0,
                    })
                # 连续流入天数
                for r in rows:
                    if r[1] and r[1] > 0:
                        continuity_days += 1
                    else:
                        break
                timeline.reverse()
        except Exception as e:
            logger.warning(f"加载资金流失败 {stock_code}: {e}")

        # 趋势文本
        if len(timeline) >= 2:
            last = timeline[-1]["net_inflow"]
            prev = timeline[-2]["net_inflow"]
            if last > 0 and prev <= 0:
                trend_text = "今日大幅转正"
            elif last > 0 and prev > 0:
                trend_text = f"连续{continuity_days}天流入"
            elif last <= 0 and prev > 0:
                trend_text = "今日转负"
            else:
                trend_text = "持续流出"
        else:
            trend_text = "数据不足"

        return {
            "timeline": timeline,
            "continuity_days": continuity_days,
            "trend_text": trend_text,
        }

    def _load_capital_score(self, stock_code: str) -> dict:
        try:
            rows = self.db.execute_query("""
                SELECT capital_score, net_inflow_ratio, big_order_buy_ratio, main_net_inflow
                FROM capital_flow_cache WHERE stock_code = ?
                ORDER BY created_at DESC LIMIT 1
            """, (stock_code,))
            if rows:
                return {
                    "score": rows[0][0] or 0,
                    "net_inflow_ratio": rows[0][1] or 0,
                    "big_order_ratio": rows[0][2] or 0,
                    "main_net_inflow": rows[0][3] or 0,
                }
        except Exception as e:
            logger.warning(f"加载资金评分失败 {stock_code}: {e}")
        return {"score": 0, "net_inflow_ratio": 0, "big_order_ratio": 0, "main_net_inflow": 0}

    def _load_activity(self, stock_code: str) -> list:
        try:
            rows = self.db.execute_query("""
                SELECT check_date, turnover_rate, turnover_amount
                FROM daily_active_stocks WHERE stock_code = ?
                ORDER BY check_date DESC LIMIT 3
            """, (stock_code,))
            result = []
            for r in rows:
                result.append({
                    "date": r[0][-5:] if r[0] else "",
                    "turnover_rate": round(r[1] or 0, 2),
                    "turnover_amount": r[2] or 0,
                })
            result.reverse()
            return result
        except Exception as e:
            logger.warning(f"加载活跃度失败 {stock_code}: {e}")
            return []

    def _load_trade_signals(self, stock_code: str) -> list:
        """加载今天的交易策略信号"""
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            rows = self.db.execute_query("""
                SELECT ts.signal_type, ts.strategy_id, ts.strategy_name,
                       ts.condition_text, ts.signal_price, ts.created_at
                FROM trade_signals ts
                JOIN stocks s ON ts.stock_id = s.id
                WHERE s.code = ? AND ts.created_at >= ?
                ORDER BY ts.created_at DESC
            """, (stock_code, today))
            signals = []
            for r in rows:
                signals.append({
                    "signal_type": r[0],
                    "strategy_id": r[1] or "",
                    "strategy_name": r[2] or r[1] or "",
                    "condition_text": r[3] or "",
                    "signal_price": r[4] or 0,
                    "created_at": r[5] or "",
                })
            return signals
        except Exception as e:
            logger.warning(f"加载交易策略信号失败 {stock_code}: {e}")
            return []

    # ==================== 计算逻辑 ====================

    def _calc_technicals(self, klines: list) -> dict:
        """从K线计算技术指标"""
        if len(klines) < 5:
            return {}

        closes = [k["close_price"] for k in klines if k.get("close_price")]
        if not closes:
            return {}

        n = len(closes)
        ma5 = sum(closes[-5:]) / min(5, n)
        ma10 = sum(closes[-10:]) / min(10, n)
        ma20 = sum(closes[-20:]) / min(20, n) if n >= 10 else ma10

        current = closes[-1]

        # 均线信号
        def ma_signal(price, ma):
            return "上穿" if price > ma else "下穿"

        # 乖离率
        deviation = (current - ma20) / ma20 * 100 if ma20 > 0 else 0

        # 位置
        highs = [k["high_price"] for k in klines if k.get("high_price")]
        lows = [k["low_price"] for k in klines if k.get("low_price")]
        high_20d = max(highs) if highs else current
        low_20d = min(lows) if lows else current
        position = (current - low_20d) / (high_20d - low_20d) if high_20d > low_20d else 0.5

        # 均线排列
        if ma5 > ma10 > ma20:
            ma_alignment = "多头排列"
        elif ma5 < ma10 < ma20:
            ma_alignment = "空头排列"
        else:
            ma_alignment = "交叉"

        # 涨跌幅
        chg_5d = (closes[-1] - closes[-min(6, n)]) / closes[-min(6, n)] * 100 if n >= 2 else 0
        chg_10d = (closes[-1] - closes[-min(11, n)]) / closes[-min(11, n)] * 100 if n >= 2 else 0

        # ATR
        trs = []
        for i in range(1, len(klines)):
            h = klines[i].get("high_price", 0)
            l = klines[i].get("low_price", 0)
            pc = klines[i - 1].get("close_price", 0)
            if h and l and pc:
                tr = max(h - l, abs(h - pc), abs(l - pc))
                trs.append(tr)
        atr = sum(trs[-14:]) / min(14, len(trs)) if trs else 0
        atr_pct = atr / current * 100 if current > 0 else 0

        return {
            "ma5": round(ma5, 3),
            "ma10": round(ma10, 3),
            "ma20": round(ma20, 3),
            "ma5_signal": ma_signal(current, ma5),
            "ma10_signal": ma_signal(current, ma10),
            "ma20_signal": ma_signal(current, ma20),
            "ma_alignment": ma_alignment,
            "deviation_rate": round(deviation, 2),
            "position_20d": round(position, 2),
            "chg_5d": round(chg_5d, 2),
            "chg_10d": round(chg_10d, 2),
            "atr": round(atr, 3),
            "atr_pct": round(atr_pct, 2),
        }

    def _calc_kline_pattern(self, klines: list) -> dict:
        """分析最后一根K线形态"""
        if not klines:
            return {"type": "无数据", "upper_shadow_ratio": 0, "lower_shadow_ratio": 0,
                    "pattern_name": "无数据", "pattern_signal": "neutral"}

        k = klines[-1]
        o = k.get("open_price", 0)
        c = k.get("close_price", 0)
        h = k.get("high_price", 0)
        l = k.get("low_price", 0)

        if not all([o, c, h, l]):
            return {"type": "无数据", "upper_shadow_ratio": 0, "lower_shadow_ratio": 0,
                    "pattern_name": "无数据", "pattern_signal": "neutral"}

        body = abs(c - o)
        total_range = h - l if h > l else 0.001
        upper_shadow = h - max(o, c)
        lower_shadow = min(o, c) - l

        upper_ratio = round(upper_shadow / total_range * 100) if total_range > 0 else 0
        lower_ratio = round(lower_shadow / total_range * 100) if total_range > 0 else 0
        body_ratio = round(body / total_range * 100) if total_range > 0 else 0

        ktype = "阳线" if c >= o else "阴线"

        # 形态判定（用大白话描述）
        if body_ratio < 10:
            pattern_name = "多空僵持（开盘收盘几乎一样）"
            signal = "neutral"
        elif upper_ratio >= 50 and lower_ratio < 20:
            pattern_name = "冲高被打回"
            signal = "bearish"
        elif lower_ratio >= 50 and upper_ratio < 20:
            pattern_name = "下探被拉回"
            signal = "bullish"
        elif upper_ratio >= 40 and lower_ratio >= 40:
            pattern_name = "大幅震荡"
            signal = "neutral"
        elif c >= o and body_ratio >= 60:
            pattern_name = "强势上涨"
            signal = "bullish"
        elif c < o and body_ratio >= 60:
            pattern_name = "强势下跌"
            signal = "bearish"
        else:
            pattern_name = "小幅收涨" if c >= o else "小幅收跌"
            signal = "bullish" if c >= o else "bearish"

        return {
            "type": ktype,
            "body_ratio": body_ratio,
            "upper_shadow_ratio": upper_ratio,
            "lower_shadow_ratio": lower_ratio,
            "pattern_name": pattern_name,
            "pattern_signal": signal,
        }

    # ==================== 信号整合 ====================

    def _collect_signals(self, quick_scan_result, flow_signals,
                         trade_strategy_signals, technicals,
                         kline_pattern, capital_score) -> dict:
        bullish = []
        bearish = []
        neutral = []

        # 1. 快速扫描判定（权重3）
        if quick_scan_result:
            vt = quick_scan_result.get("verdict_type", "")
            verdict = quick_scan_result.get("verdict", "")
            confidence = (quick_scan_result.get("confidence", 50)) / 100

            signal_data = {
                "label": f"快速扫描: {verdict}",
                "source": "价位分析",
                "confidence": confidence,
                "weight": self.WEIGHT_QUICK_SCAN,
            }
            if vt in ("buy",):
                bullish.append(signal_data)
            elif vt in ("sell", "stop"):
                bearish.append(signal_data)
            else:
                neutral.append(signal_data)

        # 2. 操盘规则信号（权重2）
        for sig in flow_signals:
            signal_data = {
                "label": f"{sig.get('rule_id', '')}: {sig.get('rule_name', '')}",
                "source": "操盘规则",
                "reason": sig.get("reason", ""),
                "confidence": sig.get("confidence", 0.6),
                "weight": self.WEIGHT_FLOW_RULE,
            }
            st = sig.get("signal_type", "")
            if st == "BUY":
                bullish.append(signal_data)
            elif st == "SELL":
                bearish.append(signal_data)
            else:
                neutral.append(signal_data)

        # 3. 交易策略信号（权重2）
        for sig in trade_strategy_signals:
            label = sig.get("strategy_name", "") or sig.get("strategy_id", "")
            # 从 condition_text 提取简短描述
            cond = sig.get("condition_text", "")
            short_reason = cond[:80] if cond else ""

            signal_data = {
                "label": f"{label}: {'买入' if sig['signal_type'] == 'BUY' else '卖出'}信号",
                "source": "交易策略",
                "reason": short_reason,
                "confidence": 0.65,
                "weight": self.WEIGHT_TRADE_STRATEGY,
            }
            if sig["signal_type"] == "BUY":
                bullish.append(signal_data)
            else:
                bearish.append(signal_data)

        # 4. 技术指标（权重1）
        if technicals:

            # 位置
            pos = technicals.get("position_20d", 0.5)
            if pos <= 0.3:
                bullish.append({
                    "label": f"价格处于低位({pos*100:.0f}%)",
                    "source": "技术面",
                    "confidence": 0.6,
                    "weight": self.WEIGHT_TECHNICAL,
                })
            elif pos >= 0.7:
                bearish.append({
                    "label": f"价格处于高位({pos*100:.0f}%)",
                    "source": "技术面",
                    "confidence": 0.6,
                    "weight": self.WEIGHT_TECHNICAL,
                })



        # 5. K线形态（权重1）
        if kline_pattern and kline_pattern.get("pattern_name") != "无数据":
            upper = kline_pattern.get("upper_shadow_ratio", 0)
            lower = kline_pattern.get("lower_shadow_ratio", 0)
            ps = kline_pattern.get("pattern_signal", "neutral")

            if ps == "bearish" and upper >= 50:
                bearish.append({
                    "label": f"冲高后回落（回落幅度{upper}%）",
                    "source": "K线形态",
                    "detail": "盘中拉高后被卖盘打压",
                    "confidence": 0.6,
                    "weight": self.WEIGHT_TECHNICAL,
                })
            elif ps == "bullish" and lower >= 50:
                bullish.append({
                    "label": f"探底后回升（回升幅度{lower}%）",
                    "source": "K线形态",
                    "detail": "盘中下探后被买盘拉回",
                    "confidence": 0.6,
                    "weight": self.WEIGHT_TECHNICAL,
                })

        # 6. 资金评分（权重1）
        score = capital_score.get("score", 0)
        if score >= 60:
            bullish.append({
                "label": f"资金评分{score:.0f}分",
                "source": "资金面",
                "detail": f"大单买入比{capital_score.get('big_order_ratio', 0)*100:.1f}%",
                "confidence": 0.6,
                "weight": self.WEIGHT_TECHNICAL,
            })
        elif score <= 40 and score > 0:
            bearish.append({
                "label": f"资金评分{score:.0f}分",
                "source": "资金面",
                "detail": f"大单买入比{capital_score.get('big_order_ratio', 0)*100:.1f}%",
                "confidence": 0.6,
                "weight": self.WEIGHT_TECHNICAL,
            })

        return {
            "bullish": bullish,
            "bearish": bearish,
            "neutral": neutral,
            "bullish_count": len(bullish),
            "bearish_count": len(bearish),
        }

    # ==================== 综合判定 ====================

    def _generate_verdict(self, signals: dict, quick_scan_result: Optional[dict]) -> dict:
        bullish_score = sum(
            s.get("weight", 1) * s.get("confidence", 0.6)
            for s in signals["bullish"]
        )
        bearish_score = sum(
            s.get("weight", 1) * s.get("confidence", 0.6)
            for s in signals["bearish"]
        )

        total = bullish_score + bearish_score
        if total == 0:
            bullish_ratio = 0.5
        else:
            bullish_ratio = bullish_score / total

        # 情绪判定
        if bullish_ratio >= 0.65:
            sentiment = "偏多"
            emoji = "🟢"
        elif bullish_ratio <= 0.35:
            sentiment = "偏空"
            emoji = "🔴"
        elif bullish_ratio >= 0.55:
            sentiment = "中性偏多"
            emoji = "🟡"
        elif bullish_ratio <= 0.45:
            sentiment = "中性偏空"
            emoji = "🟡"
        else:
            sentiment = "中性"
            emoji = "🟡"

        # 情景预判
        if bullish_ratio >= 0.65:
            scenarios = [
                {"name": "放量突破", "probability": 50, "type": "bullish"},
                {"name": "震荡整理", "probability": 35, "type": "neutral"},
                {"name": "冲高回落", "probability": 15, "type": "bearish"},
            ]
        elif bullish_ratio <= 0.35:
            scenarios = [
                {"name": "冲高回落", "probability": 50, "type": "bearish"},
                {"name": "震荡整理", "probability": 40, "type": "neutral"},
                {"name": "放量突破", "probability": 10, "type": "bullish"},
            ]
        else:
            scenarios = [
                {"name": "震荡整理", "probability": 50, "type": "neutral"},
                {"name": "放量突破", "probability": 30, "type": "bullish"},
                {"name": "冲高回落", "probability": 20, "type": "bearish"},
            ]

        # 判定文本
        verdict_text = ""
        if quick_scan_result and quick_scan_result.get("price_analysis"):
            pa = quick_scan_result["price_analysis"]
            buy_t = pa.get("buy_target", 0)
            sell_t = pa.get("sell_target", 0)
            if sell_t > 0:
                verdict_text = f"关键看能否突破{sell_t:.2f}元"
            elif buy_t > 0:
                verdict_text = f"关键看能否守住{buy_t:.2f}元"
        if not verdict_text:
            verdict_text = f"综合信号{sentiment}"

        return {
            "text": verdict_text,
            "sentiment": sentiment,
            "emoji": emoji,
            "bullish_score": round(bullish_score, 2),
            "bearish_score": round(bearish_score, 2),
            "scenarios": scenarios,
        }
