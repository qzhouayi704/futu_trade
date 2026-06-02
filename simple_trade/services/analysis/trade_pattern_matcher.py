#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易模式匹配器 — 基于真实交易数据分析的选股引擎

数据驱动的4种买入模式（从富途API历史成交提取）：
A. 强势追涨型：K线高位 + 放量 + 大涨 + 阳线（成功率最高）
B. 中位突破型：中位 + 适度涨幅 + 量比适中 + 阳线（稳健）
C. 低位反弹型：极低位 + 深度回撤 + 放量止跌（波动大）
D. 爆发追入型：5日涨幅极大 + 超级强势（高风险高回报）
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger("trade_pattern_matcher")


# ==================== 模式定义（从真实交易数据总结） ====================

PATTERN_DEFS = {
    "A": {
        "name": "\U0001f525 强势追涨",
        "desc": "K线高位+放量+大涨+阳线，追已启动的强势股",
        "color": "red",
    },
    "B": {
        "name": "\U0001f4c8 中位突破",
        "desc": "中位放量突破，趋势确认后介入",
        "color": "blue",
    },
    "C": {
        "name": "\U0001f504 低位反弹",
        "desc": "深度回调后的超跌反弹，放量止跌",
        "color": "green",
    },
    "D": {
        "name": "\u26a1 爆发追入",
        "desc": "5日涨幅极大，动能极强",
        "color": "orange",
    },
}


