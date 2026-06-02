#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
盘后优选引擎 — 全规则综合评分

收盘后对市场扫描池股票执行多规则评分，输出明日观察列表。
数据全部从DB/缓存读取，零API调用。
"""

import logging
from datetime import datetime, date
from typing import Dict, List, Any, Optional

from .overnight_models import OvernightCandidate, WEIGHTS
from .momentum_scorer import MomentumScorer

logger = logging.getLogger("overnight_screener")


class OvernightScreener:
    """盘后优选评分引擎"""

    def __init__(self, db_manager, container=None):
        self.db = db_manager
        self.container = container

    async def run_screen_from_snapshots(self, snapshots: dict) -> list:
        """
        从 StockSnapshot 字典执行评分（推荐新接口）

        Args:
            snapshots: {code: StockSnapshot} 来自 SnapshotBuilder

        Returns:
            按总分降序的 OvernightCandidate 列表
        """
        stock_list = []
        for code, snap in snapshots.items():
            stock_list.append({
                'code': snap.code,
                'name': snap.name,
                'market': snap.market,
                'last_price': snap.last_price,
                'change_rate': snap.change_rate,
                'turnover_rate': snap.turnover_rate,
                'volume_ratio': snap.volume_ratio,
                'amplitude': snap.amplitude,
                'turnover': snap.turnover,
                'high_price': snap.high_price,
                'low_price': snap.low_price,
                'plates': list(snap.plates),
                'leader_rank': 1 if snap.plate_rank == 1 else 0,
            })
        return await self.run_screen(stock_list)

    async def run_screen(self, stock_list: List[Dict[str, Any]]) -> List[OvernightCandidate]:
        """
        主入口：双模式选股

        每只股票同时评估 TREND、MOMENTUM 两种模式，
        分别排除、评分、排名，最终合并输出。

        Returns:
            合并的候选列表（TREND Top10 + MOMENTUM Top10），按总分降序
        """
        if not stock_list:
            return []

        logger.info(f"[盘后优选] 开始三模评分，共 {len(stock_list)} 只股票")

        trend_candidates = []
        momentum_candidates = []

        # --- MOMENTUM 预计算: 板块缓存 ---
        momentum_scorer = MomentumScorer(self.db)
        all_klines_cache = {}
        stock_plates_map = {}
        for stock in stock_list:
            code = stock.get('code', '')
            if not code:
                continue
            klines = self._get_klines(code, 25)
            all_klines_cache[code] = klines
            # 获取板块归属
            plates = self._get_stock_plates(code)
            stock_plates_map[code] = plates

        momentum_scorer.precompute_plate_cache(
            [{'code': s.get('code', ''), 'plates': stock_plates_map.get(s.get('code', ''), [])}
             for s in stock_list],
            all_klines_cache
        )

        for stock in stock_list:
            code = stock.get('code', '')
            name = stock.get('name', '')
            if not code:
                continue

            # 通用排除（4条，两个模式都不要的）
            excluded_common, reason_common = self._check_exclusions(stock, code, mode='REVERSAL')
            if excluded_common:
                continue

            # 收集指标和K线
            klines = all_klines_cache.get(code) or self._get_klines(code, 25)
            indicators = self._build_scorer_indicators(stock, klines, code)

            # --- TREND 候选 ---
            excluded_trend, reason_trend = self._check_exclusions(stock, code, mode='TREND')
            if not excluded_trend and indicators:
                c_t = OvernightCandidate(stock_code=code, stock_name=name)
                c_t.key_metrics = self._collect_metrics(stock, code)
                c_t.category = "趋势追涨"

                from ..strategy.stock_scorer import StockScorer, PASSING_SCORE
                scorer = StockScorer()
                trend_score, trend_details = scorer._score_trend(indicators)
                c_t.scores['scorer_trend'] = trend_score
                c_t.total_score = trend_score

                bonus = self._overnight_bonus(stock, code)
                c_t.total_score += bonus['total']
                c_t.reasons = bonus['reasons']

                c_t.penalty_factor, c_t.penalty_reasons = self._check_penalties(stock, code)
                c_t.total_score *= c_t.penalty_factor

                c_t.verdict = self._verdict(c_t.total_score)
                if trend_score >= PASSING_SCORE:
                    trend_candidates.append(c_t)

            # REVERSAL 策略已归档 → strategy_archive/reversal_v1.py

            # --- MOMENTUM 候选 ---
            if klines and len(klines) >= 5:
                m_result = momentum_scorer.score_stock(
                    code, klines, stock_plates_map.get(code, [])
                )
                if m_result['total'] >= 45:  # MOMENTUM 及格线较低（蓄势信号本身有价值）
                    c_m = OvernightCandidate(stock_code=code, stock_name=name)
                    c_m.key_metrics = self._collect_metrics(stock, code)
                    c_m.category = "蓄势突破"
                    c_m.total_score = m_result['total']
                    c_m.verdict = m_result['verdict']
                    c_m.reasons = m_result['signals']
                    c_m.scores = {
                        'momentum_accumulation': m_result['dimensions']['accumulation'],
                        'momentum_catalyst': m_result['dimensions']['catalyst'],
                        'momentum_phase': m_result['dimensions']['phase'],
                        'momentum_risk': m_result['dimensions']['risk'],
                    }
                    # 附加交易建议到 key_metrics
                    c_m.key_metrics.update(m_result.get('trade_suggestion', {}))
                    momentum_candidates.append(c_m)

        # 排序 + 排名
        trend_candidates.sort(key=lambda x: x.total_score, reverse=True)
        momentum_candidates.sort(key=lambda x: x.total_score, reverse=True)

        for i, c in enumerate(trend_candidates[:10]):
            c.rank = i + 1
        for i, c in enumerate(momentum_candidates[:10]):
            c.rank = i + 1

        # 合并输出（按stock_code去重，同一股票保留分数更高的模式）
        seen_codes = {}
        for c in trend_candidates[:10]:
            seen_codes[c.stock_code] = c
        for c in momentum_candidates[:10]:
            if c.stock_code not in seen_codes or c.total_score > seen_codes[c.stock_code].total_score:
                seen_codes[c.stock_code] = c
        result = sorted(seen_codes.values(), key=lambda x: x.total_score, reverse=True)

        logger.info(
            f"[盘后优选] 完成 | TREND: {len(trend_candidates)}只(Top1={trend_candidates[0].total_score:.0f}分)"
            if trend_candidates else "[盘后优选] TREND: 0只"
        )
        logger.info(
            f"[盘后优选] 完成 | MOMENTUM: {len(momentum_candidates)}只(Top1={momentum_candidates[0].total_score:.0f}分)"
            if momentum_candidates else "[盘后优选] MOMENTUM: 0只"
        )
        return result

    # ==================== Tier 1 核心评分 (55%) ====================

    def _score_tier1(self, c: OvernightCandidate, stock: dict, code: str):
        """P1: R11资金持续 + P2: 趋势反转 + P3: R1净流入建仓"""

        # P1: R11 资金持续流入 (20%)
        cont_days = self._get_capital_continuity_days(code)
        if cont_days >= 5:
            score = 100
        elif cont_days >= 3:
            score = 80
        elif cont_days >= 2:
            score = 50
        elif cont_days >= 1:
            score = 20
        else:
            score = 0
        c.scores['capital_continuity'] = score
        if cont_days >= 3:
            c.reasons.append(f"连续{cont_days}日资金净流入（R11）")

        # P2: 趋势反转买入信号 (20%)
        rev_score, rev_details = self._check_trend_reversal(code)
        c.scores['trend_reversal'] = rev_score
        if rev_score >= 60:
            c.reasons.append(f"趋势反转买入信号（{rev_details}）")

        # P3: R1 资金净流入建仓 (15%)
        r1_score = self._score_r1_inflow(stock, code)
        c.scores['net_inflow_position'] = r1_score
        if r1_score >= 60:
            c.reasons.append("主力资金净流入+低位建仓（R1）")

    # ==================== Tier 2 强化确认 (30%) ====================

    def _score_tier2(self, c: OvernightCandidate, stock: dict, code: str):
        """P4-P7: 资金评分v2 + 大单 + K线画像 + QuickScan"""

        # P4: 资金评分v2 (8%)
        cap_score = self._get_capital_score(code)
        c.scores['capital_score_v2'] = cap_score
        c.key_metrics['capital_score'] = cap_score
        if cap_score >= 70:
            c.reasons.append(f"资金评分偏多（{cap_score:.0f}分）")

        # P5: 大单买入强度 (7%)
        big_score = self._score_big_order(code)
        c.scores['big_order_strength'] = big_score
        if big_score >= 70:
            c.reasons.append("大单买入强势")

        # P6: K线画像 (7%)
        kline_score = self._score_kline_profile(code, stock)
        c.scores['kline_profile'] = kline_score

        # P7: QuickScan判定 (8%)
        qs_score = self._score_quickscan(stock, code)
        c.scores['quickscan_verdict'] = qs_score

    # ==================== Tier 3 辅助 (15%) ====================

    def _score_tier3(self, c: OvernightCandidate, stock: dict, code: str):
        """P8-P10: 龙头 + 量价 + 机会评分"""

        # P8: 龙头板块加分 (5%)
        leader_score = self._score_leader(stock)
        c.scores['leader_bonus'] = leader_score
        if leader_score >= 70:
            c.reasons.append("强势板块龙头股")

        # P9: 量价配合度 (5%)
        vp_score = self._score_volume_price_fit(stock)
        c.scores['volume_price_fit'] = vp_score

        # P10: 机会评分 (5%)
        opp_score = self._score_opportunity(stock)
        c.scores['opportunity_score'] = opp_score

    # ==================== 排除条件 ====================

    def _check_exclusions(self, stock: dict, code: str, mode: str = None) -> tuple:
        """排除条件，返回 (excluded, reason)

        mode=None: 通用排除(4条)
        mode='TREND': 通用+TREND专用(7条)
        mode='REVERSAL': 仅通用(4条), 深跌/回撤/卖出信号不排除
        """
        change = stock.get('change_rate', 0) or 0
        turnover_rate = stock.get('turnover_rate', 0) or 0
        volume_ratio = stock.get('volume_ratio', 0) or 0
        high = stock.get('high_price', 0) or 0
        last = stock.get('last_price', 0) or 0

        # === 通用排除 (TREND + REVERSAL 都适用) ===

        # 流动性不足（仅当换手率有效值时才排除，历史K线模式无换手率时跳过）
        if turnover_rate > 0 and turnover_rate < 0.3:
            return True, f"流动性不足：换手率{turnover_rate:.2f}%<0.3%"

        # 缩量暴涨（仅当换手率和量比都有有效值时才判断）
        if change > 10 and turnover_rate > 0 and turnover_rate < 1 and volume_ratio > 0 and volume_ratio < 0.8:
            return True, f"缩量暴涨：涨{change:.1f}%但换手{turnover_rate:.1f}%量比{volume_ratio:.1f}"

        # 量价背离(收盘价≈日高但缩量)
        if high > 0 and last > 0 and volume_ratio > 0:
            near_high = (high - last) / high < 0.005 if high > 0 else False
            if near_high and volume_ratio < 0.7 and change > 1:
                return True, f"量价背离：收盘近日高但量比{volume_ratio:.1f}"

        # 资金大幅流出+高位
        cap_data = self._get_cached_capital(code)
        if cap_data:
            ratio = cap_data.get('net_inflow_ratio', 0)
            if ratio < -0.05 and change > 5:
                return True, f"资金大幅流出：净流出{ratio:.1%}+涨{change:.1f}%"

        # === 仅TREND排除 (REVERSAL不排除, 因为深跌/回撤正是反转机会) ===
        if mode != 'REVERSAL':
            # 趋势反转卖出信号
            sell_score = self._check_trend_sell(code)
            if sell_score >= 80:
                return True, "趋势反转卖出信号明确"

            # 20日深度下跌
            total_20d = self._get_20d_change(code)
            if total_20d is not None and total_20d < -20:
                return True, f"20日累跌{total_20d:.1f}%，深度下跌趋势"

            # 最大回撤过深
            max_dd = self._get_max_drawdown(code)
            if max_dd is not None and max_dd > 25:
                return True, f"20日最大回撤{max_dd:.1f}%"

        return False, ""

    def _check_penalties(self, stock: dict, code: str) -> tuple:
        """降权检查，返回 (factor, reasons)"""
        factor = 1.0
        reasons = []
        change = stock.get('change_rate', 0) or 0

        # ❌9 R4 资金转正但力度不足
        cont_days = self._get_capital_continuity_days(code)
        cap_data = self._get_cached_capital(code)
        if cap_data and cont_days == 1:
            ratio = cap_data.get('net_inflow_ratio', 0)
            if 0 < ratio < 0.03:
                factor *= 0.5
                reasons.append(f"R4：资金刚转正但流入不足({ratio:.1%})")

        # ❌10 R3 流入不足逢高
        if cap_data:
            ratio = cap_data.get('net_inflow_ratio', 0)
            if 0 < ratio < 0.03 and change > 2:
                factor *= 0.7
                reasons.append(f"R3：流入不足({ratio:.1%})但涨{change:.1f}%")

        return factor, reasons

    # ==================== 强势股动量评估 ====================

    def _evaluate_momentum(self, c: OvernightCandidate, stock: dict, code: str):
        """涨幅≥8%的股票，动量评估加分"""
        bonus = 0
        turnover_rate = stock.get('turnover_rate', 0) or 0
        cont_days = self._get_capital_continuity_days(code)
        big_ratio = self._get_big_order_ratio(code)
        is_leader = stock.get('leader_rank', 0) == 1
        cap_score = c.scores.get('capital_score_v2', 50)

        met_count = 0
        if turnover_rate >= 3:
            bonus += 15; met_count += 1
        if cont_days >= 2:
            bonus += 15; met_count += 1
        if big_ratio and big_ratio > 1.5:
            bonus += 10; met_count += 1
        if is_leader:
            bonus += 10; met_count += 1
        if cap_score >= 60:
            bonus += 10; met_count += 1

        if met_count >= 2:
            c.category = "强势延续"
            c.total_score = min(100, c.total_score + bonus * 0.3)
            c.reasons.append(f"强势延续：满足{met_count}项动量条件")

    # ==================== 分类确定 ====================

    def _determine_category(self, c: OvernightCandidate) -> str:
        if c.category == "强势延续":
            return c.category
        rev = c.scores.get('trend_reversal', 0)
        cont = c.scores.get('capital_continuity', 0)
        r1 = c.scores.get('net_inflow_position', 0)
        if rev >= 60:
            return "趋势反转"
        if cont >= 80 or r1 >= 70:
            return "资金吸筹"
        return "综合优选"

    # ==================== StockScorer 集成 ====================

    def _build_scorer_indicators(self, stock: dict, klines: list, code: str) -> dict:
        """从盘后数据构建 StockScorer 所需的指标字典"""
        indicators = {}

        # 振幅
        high = stock.get('high_price', 0) or 0
        low = stock.get('low_price', 0) or 0
        last = stock.get('last_price', 0) or 0
        if high > 0 and low > 0 and last > 0:
            indicators['day_amplitude'] = stock.get('amplitude', 0) or ((high - low) / last * 100)

        # 量比: 优先用实时数据，缺失时从K线成交量计算
        indicators['vol_ratio'] = stock.get('volume_ratio', None) or None
        if indicators['vol_ratio'] is None and klines and len(klines) >= 6:
            # 用最后一根K线成交量 / 前5日均量
            today_vol = klines[-1].get('volume', 0) or 0
            prev_vols = [k['volume'] for k in klines[-6:-1] if k.get('volume', 0) > 0]
            if today_vol > 0 and prev_vols:
                avg_vol = sum(prev_vols) / len(prev_vols)
                if avg_vol > 0:
                    calc_vr = round(today_vol / avg_vol, 2)
                    # 仅当量比>=1.5时才填入(加分)，低量比留None走中性分
                    # 大盘股量比天然偏低(0.6-1.3)，填入反而扣分
                    if calc_vr >= 1.5:
                        indicators['vol_ratio'] = calc_vr

        # ticker_power: 优先用逐笔数据，回退到资金流
        ticker_power = None
        ticker_svc = getattr(self.container, 'ticker_service', None) if self.container else None
        if ticker_svc:
            try:
                import asyncio
                ticker_data = asyncio.get_event_loop().run_until_complete(
                    ticker_svc.get_ticker_data(code)
                )
                if ticker_data and hasattr(ticker_data, 'buy_turnover') and getattr(ticker_data, 'sell_turnover', 0) > 0:
                    bsr = ticker_data.buy_turnover / ticker_data.sell_turnover
                    ticker_power = bsr - 1.0
            except Exception:
                pass
        if ticker_power is None:
            cap = self._get_cached_capital(code)
            if cap:
                ticker_power = cap.get('net_inflow_ratio', None)
        indicators['ticker_power'] = ticker_power

        # 今日涨跌幅
        indicators['today_change'] = stock.get('change_rate', None)

        # 从K线计算
        if klines and len(klines) >= 2:
            closes = [k['close_price'] for k in klines if k.get('close_price', 0) > 0]

            if len(closes) >= 2:
                indicators['prev_day_change'] = (closes[-1] - closes[-2]) / closes[-2] * 100

            if len(closes) >= 6:
                indicators['change_5d'] = (closes[-1] - closes[-6]) / closes[-6] * 100

            # K线20日位置
            if len(klines) >= 10:
                recent = klines[-20:] if len(klines) >= 20 else klines
                highs = [k['high_price'] for k in recent if k.get('high_price')]
                lows = [k['low_price'] for k in recent if k.get('low_price')]
                if highs and lows:
                    max_h, min_l = max(highs), min(lows)
                    if max_h > min_l and last > 0:
                        indicators['kline_pos_20d'] = (last - min_l) / (max_h - min_l)

            # 距低点反弹
            if len(klines) >= 3:
                lookback = klines[-10:] if len(klines) >= 10 else klines
                recent_lows = [k['low_price'] for k in lookback if k.get('low_price', 0) > 0]
                if recent_lows and last > 0:
                    period_low = min(recent_lows)
                    if period_low > 0:
                        indicators['rise_from_low'] = (last - period_low) / period_low * 100

        return indicators

    def _overnight_bonus(self, stock: dict, code: str) -> dict:
        """盘后独有的加分项（StockScorer 没有的维度）"""
        bonus = 0
        reasons = []

        # 资金连续流入天数 (最多+15分)
        cont_days = self._get_capital_continuity_days(code)
        if cont_days >= 5:
            bonus += 15
            reasons.append(f"资金连续流入{cont_days}天")
        elif cont_days >= 3:
            bonus += 10
            reasons.append(f"资金连续流入{cont_days}天")
        elif cont_days >= 2:
            bonus += 5

        # 大单买入强势 (最多+10分)
        big_ratio = self._get_big_order_ratio(code)
        if big_ratio and big_ratio >= 2.0:
            bonus += 10
            reasons.append(f"大单买卖比{big_ratio:.1f}")
        elif big_ratio and big_ratio >= 1.5:
            bonus += 5

        # 龙头板块 (最多+5分)
        if stock.get('leader_rank', 0) == 1:
            bonus += 5
            reasons.append("板块龙头")

        # 资金评分强势加分 (最多+15分)
        # 修复大盘股因量比/逐笔力量丢分导致的系统性低估
        cap_data = self._get_cached_capital(code)
        if cap_data:
            cap_score = cap_data.get('capital_score', 50)
            main_inflow = cap_data.get('main_net_inflow', 0)
            if cap_score >= 85 and main_inflow > 0:
                bonus += 15
                reasons.append(f"资金强势流入(评分{cap_score:.0f})")
            elif cap_score >= 70 and main_inflow > 0:
                bonus += 10
                reasons.append(f"资金偏多(评分{cap_score:.0f})")

        return {'total': bonus, 'reasons': reasons}

    @staticmethod
    def _verdict(score: float) -> str:
        if score >= 85:
            return "强烈推荐"
        if score >= 70:
            return "推荐"
        if score >= 60:
            return "可关注"
        return "观望"

    # ==================== 底层数据读取 ====================

    def _get_capital_continuity_days(self, code: str) -> int:
        """从capital_flow_daily查连续净流入天数"""
        try:
            rows = self.db.execute_query(
                "SELECT net_inflow FROM capital_flow_daily "
                "WHERE stock_code = ? ORDER BY date DESC LIMIT 10",
                (code,)
            )
            if not rows:
                return 0
            days = 0
            for r in rows:
                if r[0] and r[0] > 0:
                    days += 1
                else:
                    break
            return days
        except Exception:
            return 0

    def _get_cached_capital(self, code: str) -> Optional[dict]:
        """读取capital_flow_cache最新数据"""
        try:
            rows = self.db.execute_query(
                "SELECT net_inflow_ratio, big_order_buy_ratio, capital_score, main_net_inflow "
                "FROM capital_flow_cache WHERE stock_code = ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (code,)
            )
            if rows:
                return {
                    'net_inflow_ratio': rows[0][0] or 0,
                    'big_order_buy_ratio': rows[0][1] or 0,
                    'capital_score': rows[0][2] or 50,
                    'main_net_inflow': rows[0][3] or 0,
                }
        except Exception:
            pass
        return None

    def _get_capital_score(self, code: str) -> float:
        """获取资金评分v2"""
        cap = self._get_cached_capital(code)
        return cap['capital_score'] if cap else 50

    def _get_big_order_ratio(self, code: str) -> Optional[float]:
        """从big_order_tracking获取买卖比"""
        try:
            rows = self.db.execute_query(
                "SELECT buy_sell_ratio FROM big_order_tracking "
                "WHERE stock_code = ? ORDER BY timestamp DESC LIMIT 1",
                (code,)
            )
            return rows[0][0] if rows else None
        except Exception:
            return None

    def _score_big_order(self, code: str) -> float:
        ratio = self._get_big_order_ratio(code)
        if ratio is None:
            return 50
        if ratio >= 2.0:
            return 100
        if ratio >= 1.5:
            return 80
        if ratio >= 1.0:
            return 50
        return max(0, ratio * 50)

    def _check_trend_reversal(self, code: str) -> tuple:
        """检查趋势反转买入信号，返回 (score, detail_text)"""
        try:
            klines = self._get_klines(code, 30)
            if len(klines) < 10:
                return 0, ""

            closes = [k['close_price'] for k in klines]
            volumes = [k['volume'] for k in klines]
            opens = [k['open_price'] for k in klines]

            conditions_met = 0
            details = []

            # 条件1: 近期有下跌(距高点跌幅≥10%, 回测PF=1.91)
            peak = max(closes[-20:]) if len(closes) >= 20 else max(closes)
            drop_pct = (peak - closes[-1]) / peak * 100 if peak > 0 else 0
            if drop_pct >= 10:
                conditions_met += 1
                details.append(f"距高点跌{drop_pct:.1f}%")

            # 条件2: 最后一根K线是阳线
            if closes[-1] > opens[-1]:
                conditions_met += 1
                details.append("阳线反转")

            # 条件3: 放量(最后一根量 > 5日均量)
            avg_vol_5 = sum(volumes[-6:-1]) / 5 if len(volumes) >= 6 else sum(volumes) / len(volumes)
            if volumes[-1] > avg_vol_5 * 1.2:
                conditions_met += 1
                details.append("放量确认")

            # 条件4: 反弹(最后收盘 > 前一收盘)
            if len(closes) >= 2 and closes[-1] > closes[-2]:
                conditions_met += 1
                details.append("价格反弹")

            score = min(100, conditions_met * 25)
            return score, "、".join(details)
        except Exception as e:
            logger.debug(f"趋势反转检查失败 {code}: {e}")
            return 0, ""

    def _check_trend_sell(self, code: str) -> float:
        """检查趋势反转卖出信号强度"""
        try:
            klines = self._get_klines(code, 20)
            if len(klines) < 5:
                return 0
            closes = [k['close_price'] for k in klines]
            opens = [k['open_price'] for k in klines]
            conditions = 0
            low = min(closes[-10:]) if len(closes) >= 10 else min(closes)
            rise = (closes[-1] - low) / low * 100 if low > 0 else 0
            if rise >= 10:
                conditions += 1
            if closes[-1] < opens[-1]:
                conditions += 1
            if len(closes) >= 2 and closes[-1] < closes[-2]:
                conditions += 1
            return conditions * 27
        except Exception:
            return 0

    def _score_r1_inflow(self, stock: dict, code: str) -> float:
        """R1: 资金净流入 + 低位建仓"""
        cap = self._get_cached_capital(code)
        if not cap:
            return 30
        ratio = cap['net_inflow_ratio']
        if ratio <= 0:
            return 0
        # 净流入强度评分
        inflow_score = min(100, ratio / 0.05 * 50)
        # K线位置加成(低位加分)
        position = self._get_kline_position(code)
        if position is not None and position <= 0.3:
            inflow_score = min(100, inflow_score + 30)
        elif position is not None and position >= 0.7:
            inflow_score = max(0, inflow_score - 20)
        return inflow_score

    def _score_kline_profile(self, code: str, stock: dict) -> float:
        """K线画像评分"""
        score = 50
        position = self._get_kline_position(code)
        if position is not None:
            if position <= 0.3:
                score += 30  # 低位
            elif position >= 0.8:
                score -= 20  # 高位
        # 支撑位附近加分
        last = stock.get('last_price', 0)
        support = self._get_support_level(code)
        if last > 0 and support > 0:
            dist_pct = (last - support) / last * 100
            if dist_pct <= 3:
                score += 20
        return max(0, min(100, score))

    def _score_quickscan(self, stock: dict, code: str) -> float:
        """QuickScan判定复用（从缓存读取或简化计算）"""
        # 简化版：基于K线位置+资金评分+量比综合
        position = self._get_kline_position(code)
        cap_score = self._get_capital_score(code)
        volume_ratio = stock.get('volume_ratio', 1) or 1

        score = 50
        if position is not None and position <= 0.3:
            score += 20
        if cap_score >= 60:
            score += 15
        elif cap_score <= 40:
            score -= 15
        if 1.5 <= volume_ratio <= 3:
            score += 10
        # 风险收益比估算
        change = stock.get('change_rate', 0) or 0
        if 1 <= change <= 5:
            score += 10
        elif change > 8:
            score -= 5
        elif change < -3:
            score -= 10
        return max(0, min(100, score))

    def _score_leader(self, stock: dict) -> float:
        """龙头板块加分"""
        rank = stock.get('leader_rank', 0)
        if rank == 1:
            return 100
        if rank == 2:
            return 70
        if rank == 3:
            return 50
        # 有板块但非龙头
        plates = stock.get('plates', [])
        if plates:
            return 30
        return 0

    def _score_volume_price_fit(self, stock: dict) -> float:
        """量价配合度"""
        vr = stock.get('volume_ratio', 0) or 0
        tr = stock.get('turnover_rate', 0) or 0
        amp = stock.get('amplitude', 0) or 0

        # 量比: 1.5-3最佳
        vr_s = 100 if 1.5 <= vr <= 3 else (60 if 1 <= vr <= 4 else 20)
        # 换手率: 2-8%最佳
        tr_s = 100 if 2 <= tr <= 8 else (60 if 1 <= tr <= 12 else 20)
        # 振幅: 3-10%最佳
        amp_s = 100 if 3 <= amp <= 10 else (60 if 1 <= amp <= 15 else 20)

        return vr_s * 0.4 + tr_s * 0.35 + amp_s * 0.25

    def _score_opportunity(self, stock: dict) -> float:
        """机会评分（复用Advisor逻辑）"""
        tr = stock.get('turnover_rate', 0) or 0
        change = stock.get('change_rate', 0) or 0

        # 活跃度
        if tr >= 3:
            activity = 100
        elif tr >= 1:
            activity = 50 + (tr - 1) / 2 * 50
        else:
            activity = max(0, tr * 50)

        # 涨跌幅（适度上涨最佳）
        if 1 <= change <= 5:
            change_s = 100
        elif 0 <= change < 1:
            change_s = 60
        elif change > 5:
            change_s = 50
        else:
            change_s = 30

        return activity * 0.6 + change_s * 0.4

    # ==================== K线数据读取 ====================

    def _get_klines(self, code: str, limit: int = 25) -> List[dict]:
        try:
            rows = self.db.execute_query(
                "SELECT time_key, open_price, high_price, low_price, close_price, volume "
                "FROM kline_data WHERE stock_code = ? "
                "ORDER BY time_key DESC LIMIT ?",
                (code, limit)
            )
            if not rows:
                return []
            cols = ['time_key', 'open_price', 'high_price', 'low_price', 'close_price', 'volume']
            klines = [dict(zip(cols, r)) for r in rows]
            klines.reverse()
            return klines
        except Exception:
            return []

    def _get_kline_position(self, code: str) -> Optional[float]:
        """K线位置 0~1"""
        klines = self._get_klines(code, 20)
        if len(klines) < 5:
            return None
        closes = [k['close_price'] for k in klines if k.get('close_price')]
        highs = [k['high_price'] for k in klines if k.get('high_price')]
        lows = [k['low_price'] for k in klines if k.get('low_price')]
        if not highs or not lows or not closes:
            return None
        h, l = max(highs), min(lows)
        if h <= l:
            return 0.5
        return (closes[-1] - l) / (h - l)

    def _get_support_level(self, code: str) -> float:
        klines = self._get_klines(code, 10)
        if len(klines) < 5:
            return 0
        lows = sorted([k['low_price'] for k in klines[-5:] if k.get('low_price')])
        if len(lows) >= 3:
            import statistics
            return statistics.median(lows[:3])
        return min(lows) if lows else 0

    def _get_20d_change(self, code: str) -> Optional[float]:
        klines = self._get_klines(code, 20)
        if len(klines) < 10:
            return None
        closes = [k['close_price'] for k in klines if k.get('close_price')]
        if len(closes) < 2 or closes[0] <= 0:
            return None
        return (closes[-1] - closes[0]) / closes[0] * 100

    def _get_max_drawdown(self, code: str) -> Optional[float]:
        klines = self._get_klines(code, 20)
        if len(klines) < 5:
            return None
        closes = [k['close_price'] for k in klines if k.get('close_price')]
        if not closes:
            return None
        peak = closes[0]
        max_dd = 0
        for c in closes:
            if c > peak:
                peak = c
            dd = (peak - c) / peak * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        return max_dd

    def _collect_metrics(self, stock: dict, code: str = '') -> dict:
        metrics = {
            'last_price': stock.get('last_price', 0),
            'change_rate': stock.get('change_rate', 0),
            'turnover_rate': stock.get('turnover_rate', 0),
            'volume_ratio': stock.get('volume_ratio', 0),
            'amplitude': stock.get('amplitude', 0),
            'turnover': stock.get('turnover', 0),
        }
        # 资金流模式标签
        if code:
            pattern, desc = self._get_flow_pattern(code)
            metrics['flow_pattern'] = pattern
            metrics['flow_pattern_desc'] = desc
        return metrics

    def _get_flow_pattern(self, code: str) -> tuple:
        """分析资金流模式（复用 PositionAdvisor 逻辑）"""
        try:
            rows = self.db.execute_query(
                "SELECT net_inflow FROM capital_flow_daily "
                "WHERE stock_code = ? ORDER BY date DESC LIMIT 10",
                (code,)
            )
            if not rows:
                return 'unknown', ''

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
                return 'sustained_in', f'持续流入{in_days}天'
            elif out_days >= 3:
                return 'sustained_out', f'持续流出{out_days}天'
            else:
                # 判断交替
                if len(rows) >= 4:
                    signs = [1 if (r[0] or 0) > 0 else -1 for r in rows[:7]]
                    changes = sum(1 for i in range(1, len(signs)) if signs[i] != signs[i-1])
                    if changes >= 3:
                        return 'alternating', '交替进出'
                return 'alternating', '方向不明'
        except Exception:
            return 'unknown', ''

    def _get_stock_plates(self, code: str) -> List[str]:
        """获取股票所属板块名称列表"""
        try:
            rows = self.db.execute_query(
                "SELECT p.plate_name FROM stock_plates sp "
                "JOIN stocks s ON sp.stock_id = s.id "
                "JOIN plates p ON sp.plate_id = p.id "
                "WHERE s.code = ?",
                (code,)
            )
            return [r[0] for r in rows] if rows else []
        except Exception:
            return []
