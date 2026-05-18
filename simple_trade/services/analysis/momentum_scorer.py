#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
蓄势突破策略评分器 (MOMENTUM)

基于5/18市场4只爆发股实证分析设计：
- 个股蓄势信号(40%): 量能异变、支撑测试、缩量蓄势、长下影线、大阳线历史
- 题材催化(25%): 板块联动、板块内已爆发、新闻热度
- 阶段判断(20%): 第几波、距首次放量天数、市值区间
- 风控适配(15%): 振幅健康度、上影线风险、量价配合
"""

import logging
from typing import Dict, List, Any, Optional
from collections import defaultdict

logger = logging.getLogger("momentum_scorer")


class MomentumScorer:
    """蓄势突破策略评分器"""

    def __init__(self, db_manager):
        self.db = db_manager
        # 板块联动缓存：{plate_name: [codes with signals]}
        self._plate_signal_cache: Dict[str, List[str]] = {}
        # 板块内已爆发缓存：{plate_name: count}
        self._plate_explosion_cache: Dict[str, int] = {}

    def score_stock(self, code: str, klines: List[dict],
                    stock_plates: List[str] = None) -> Dict[str, Any]:
        """
        对单只股票进行 MOMENTUM 评分

        Args:
            code: 股票代码
            klines: K线数据列表（按时间正序, 至少10根）
            stock_plates: 该股票所属板块名称列表

        Returns:
            {
                'total': float,         # 总分 0-100
                'dimensions': {         # 各维度分数
                    'accumulation': float,  # 个股蓄势 0-40
                    'catalyst': float,      # 题材催化 0-25
                    'phase': float,         # 阶段判断 0-20
                    'risk': float,          # 风控适配 0-15
                },
                'signals': [...],       # 信号列表
                'trade_suggestion': {}, # 交易建议
                'verdict': str,         # 评级
            }
        """
        if not klines or len(klines) < 5:
            return self._empty_result()

        signals = []

        # 第一层：个股蓄势信号 (40分)
        acc_score, acc_signals = self._score_accumulation(klines)
        signals.extend(acc_signals)

        # 第二层：题材催化 (25分)
        cat_score, cat_signals = self._score_catalyst(code, stock_plates or [])
        signals.extend(cat_signals)

        # 第三层：阶段判断 (20分)
        phase_score, phase_signals = self._score_phase(klines)
        signals.extend(phase_signals)

        # 第四层：风控适配 (15分)
        risk_score, risk_signals = self._score_risk(klines)
        signals.extend(risk_signals)

        total = acc_score + cat_score + phase_score + risk_score

        # 交易建议
        suggestion = self._build_trade_suggestion(klines, total)

        return {
            'total': round(total, 1),
            'dimensions': {
                'accumulation': round(acc_score, 1),
                'catalyst': round(cat_score, 1),
                'phase': round(phase_score, 1),
                'risk': round(risk_score, 1),
            },
            'signals': signals,
            'trade_suggestion': suggestion,
            'verdict': self._verdict(total),
        }

    # ==================== 第一层: 个股蓄势 (40分) ====================

    def _score_accumulation(self, klines: List[dict]) -> tuple:
        """个股蓄势信号评分"""
        score = 0.0
        signals = []

        # 基准量能（前3根K线平均）
        base_vols = [k['volume'] for k in klines[:3] if k.get('volume', 0) > 0]
        base_vol = sum(base_vols) / len(base_vols) if base_vols else 1

        # 1. 量能异变 (10分): 近10日出现≥3x放量的天数
        vol_spike_days = 0
        for k in klines[-10:]:
            v = k.get('volume', 0) or 0
            if base_vol > 0 and v >= base_vol * 3:
                vol_spike_days += 1

        if vol_spike_days >= 4:
            score += 10; signals.append(f"量能异变: {vol_spike_days}天放量(≥3x)")
        elif vol_spike_days >= 3:
            score += 8; signals.append(f"量能异变: {vol_spike_days}天放量(≥3x)")
        elif vol_spike_days >= 2:
            score += 5; signals.append(f"放量{vol_spike_days}天")
        elif vol_spike_days >= 1:
            score += 2

        # 2. 支撑位测试 (10分): 同一价位区间被测试次数
        support_zones = defaultdict(int)
        for k in klines[-10:]:
            low = k.get('low_price', 0)
            if low > 0:
                # 按2%区间聚类
                zone_key = round(low * 50) / 50  # 四舍五入到0.02精度
                support_zones[zone_key] += 1

        max_tests = max(support_zones.values()) if support_zones else 0
        if max_tests >= 4:
            zone_price = max(support_zones, key=support_zones.get)
            score += 10; signals.append(f"支撑{zone_price:.1f}元测试{max_tests}次")
        elif max_tests >= 3:
            zone_price = max(support_zones, key=support_zones.get)
            score += 7; signals.append(f"支撑{zone_price:.1f}元测试{max_tests}次")
        elif max_tests >= 2:
            score += 3

        # 3. 缩量蓄势 (10分): 放量后出现连续缩量
        contraction_score = self._detect_contraction(klines, base_vol)
        score += contraction_score
        if contraction_score >= 7:
            signals.append("缩量蓄势: 放量后连续缩量")

        # 4. 长下影线 (5分): 近10日探底回升天数
        shadow_days = 0
        for k in klines[-10:]:
            o, c, l = k.get('open_price', 0), k.get('close_price', 0), k.get('low_price', 0)
            body_low = min(o, c) if o > 0 and c > 0 else 0
            body_size = abs(o - c) if o > 0 and c > 0 else 1
            if body_low > 0 and l > 0 and body_size > 0:
                lower_shadow = body_low - l
                if lower_shadow >= body_size * 1.5:  # 下影线≥1.5倍实体
                    shadow_days += 1

        if shadow_days >= 3:
            score += 5; signals.append(f"长下影线{shadow_days}天(探底回升)")
        elif shadow_days >= 2:
            score += 3; signals.append(f"长下影线{shadow_days}天")
        elif shadow_days >= 1:
            score += 1

        # 5. 大阳线历史 (5分): 近10日出现≥5%涨幅大阳线
        big_yang_days = 0
        for k in klines[-10:]:
            o, c = k.get('open_price', 0), k.get('close_price', 0)
            if o > 0 and c > 0 and (c - o) / o * 100 >= 5:
                big_yang_days += 1

        if big_yang_days >= 2:
            score += 5; signals.append(f"近期{big_yang_days}根大阳线(≥5%)")
        elif big_yang_days >= 1:
            score += 3; signals.append("近期有大阳线启动迹象")

        return score, signals

    def _detect_contraction(self, klines: List[dict], base_vol: float) -> float:
        """检测放量后缩量蓄势"""
        if len(klines) < 5:
            return 0

        # 找到最近一次放量日（从后往前）
        last_spike_idx = -1
        for i in range(len(klines) - 1, -1, -1):
            v = klines[i].get('volume', 0) or 0
            if base_vol > 0 and v >= base_vol * 3:
                last_spike_idx = i
                break

        if last_spike_idx < 0 or last_spike_idx >= len(klines) - 2:
            return 0

        # 放量后连续缩量天数
        spike_vol = klines[last_spike_idx]['volume']
        contraction_days = 0
        for k in klines[last_spike_idx + 1:]:
            v = k.get('volume', 0) or 0
            if v < spike_vol * 0.5:  # 量能降至放量日50%以下
                contraction_days += 1
            else:
                break

        if contraction_days >= 3:
            return 10
        elif contraction_days >= 2:
            return 7
        elif contraction_days >= 1:
            return 4
        return 0

    # ==================== 第二层: 题材催化 (25分) ====================

    def _score_catalyst(self, code: str, plates: List[str]) -> tuple:
        """题材催化评分"""
        score = 0.0
        signals = []

        if not plates:
            return score, signals

        # 1. 板块联动数 (10分): 同板块内有蓄势信号的股票数
        max_linked = 0
        linked_plate = ""
        for plate in plates:
            linked = len(self._plate_signal_cache.get(plate, []))
            if linked > max_linked:
                max_linked = linked
                linked_plate = plate

        if max_linked >= 3:
            score += 10; signals.append(f"板块联动: {linked_plate}内{max_linked}只蓄势")
        elif max_linked >= 2:
            score += 6; signals.append(f"板块联动: {linked_plate}内{max_linked}只蓄势")

        # 2. 板块内已爆发股 (10分): 同板块近3日涨≥10%的股票数
        max_exploded = 0
        exploded_plate = ""
        for plate in plates:
            exploded = self._plate_explosion_cache.get(plate, 0)
            if exploded > max_exploded:
                max_exploded = exploded
                exploded_plate = plate

        if max_exploded >= 3:
            score += 10; signals.append(f"{exploded_plate}已有{max_exploded}只爆发")
        elif max_exploded >= 2:
            score += 7; signals.append(f"{exploded_plate}已有{max_exploded}只爆发")
        elif max_exploded >= 1:
            score += 4; signals.append(f"{exploded_plate}有龙头启动")

        # 3. 板块新闻热度 (5分)
        news_score = self._get_plate_news_heat(plates)
        score += news_score
        if news_score >= 4:
            signals.append("板块新闻密集")

        return score, signals

    def _get_plate_news_heat(self, plates: List[str]) -> float:
        """查询板块近3日新闻密度"""
        if not plates:
            return 0
        try:
            # 用板块名做模糊匹配
            placeholders = ','.join(['?' for _ in plates])
            rows = self.db.execute_query(
                f"SELECT COUNT(*) FROM news_plates "
                f"WHERE plate_name IN ({placeholders}) "
                f"AND created_at >= datetime('now', '-3 days')",
                tuple(plates)
            )
            count = rows[0][0] if rows else 0
            if count >= 5:
                return 5
            elif count >= 3:
                return 3
            elif count >= 1:
                return 1
            return 0
        except Exception:
            return 0

    # ==================== 第三层: 阶段判断 (20分) ====================

    def _score_phase(self, klines: List[dict]) -> tuple:
        """阶段判断评分"""
        score = 0.0
        signals = []

        if len(klines) < 5:
            return score, signals

        base_vols = [k['volume'] for k in klines[:3] if k.get('volume', 0) > 0]
        base_vol = sum(base_vols) / len(base_vols) if base_vols else 1

        # 1. 爆发阶段 (10分): 数大阳线波数
        wave_count = 0
        in_wave = False
        for k in klines:
            o, c = k.get('open_price', 0), k.get('close_price', 0)
            change = (c - o) / o * 100 if o > 0 else 0
            if change >= 8:  # ≥8%算一波
                if not in_wave:
                    wave_count += 1
                    in_wave = True
            else:
                in_wave = False

        if wave_count == 0:
            score += 10; signals.append("首波蓄势(尚未爆发)")
        elif wave_count == 1:
            score += 7; signals.append("第二波机会")
        elif wave_count == 2:
            score += 3; signals.append("第三波(风险增加)")
        else:
            score += 1; signals.append(f"第{wave_count + 1}波(追高风险)")

        # 2. 距首次放量天数 (5分)
        first_spike_idx = -1
        for i, k in enumerate(klines):
            v = k.get('volume', 0) or 0
            if base_vol > 0 and v >= base_vol * 3:
                first_spike_idx = i
                break

        if first_spike_idx >= 0:
            days_since = len(klines) - 1 - first_spike_idx
            if 1 <= days_since <= 5:
                score += 5; signals.append(f"放量启动{days_since}天(最佳窗口)")
            elif 6 <= days_since <= 10:
                score += 3
            else:
                score += 1

        # 3. 市值区间 (5分) — 简化：用股价×成交量估算活跃度
        last_close = klines[-1].get('close_price', 0)
        last_vol = klines[-1].get('volume', 0)
        if last_close > 0 and last_vol > 0:
            daily_turnover = last_close * last_vol
            if 5_000_000 <= daily_turnover <= 500_000_000:
                score += 5  # 中等活跃
            elif daily_turnover > 500_000_000:
                score += 3  # 大盘，爆发力受限
            else:
                score += 2  # 太小，流动性风险

        return score, signals

    # ==================== 第四层: 风控适配 (15分) ====================

    def _score_risk(self, klines: List[dict]) -> tuple:
        """风控适配评分"""
        score = 0.0
        signals = []

        recent = klines[-5:] if len(klines) >= 5 else klines

        # 1. 振幅健康度 (5分)
        amplitudes = []
        for k in recent:
            h, l = k.get('high_price', 0), k.get('low_price', 0)
            if l > 0:
                amplitudes.append((h - l) / l * 100)

        avg_amp = sum(amplitudes) / len(amplitudes) if amplitudes else 0
        if 5 <= avg_amp <= 15:
            score += 5
        elif 3 <= avg_amp <= 20:
            score += 3
        elif avg_amp > 30:
            score += 1; signals.append(f"⚠️ 振幅过大({avg_amp:.0f}%)")
        else:
            score += 2

        # 2. 上影线风险 (5分)
        upper_shadow_ratio_total = 0
        count = 0
        for k in recent[-3:]:
            h = k.get('high_price', 0)
            o, c = k.get('open_price', 0), k.get('close_price', 0)
            body_high = max(o, c) if o > 0 and c > 0 else 0
            if h > 0 and body_high > 0:
                upper_shadow = h - body_high
                full_range = h - k.get('low_price', 0) if k.get('low_price', 0) > 0 else 1
                if full_range > 0:
                    upper_shadow_ratio_total += upper_shadow / full_range
                    count += 1

        avg_upper = upper_shadow_ratio_total / count if count > 0 else 0
        if avg_upper < 0.2:
            score += 5  # 上影线小，抛压轻
        elif avg_upper < 0.35:
            score += 3
        else:
            score += 1; signals.append("⚠️ 上影线偏长(抛压重)")

        # 3. 量价配合 (5分): 涨时放量跌时缩量
        up_vol, down_vol = [], []
        for k in recent:
            o, c, v = k.get('open_price', 0), k.get('close_price', 0), k.get('volume', 0)
            if o > 0 and c > 0 and v > 0:
                if c >= o:
                    up_vol.append(v)
                else:
                    down_vol.append(v)

        avg_up = sum(up_vol) / len(up_vol) if up_vol else 0
        avg_down = sum(down_vol) / len(down_vol) if down_vol else 0

        if avg_up > 0 and avg_down > 0:
            ratio = avg_up / avg_down
            if ratio >= 1.5:
                score += 5; signals.append("量价配合良好(涨放量跌缩量)")
            elif ratio >= 1.0:
                score += 3
            else:
                score += 1; signals.append("⚠️ 量价背离")
        elif avg_up > 0:
            score += 4  # 全是阳线

        return score, signals

    # ==================== 交易建议 ====================

    def _build_trade_suggestion(self, klines: List[dict],
                                 total_score: float) -> dict:
        """生成交易参数建议"""
        last = klines[-1]
        close = last.get('close_price', 0)
        if close <= 0:
            return {}

        # 支撑位（近5日最低价中位数）
        recent_lows = sorted([k['low_price'] for k in klines[-5:]
                              if k.get('low_price', 0) > 0])
        support = recent_lows[len(recent_lows) // 2] if recent_lows else close * 0.95

        buy_price = round(close * 0.98, 3)       # 前收-2%低吸
        stop_loss = round(support * 0.97, 3)      # 支撑位再下3%
        stop_loss_pct = round((close - stop_loss) / close * 100, 1)
        target = round(close * 1.15, 3)           # 目标+15%

        return {
            'buy_price': buy_price,
            'stop_loss': stop_loss,
            'stop_loss_pct': min(stop_loss_pct, 8.0),  # 最大止损8%
            'target_price': target,
            'target_pct': 15.0,
            'max_hold_days': 3,
            'position_pct': 10,  # 建议仓位上限
            'entry_note': f"开盘回调至{buy_price:.2f}附近低吸",
        }

    # ==================== 板块缓存预计算 ====================

    def precompute_plate_cache(self, all_stocks: List[Dict],
                                all_klines: Dict[str, List[dict]]):
        """
        预计算板块联动缓存（在批量评分前调用一次）

        Args:
            all_stocks: [{code, plates: [plate_name, ...], ...}]
            all_klines: {code: [kline_dicts]}
        """
        self._plate_signal_cache.clear()
        self._plate_explosion_cache.clear()

        for stock in all_stocks:
            code = stock.get('code', '')
            plates = stock.get('plates', [])
            klines = all_klines.get(code, [])

            if not klines or len(klines) < 5:
                continue

            # 检查是否有蓄势信号（简化：放量≥2天 + 支撑测试≥2次）
            base_vols = [k['volume'] for k in klines[:3] if k.get('volume', 0) > 0]
            base_vol = sum(base_vols) / len(base_vols) if base_vols else 1

            spike_days = sum(1 for k in klines[-10:]
                            if k.get('volume', 0) >= base_vol * 3)

            support_zones = defaultdict(int)
            for k in klines[-10:]:
                low = k.get('low_price', 0)
                if low > 0:
                    support_zones[round(low * 50) / 50] += 1
            max_tests = max(support_zones.values()) if support_zones else 0

            has_signal = spike_days >= 2 and max_tests >= 2

            if has_signal:
                for plate in plates:
                    if plate not in self._plate_signal_cache:
                        self._plate_signal_cache[plate] = []
                    self._plate_signal_cache[plate].append(code)

            # 检查近3日是否已爆发（涨≥10%）
            if len(klines) >= 2:
                recent_3 = klines[-3:]
                for k in recent_3:
                    o, c = k.get('open_price', 0), k.get('close_price', 0)
                    if o > 0 and (c - o) / o * 100 >= 10:
                        for plate in plates:
                            self._plate_explosion_cache[plate] = \
                                self._plate_explosion_cache.get(plate, 0) + 1
                        break

        logger.info(
            f"[MOMENTUM] 板块缓存: {len(self._plate_signal_cache)}个板块有蓄势信号, "
            f"{len(self._plate_explosion_cache)}个板块有爆发股"
        )

    # ==================== 工具方法 ====================

    @staticmethod
    def _verdict(score: float) -> str:
        if score >= 75:
            return "强烈推荐"
        if score >= 60:
            return "推荐"
        if score >= 45:
            return "可关注"
        return "观望"

    @staticmethod
    def _empty_result() -> Dict[str, Any]:
        return {
            'total': 0,
            'dimensions': {
                'accumulation': 0, 'catalyst': 0,
                'phase': 0, 'risk': 0,
            },
            'signals': [],
            'trade_suggestion': {},
            'verdict': '观望',
        }