class TradePatternMatcher:
    """交易模式匹配引擎"""

    def __init__(self, db_manager, container=None):
        self.db = db_manager
        self.container = container

    async def find_similar_stocks(self) -> Dict[str, Any]:
        """主入口：分析历史买入模式 -> 匹配当前市场中类似股票"""

        # 1. 从富途API获取真实交易记录，提取成功模式
        patterns = self._extract_buy_patterns()
        if not patterns:
            return {
                "trade_patterns": [],
                "similar_stocks": [],
                "pattern_summary": {},
                "analyzed_at": datetime.now().isoformat(),
                "message": "无法从富途API获取交易记录，或无成功买入记录"
            }

        # 统计各模式数量
        pattern_counts = {}
        for p in patterns:
            pt = p.get("pattern_type_id", "?")
            pattern_counts[pt] = pattern_counts.get(pt, 0) + 1

        logger.info(
            f"[模式匹配] 提取到 {len(patterns)} 个成功买入模式: "
            + ", ".join(f"{k}={v}" for k, v in pattern_counts.items())
        )

        # 2. 获取当前股票池
        pool_stocks = self._get_stock_pool()
        if not pool_stocks:
            return {
                "trade_patterns": [p["summary"] for p in patterns],
                "similar_stocks": [],
                "pattern_summary": pattern_counts,
                "analyzed_at": datetime.now().isoformat(),
                "message": "股票池为空"
            }

        # 3. 对每只股票进行模式匹配
        similar = []
        for stock in pool_stocks:
            code = stock["code"]
            result = self._match_stock_to_patterns(code, stock)
            if result and result["score"] >= 50:
                similar.append(result)

        similar.sort(key=lambda x: x["score"], reverse=True)

        return {
            "trade_patterns": [p["summary"] for p in patterns],
            "similar_stocks": similar[:20],
            "pattern_summary": pattern_counts,
            "analyzed_at": datetime.now().isoformat(),
        }

    # ==================== 从富途API获取真实交易记录 ====================

    def _get_futu_buy_deals(self) -> List[Dict]:
        """从富途API获取账户真实历史买入成交记录"""
        trade_service = getattr(self.container, 'futu_trade_service', None)
        if not trade_service:
            logger.warning("[模式匹配] futu_trade_service 不可用")
            return []

        order_mgr = getattr(trade_service, 'order_manager', None)
        if not order_mgr:
            logger.warning("[模式匹配] order_manager 不可用")
            return []

        trade_client = getattr(order_mgr, 'trade_client', None)
        if not trade_client:
            logger.warning("[模式匹配] trade_client 未连接")
            return []

        try:
            from futu import RET_OK

            end_date = datetime.now()
            start_date = end_date - timedelta(days=60)

            ret, data = trade_client.history_deal_list_query(
                start=start_date.strftime('%Y-%m-%d 00:00:00'),
                end=end_date.strftime('%Y-%m-%d 23:59:59'),
                trd_env=getattr(order_mgr, 'trd_env', None),
            )

            if ret != RET_OK or data is None:
                logger.warning(f"[模式匹配] 获取历史成交失败: {data}")
                return []

            deals = []
            for _, row in data.iterrows():
                if str(row.get('trd_side', '')) != 'BUY':
                    continue
                code = row.get('code', '')
                price = float(row.get('price', 0))
                if code and price > 0:
                    deals.append({
                        "code": code,
                        "name": str(row.get('stock_name', '')),
                        "buy_price": price,
                        "buy_time": str(row.get('create_time', '')),
                        "quantity": int(row.get('qty', 0)),
                    })

            logger.info(f"[模式匹配] 从富途API获取到 {len(deals)} 条买入成交")
            return deals

        except Exception as e:
            logger.error(f"[模式匹配] 获取富途历史成交异常: {e}", exc_info=True)
            return []

    # ==================== 提取成功的买入模式 ====================

    def _extract_buy_patterns(self) -> List[Dict[str, Any]]:
        """从富途API获取真实买入记录，过滤成功交易，归类模式"""
        buy_deals = self._get_futu_buy_deals()
        if not buy_deals:
            return []

        # 按股票去重（取最近一次）
        seen = set()
        unique = []
        for d in buy_deals:
            if d["code"] not in seen:
                seen.add(d["code"])
                unique.append(d)

        patterns = []
        for record in unique[:20]:
            pattern = self._analyze_and_classify(record)
            if pattern:
                patterns.append(pattern)

        return patterns

    def _analyze_and_classify(self, record: Dict) -> Optional[Dict]:
        """分析一笔买入，验证成功后归类到模式A/B/C/D"""
        code = record["code"]
        buy_price = record["buy_price"]
        buy_time = record["buy_time"]
        stock_name = record.get("name", "")

        try:
            buy_date = buy_time.split(" ")[0].split("T")[0]
        except Exception:
            return None

        # 验证买入后有上涨
        if not self._verify_post_buy_rise(code, buy_date, buy_price):
            return None

        # 获取买入前K线
        features = self._extract_features(code, buy_date)
        if not features:
            return None

        # 归类模式
        pattern_id = self._classify_pattern(features)

        if not stock_name:
            stock_name = self.db.stock_queries.get_stock_name(code)

        rise_info = self._get_post_buy_rise_info(code, buy_date, buy_price)
        pdef = PATTERN_DEFS.get(pattern_id, {})

        return {
            "code": code,
            "name": stock_name,
            "features": features,
            "pattern_type_id": pattern_id,
            "pattern_type": pdef.get("name", pattern_id),
            "summary": {
                "stock_code": code,
                "stock_name": stock_name,
                "buy_price": record["buy_price"],
                "buy_time": record["buy_time"],
                "pattern_type": pdef.get("name", pattern_id),
                "drop_from_peak": features["drop_from_peak"],
                "kline_position": features["kline_position"],
                "volume_ratio": features["volume_ratio"],
                "recent_5d_change": features["recent_5d_change"],
                "post_buy_rise": rise_info,
            }
        }

    def _classify_pattern(self, feat: Dict) -> str:
        """根据特征归类到模式A/B/C/D"""
        pos = feat["kline_position"]
        change_5d = feat["recent_5d_change"]
        vol_ratio = feat["volume_ratio"]
        bullish = feat["last_is_bullish"]
        drop = feat["drop_from_peak"]

        # D: 爆发追入 — 5日涨幅≥50%
        if change_5d >= 50:
            return "D"

        # A: 强势追涨 — 高位+大涨+放量
        if pos >= 0.7 and change_5d >= 15:
            return "A"

        # C: 低位反弹 — 极低位+深度回撤
        if pos <= 0.25 and drop >= 15:
            return "C"

        # B: 中位突破 — 中位+适度涨幅
        if 0.3 <= pos <= 0.65 and change_5d > 0:
            return "B"

        # 默认按位置判断
        if pos >= 0.6:
            return "A"
        if pos <= 0.3:
            return "C"
        return "B"

    # ==================== 当前股票的模式匹配 ====================

    def _match_stock_to_patterns(
        self, code: str, stock: Dict
    ) -> Optional[Dict]:
        """检测一只股票是否匹配历史成功买入的ABCD模式"""
        features = self._extract_features(code)
        if not features:
            return None

        pos = features["kline_position"]
        change_5d = features["recent_5d_change"]
        vol_ratio = features["volume_ratio"]
        bullish = features["last_is_bullish"]
        drop = features["drop_from_peak"]
        bouncing = features["bouncing"]

        vol_trend, price_trend = self._calc_short_trends(code)

        best_score = 0
        best_pattern = ""
        reasons = []

        # ===== 模式A：强势追涨 =====
        # 真实盈利范围：pos 0.74~1.00, 5d涨幅 +8%~+43%, 放量
        # 核心：必须已经是强势启动（5日涨幅≥8%），不是慢涨
        score_a = 0
        reasons_a = []

        # 门槛：5日涨幅≥8%（真实盈利交易的最低值）
        if change_5d >= 15:
            score_a += 25
            reasons_a.append(f"5日涨{change_5d:.1f}%")
        elif change_5d >= 8:
            score_a += 18
            reasons_a.append(f"5日涨{change_5d:.1f}%")
        # 涨幅<8%不给分（不符合模式A真实特征）

        # 高位确认（真实范围：0.74~1.00）
        if pos >= 0.7:
            score_a += 15
            reasons_a.append(f"强势位({pos:.0%})")
        elif pos >= 0.5:
            score_a += 8  # 中位启动，降权

        # 放量确认
        if vol_ratio >= 2.0:
            score_a += 20
            reasons_a.append(f"放量{vol_ratio:.1f}x")
        elif vol_ratio >= 1.3:
            score_a += 12
            reasons_a.append(f"放量{vol_ratio:.1f}x")

        # 阳线确认
        if bullish and score_a > 0:
            score_a += 10
            reasons_a.append("阳线突破")

        # 量价齐升趋势
        if vol_trend > 0 and price_trend > 0 and score_a > 0:
            score_a += 12
            reasons_a.append("量价齐升")

        if score_a > best_score:
            best_score = score_a
            best_pattern = "A"
            reasons = reasons_a

        # ===== 模式B：中位突破 =====
        # 真实盈利范围：pos 0.30~0.47, 5d涨跌 -7%~+2%, 温和企稳
        # 核心：回调到中位+开始企稳（不是高位也不是低位）
        score_b = 0
        reasons_b = []

        # 中位区间（真实范围0.25~0.50）
        if 0.25 <= pos <= 0.50:
            score_b += 20
            reasons_b.append(f"中位区({pos:.0%})")
        elif 0.20 <= pos <= 0.65:
            score_b += 10

        # 适度回调（真实范围 drop 2%~20%）
        if 5 <= drop <= 20:
            score_b += 18
            reasons_b.append(f"回调{drop:.1f}%")
        elif 2 <= drop <= 25:
            score_b += 10

        # 5日涨跌在真实范围内（-7%~+2%，企稳阶段）
        if -7 <= change_5d <= 3:
            score_b += 15
            reasons_b.append("企稳阶段")
        elif -10 <= change_5d <= 5:
            score_b += 8

        # 开始企稳反弹
        if bullish and score_b > 0:
            score_b += 12
            reasons_b.append("止跌阳线")

        # 量能未萎缩
        if vol_ratio >= 1.0 and score_b > 0:
            score_b += 10
            if vol_ratio >= 1.3:
                reasons_b.append(f"量比{vol_ratio:.1f}")

        # 价格趋势转正
        if price_trend > 0 and score_b > 0:
            score_b += 8
            reasons_b.append("趋势转正")

        if score_b > best_score:
            best_score = score_b
            best_pattern = "B"
            reasons = reasons_b

        # ===== 模式C：低位反弹（盈利率最高73%） =====
        # 真实盈利范围：pos 0.01~0.28, 5d涨跌 -26%~0%, drop 8%~73%
        # 核心：极低位+深度回撤+止跌迹象
        score_c = 0
        reasons_c = []

        # 门槛：低位（真实范围 pos ≤ 0.28）
        if pos <= 0.15:
            score_c += 25
            reasons_c.append(f"极低位({pos:.0%})")
        elif pos <= 0.30:
            score_c += 18
            reasons_c.append(f"低位({pos:.0%})")
        # 超过0.30不给分

        # 深度回撤（真实范围 drop ≥ 8%）
        if drop >= 20:
            score_c += 20
            reasons_c.append(f"深跌{drop:.1f}%")
        elif drop >= 10:
            score_c += 15
            reasons_c.append(f"回撤{drop:.1f}%")
        elif drop >= 8:
            score_c += 10

        # 止跌信号
        if bouncing and score_c > 0:
            score_c += 18
            reasons_c.append("放量反弹")
        elif bullish and score_c > 0:
            score_c += 12
            reasons_c.append("止跌阳线")

        # 量能恢复
        if vol_ratio >= 1.2 and score_c > 0:
            score_c += 10
            reasons_c.append(f"量能恢复{vol_ratio:.1f}x")

        # 5日跌幅在真实范围内（跌势趋缓）
        if change_5d >= 0 and score_c > 0:
            score_c += 8
            reasons_c.append("跌势已止")
        elif change_5d >= -10 and score_c > 0:
            score_c += 5

        if score_c > best_score:
            best_score = score_c
            best_pattern = "C"
            reasons = reasons_c

        # ===== 模式D：爆发追入 =====
        # 真实范围：5日涨幅 ≥50%，极端强势
        score_d = 0
        reasons_d = []
        if change_5d >= 50:
            score_d = 90
            reasons_d = [f"5日暴涨{change_5d:.1f}%", "超级强势"]
        elif change_5d >= 35:
            score_d = 70
            reasons_d = [f"5日大涨{change_5d:.1f}%", "强势爆发"]
        if vol_ratio >= 2.0 and score_d > 0:
            score_d += 10
            reasons_d.append(f"放量{vol_ratio:.1f}x")

        if score_d > best_score:
            best_score = score_d
            best_pattern = "D"
            reasons = reasons_d

        if best_score < 50 or not best_pattern:
            return None

        # ===== 融入盘后优选体系的已验证指标（加分/减分/排除） =====
        confirmed = self._apply_verified_indicators(code, best_score, best_pattern, reasons)
        if confirmed is None:
            return None  # 被已验证指标排除

        best_score = confirmed["score"]
        reasons = confirmed["reasons"]

        pdef = PATTERN_DEFS.get(best_pattern, {})
        metrics = self._get_current_metrics(code, stock)

        # ===== 当日实时行情修正 =====
        today_change = metrics.get("today_change")
        if today_change is not None:
            if today_change <= -8:
                return None  # 今日暴跌，直接排除
            elif today_change <= -5:
                best_score -= 40
                reasons.append(f"⚠今日跌{today_change:.1f}%")
            elif today_change <= -3:
                best_score -= 20
                reasons.append(f"⚠今日跌{today_change:.1f}%")
            elif today_change >= 3:
                best_score += 5  # 今日涨势好，微加分

        if best_score < 50:
            return None  # 降分后不够阈值

        return {
            "stock_code": code,
            "stock_name": stock.get("name", ""),
            "score": round(best_score, 1),
            "pattern_id": best_pattern,
            "pattern_name": pdef.get("name", ""),
            "pattern_desc": pdef.get("desc", ""),
            "pattern_color": pdef.get("color", "blue"),
            "reasons": reasons,
            "stage": self._determine_stage(features),
            "matched_patterns": reasons[:3],
            "similarity_score": round(best_score, 1),
            "current_metrics": metrics,
        }

    def _apply_verified_indicators(
        self, code: str, score: float, pattern: str, reasons: list
    ) -> Optional[Dict]:
        """
        融入盘后优选体系中已经回测验证过的指标，作为二次确认。

        加分项（来自 overnight_screener 的 P1/P2/P5 规则）：
        - 资金连续流入≥2天 → +10分
        - 资金连续流入≥3天 → +15分
        - 大单买卖比≥1.5 → +10分
        - 趋势反转买入信号 → +10分
        - 资金评分≥70 → +8分

        排除条件（来自 overnight_screener 的排除规则）：
        - 资金大幅流出(净流出>5%) + 涨幅>5% → 排除（量价背离R2）
        - 20日累跌>20% → 排除（深度下跌趋势）
        - 趋势反转卖出信号明确 → 排除

        减分项：
        - 资金刚转正但流入不足(<3%) → 分数*0.7
        - 换手率<0.3% → 排除（流动性不足）
        """
        reasons = list(reasons)  # 复制

        # --- 资金连续流入天数（P1: R11规则，权重20%） ---
        cont_days = 0
        try:
            rows = self.db.execute_query(
                "SELECT net_inflow FROM capital_flow_daily "
                "WHERE stock_code = ? ORDER BY date DESC LIMIT 10",
                (code,)
            )
            if rows:
                for r in rows:
                    if r[0] and r[0] > 0:
                        cont_days += 1
                    else:
                        break
        except Exception:
            pass

        if cont_days >= 5:
            score += 20
            reasons.append(f"资金连续{cont_days}日流入")
        elif cont_days >= 3:
            score += 15
            reasons.append(f"资金连续{cont_days}日流入")
        elif cont_days >= 2:
            score += 10
            reasons.append(f"资金连续{cont_days}日流入")

        # --- 资金评分 + 净流入比 ---
        cap_score_val = 50.0
        net_ratio = 0.0
        try:
            cap_rows = self.db.execute_query(
                "SELECT capital_score, net_inflow_ratio FROM capital_flow_cache "
                "WHERE stock_code = ? ORDER BY timestamp DESC LIMIT 1",
                (code,)
            )
            if cap_rows:
                cap_score_val = float(cap_rows[0][0] or 50)
                net_ratio = float(cap_rows[0][1] or 0)
        except Exception:
            pass

        # 排除：资金大幅流出+高位（R2规则）
        if net_ratio < -0.05:
            return None

        # 资金评分≥70 加分（P4规则，回测确认阈值）
        if cap_score_val >= 70:
            score += 8
            reasons.append(f"资金偏多({cap_score_val:.0f}分)")

        # 资金刚转正但力度不足 → 降权（R4规则）
        if cont_days == 1 and 0 < net_ratio < 0.03:
            score *= 0.7
            reasons.append("资金转正但力度不足")

        # --- 资金流入衰减检查（R5规则：流入量急剧缩减） ---
        try:
            flow_rows = self.db.execute_query(
                "SELECT net_inflow FROM capital_flow_daily "
                "WHERE stock_code = ? ORDER BY date DESC LIMIT 3",
                (code,)
            )
            if flow_rows and len(flow_rows) >= 2:
                today_flow = float(flow_rows[0][0] or 0)
                yest_flow = float(flow_rows[1][0] or 0)
                # 昨天大幅流入但今天急剧缩减(>50%)
                if yest_flow > 0 and today_flow > 0 and today_flow < yest_flow * 0.5:
                    score -= 10
                    reasons.append(f"⚠资金流入骤减{(1-today_flow/yest_flow)*100:.0f}%")
        except Exception:
            pass

        # --- 高位+资金衰减组合惩罚（R6规则：追高风险） ---
        try:
            klines_pos = self.db.execute_query(
                "SELECT close_price, high_price, low_price FROM kline_data "
                "WHERE stock_code = ? ORDER BY time_key DESC LIMIT 10",
                (code,)
            )
            if klines_pos and len(klines_pos) >= 5:
                klines_pos = list(reversed(klines_pos))
                cls = [float(k[0]) for k in klines_pos if k[0]]
                hs = [float(k[1]) for k in klines_pos if k[1]]
                ls = [float(k[2]) for k in klines_pos if k[2]]
                if cls and hs and ls:
                    hh, ll = max(hs), min(ls)
                    pos = (cls[-1] - ll) / (hh - ll) if hh > ll else 0.5
                    # 连涨天数
                    up_days = 0
                    for j in range(len(cls)-1, 0, -1):
                        if cls[j] > cls[j-1]:
                            up_days += 1
                        else:
                            break
                    # 高位(>0.8) + 连涨≥3天 + 大单偏空 → 追高风险
                    if pos > 0.8 and up_days >= 3:
                        score -= 25
                        reasons.append(f"⚠高位连涨{up_days}天(位置{pos:.0%})")
                    elif pos > 0.7 and up_days >= 4:
                        score -= 15
                        reasons.append(f"⚠偏高连涨{up_days}天")
        except Exception:
            pass

        # --- 大单买卖比（P5规则，阈值>1.5来自回测） ---
        try:
            big_rows = self.db.execute_query(
                "SELECT big_buy_count, big_sell_count, buy_sell_ratio, order_strength "
                "FROM big_order_tracking "
                "WHERE stock_code = ? ORDER BY created_at DESC LIMIT 1",
                (code,)
            )
            if big_rows:
                buy_c = int(big_rows[0][0] or 0)
                sell_c = int(big_rows[0][1] or 0)
                ratio = float(big_rows[0][2] or 0)
                strength = float(big_rows[0][3] or 0)
                if ratio >= 1.5:
                    score += 10
                    reasons.append(f"大单买强({ratio:.1f})")
                elif ratio < 1.0 and sell_c > buy_c:
                    # 真实盈利交易大单比全部>1.5，<1.0说明卖方更强
                    score -= 15
                    reasons.append(f"⚠大单偏空({ratio:.1f})")
                elif ratio <= 0.5 and sell_c > 3:
                    score -= 25
                    reasons.append(f"⚠大单卖压({ratio:.1f})")
                # 订单强度为负也降分（盈利交易均>0）
                if strength < 0:
                    score -= 10
                    reasons.append(f"⚠订单偏空({strength:.2f})")
                elif strength <= -0.3:
                    score -= 20
                    reasons.append(f"⚠订单强空({strength:.2f})")
        except Exception:
            pass

        # --- 趋势反转信号（P2规则） ---
        try:
            sig_rows = self.db.execute_query(
                "SELECT signal_type FROM trade_signals ts "
                "JOIN stocks s ON ts.stock_id = s.id "
                "WHERE s.code = ? AND ts.created_at >= datetime('now', '-3 days') "
                "ORDER BY ts.created_at DESC LIMIT 1",
                (code,)
            )
            if sig_rows:
                sig_type = str(sig_rows[0][0])
                if sig_type == "BUY":
                    score += 10
                    reasons.append("趋势反转买入信号")
                elif sig_type == "SELL":
                    return None  # 排除有卖出信号的
        except Exception:
            pass

        # --- 20日深度下跌排除（回测确认阈值-20%） ---
        try:
            klines_20d = self.db.execute_query(
                "SELECT close_price FROM kline_data "
                "WHERE stock_code = ? ORDER BY time_key DESC LIMIT 20",
                (code,)
            )
            if klines_20d and len(klines_20d) >= 15:
                closes = [float(k[0]) for k in klines_20d if k[0]]
                if closes and closes[-1] > 0:
                    change_20d = (closes[0] - closes[-1]) / closes[-1] * 100
                    if change_20d < -20:
                        return None  # 深度下跌趋势排除
        except Exception:
            pass

        # --- 阻力位突破加分（整合突破扫描功能） ---
        try:
            brk_rows = self.db.execute_query(
                "SELECT high_price, close_price, open_price FROM kline_data "
                "WHERE stock_code = ? ORDER BY time_key DESC LIMIT 22",
                (code,)
            )
            if brk_rows and len(brk_rows) >= 6:
                brk_rows = list(reversed(brk_rows))
                today_close = float(brk_rows[-1][1] or 0)
                today_open = float(brk_rows[-1][2] or 0)
                prev_bars = brk_rows[:-1]
                # 必须是阳线或持平
                if today_close >= today_open * 0.995 and today_close > 0:
                    # 近3日收盘（用于判断"刚突破"）
                    recent_closes = [float(b[1] or 0) for b in prev_bars[-3:]]
                    highs_5 = max(float(b[0] or 0) for b in prev_bars[-5:]) if len(prev_bars) >= 5 else 0
                    highs_10 = max(float(b[0] or 0) for b in prev_bars[-10:]) if len(prev_bars) >= 10 else 0
                    highs_20 = max(float(b[0] or 0) for b in prev_bars[-20:]) if len(prev_bars) >= 20 else 0

                    def _just_broken(res):
                        return res > 0 and today_close > res and any(c <= res for c in recent_closes)

                    if _just_broken(highs_20):
                        score += 15
                        reasons.append("🔺突破20日高")
                    elif _just_broken(highs_10):
                        score += 10
                        reasons.append("🔺突破10日高")
                    elif _just_broken(highs_5):
                        score += 5
                        reasons.append("🔺突破5日高")
        except Exception:
            pass

        return {"score": score, "reasons": reasons}

    def _calc_short_trends(self, code: str) -> tuple:
        """
        计算近3日的量能趋势和价格趋势方向。

        Returns:
            (vol_trend, price_trend)
            正数=上升趋势, 负数=下降趋势, 0=无数据
        """
        try:
            rows = self.db.execute_query("""
                SELECT close_price, volume
                FROM kline_data WHERE stock_code = ?
                ORDER BY time_key DESC LIMIT 4
            """, (code,))
            if not rows or len(rows) < 3:
                return 0, 0

            # rows是倒序：[今天, 昨天, 前天, 大前天]
            closes = [float(r[0]) for r in rows if r[0]]
            volumes = [int(r[1]) for r in rows if r[1]]

            if len(closes) < 3 or len(volumes) < 3:
                return 0, 0

            # 价格趋势：今天 vs 前天
            price_trend = closes[0] - closes[2]

            # 量能趋势：近2日均量 vs 前2日均量
            recent_vol = (volumes[0] + volumes[1]) / 2
            prev_vol = (volumes[2] + volumes[3]) / 2 if len(volumes) >= 4 else volumes[2]
            vol_trend = recent_vol - prev_vol

            return vol_trend, price_trend
        except Exception:
            return 0, 0

    # ==================== 特征提取 ====================

    def _extract_features(self, code: str, up_to_date: str = None) -> Optional[Dict]:
        """从K线数据中提取特征"""
        try:
            if up_to_date:
                klines = self.db.execute_query("""
                    SELECT time_key, open_price, high_price, low_price,
                           close_price, volume, turnover_rate
                    FROM kline_data WHERE stock_code = ? AND time_key <= ?
                    ORDER BY time_key DESC LIMIT 25
                """, (code, up_to_date))
            else:
                klines = self.db.execute_query("""
                    SELECT time_key, open_price, high_price, low_price,
                           close_price, volume, turnover_rate
                    FROM kline_data WHERE stock_code = ?
                    ORDER BY time_key DESC LIMIT 25
                """, (code,))
        except Exception:
            return None

        if not klines or len(klines) < 5:
            return None

        klines = list(reversed(klines))
        closes = [float(k[4]) for k in klines if k[4]]
        volumes = [int(k[5]) for k in klines if k[5]]
        opens = [float(k[1]) for k in klines if k[1]]
        highs = [float(k[2]) for k in klines if k[2]]
        lows = [float(k[3]) for k in klines if k[3]]

        if not closes or len(closes) < 5:
            return None

        peak = max(closes)
        last = closes[-1]
        h, l = max(highs), min(lows)
        pos = (last - l) / (h - l) if h > l else 0.5
        drop = (peak - last) / peak * 100 if peak > 0 else 0
        change_5d = (closes[-1] - closes[-5]) / closes[-5] * 100 if closes[-5] > 0 else 0

        if len(volumes) >= 6:
            avg_vol = sum(volumes[-6:-1]) / 5
            vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1
        else:
            vol_ratio = 1

        bullish = closes[-1] > opens[-1] if opens else False
        bouncing = (
            len(closes) >= 3
            and closes[-1] > closes[-2]
            and volumes[-1] > volumes[-2]
        )

        return {
            "kline_position": round(pos, 2),
            "drop_from_peak": round(drop, 1),
            "recent_5d_change": round(change_5d, 1),
            "volume_ratio": round(vol_ratio, 2),
            "last_is_bullish": bullish,
            "bouncing": bouncing,
            "last_close": round(last, 3),
        }

    # ==================== 验证买入后上涨 ====================

    def _verify_post_buy_rise(self, code: str, buy_date: str, buy_price: float) -> bool:
        """验证买入后是否有上涨"""
        try:
            rows = self.db.execute_query("""
                SELECT high_price, close_price
                FROM kline_data WHERE stock_code = ? AND time_key >= ?
                ORDER BY time_key ASC LIMIT 4
            """, (code, buy_date))

            if not rows:
                return False

            day0_high = float(rows[0][0]) if rows[0][0] else 0
            day0_close = float(rows[0][1]) if rows[0][1] else 0

            if day0_high > buy_price * 1.005:
                return True
            if len(rows) >= 2:
                day1_close = float(rows[1][1]) if rows[1][1] else 0
                if day1_close > day0_close:
                    return True
            highs = [float(r[0]) for r in rows[:4] if r[0]]
            if highs and max(highs) > buy_price * 1.02:
                return True
            return False
        except Exception:
            return False

    def _get_post_buy_rise_info(self, code: str, buy_date: str, buy_price: float) -> Optional[Dict]:
        """获取买入后涨幅信息"""
        try:
            rows = self.db.execute_query("""
                SELECT high_price, close_price
                FROM kline_data WHERE stock_code = ? AND time_key >= ?
                ORDER BY time_key ASC LIMIT 6
            """, (code, buy_date))
            if not rows or len(rows) < 2:
                return None

            day0_close = float(rows[0][1]) if rows[0][1] else buy_price
            highs = [float(r[0]) for r in rows[:4] if r[0]]
            max_high = max(highs) if highs else buy_price
            max_rise = (max_high - buy_price) / buy_price * 100 if buy_price > 0 else 0
            day1_close = float(rows[1][1]) if rows[1][1] else day0_close
            day1_change = (day1_close - day0_close) / day0_close * 100 if day0_close > 0 else 0

            return {
                "max_rise_3d": round(max_rise, 1),
                "day1_change": round(day1_change, 1),
            }
        except Exception:
            return None

    # ==================== 阶段判定 ====================

    def _determine_stage(self, feat: Dict) -> str:
        """判断当前阶段"""
        pos = feat["kline_position"]
        change = feat["recent_5d_change"]
        vol = feat["volume_ratio"]
        bullish = feat["last_is_bullish"]
        bouncing = feat["bouncing"]

        if change >= 50:
            return "\u26a1 \u7206\u53d1\u4e2d"
        if pos >= 0.8 and change >= 15 and vol >= 1.5:
            return "\U0001f525 \u5f3a\u52bf\u8ffd\u6da8\u671f"
        if pos >= 0.7 and change >= 10:
            return "\U0001f680 \u4e3b\u5347\u671f"
        if 0.3 <= pos <= 0.6 and bullish and change > 0:
            return "\U0001f4c8 \u7a81\u7834\u671f"
        if pos <= 0.2 and bouncing:
            return "\U0001f504 \u53cd\u5f39\u542f\u52a8"
        if pos <= 0.3 and bullish:
            return "\U0001f331 \u5e95\u90e8\u6574\u7406"
        if pos <= 0.25:
            return "\U0001f4a4 \u4f4e\u4f4d\u5f85\u53d1"
        return "\U0001f4ca \u89c2\u671b"

    # ==================== 股票池 + 指标 ====================

    def _get_stock_pool(self) -> List[Dict]:
        """获取活跃股票池（有近期K线数据的非低活跃度股票）"""
        try:
            rows = self.db.execute_query("""
                SELECT s.code, s.name, s.market FROM stocks s
                WHERE (s.is_low_activity = 0 OR s.is_low_activity IS NULL)
                  AND s.code IN (
                    SELECT DISTINCT stock_code FROM kline_data
                    WHERE time_key >= date('now', '-7 days')
                  )
                LIMIT 300
            """)
            result = [{"code": r[0], "name": r[1], "market": r[2]} for r in (rows or [])]
            logger.info(f"[模式匹配] 股票池获取到 {len(result)} 只活跃股票")
            return result
        except Exception as e:
            logger.error(f"获取股票池失败: {e}")
            return []

    def _get_current_metrics(self, code: str, stock: Dict) -> Dict:
        """获取当前指标"""
        metrics = {"name": stock.get("name", "")}

        try:
            klines = self.db.execute_query("""
                SELECT close_price, high_price, low_price
                FROM kline_data WHERE stock_code = ?
                ORDER BY time_key DESC LIMIT 20
            """, (code,))
            if klines and len(klines) >= 5:
                klines = list(reversed(klines))
                closes = [float(k[0]) for k in klines if k[0]]
                highs = [float(k[1]) for k in klines if k[1]]
                lows = [float(k[2]) for k in klines if k[2]]

                if closes and highs and lows:
                    h, l = max(highs), min(lows)
                    metrics["kline_position"] = round(
                        (closes[-1] - l) / (h - l) if h > l else 0.5, 2
                    )
                    peak = max(closes)
                    metrics["drop_from_peak"] = round(
                        (peak - closes[-1]) / peak * 100 if peak > 0 else 0, 1
                    )
                    metrics["last_price"] = round(closes[-1], 3)
                    if len(closes) >= 5 and closes[-5] > 0:
                        metrics["change_5d"] = round(
                            (closes[-1] - closes[-5]) / closes[-5] * 100, 1
                        )
        except Exception:
            pass

        try:
            rows = self.db.execute_query(
                "SELECT capital_score, net_inflow_ratio FROM capital_flow_cache "
                "WHERE stock_code = ? ORDER BY timestamp DESC LIMIT 1",
                (code,)
            )
            if rows:
                metrics["capital_score"] = round(float(rows[0][0] or 50), 1)
                metrics["net_inflow_ratio"] = round(float(rows[0][1] or 0), 4)
        except Exception:
            pass

        # 获取当日实时行情（如果可用）
        try:
            quote_service = getattr(self.container, 'quote_service', None)
            if quote_service:
                snapshot = quote_service.get_market_snapshot([code])
                if snapshot and len(snapshot) > 0:
                    snap = snapshot[0]
                    cur_price = getattr(snap, 'last_price', 0) or 0
                    prev_close = getattr(snap, 'prev_close_price', 0) or 0
                    if cur_price > 0 and prev_close > 0:
                        today_change = (cur_price - prev_close) / prev_close * 100
                        metrics["today_change"] = round(today_change, 2)
                        metrics["realtime_price"] = round(cur_price, 3)
                        # 用实时价覆盖K线收盘价
                        metrics["last_price"] = round(cur_price, 3)
        except Exception:
            pass

        return metrics
