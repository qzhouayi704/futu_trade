#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多维趋势评分器 — 综合5个已有数据源输出趋势评分

五维评分:
  - VWAP偏离 (25%): 价格相对VWAP的偏离程度
  - Delta持续性 (30%): 近期Delta方向一致性和magnitude
  - 盘口压力 OFI (15%): Order Flow Imbalance
  - 成交量加速度 (15%): TapeVelocity相对基准的加速倍数
  - OFI趋势 (15%): 近期OFI历史方向一致性

纯读Scalping内存缓存，零I/O开销。
"""

import logging
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from simple_trade.services.scalping.engine import ScalpingEngine

logger = logging.getLogger("scalping.trend_scorer")


@dataclass
class TrendDimension:
    """单个维度的评分结果"""
    name: str           # "vwap" / "delta" / "pressure" / "volume" / "ofi"
    score: float        # -100 ~ +100
    weight: float       # 5维合计=1.0
    description: str


@dataclass
class TrendScoreResult:
    """趋势评分结果"""
    total_score: float = 0.0            # -100 ~ +100
    label: str = "neutral"              # "strong_bull"/"bull"/"neutral"/"bear"/"strong_bear"
    confidence: float = 0.0             # 0~1
    has_divergence: bool = False
    divergence_desc: str = ""
    dimensions: list = None

    def __post_init__(self):
        if self.dimensions is None:
            self.dimensions = []


# 权重配置
WEIGHTS = {
    "vwap": 0.25,
    "delta": 0.30,
    "pressure": 0.15,
    "volume": 0.15,
    "ofi": 0.15,
}


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(val, hi))


def _score_to_label(score: float) -> str:
    if score > 40:
        return "strong_bull"
    elif score > 15:
        return "bull"
    elif score > -15:
        return "neutral"
    elif score > -40:
        return "bear"
    else:
        return "strong_bear"


class TrendScorer:
    """多维趋势评分器"""

    def __init__(self, engine: "ScalpingEngine"):
        self._engine = engine

    def calculate(self, stock_code: str) -> TrendScoreResult:
        """计算指定股票的多维趋势评分"""
        dims: list[TrendDimension] = []

        # 1. VWAP偏离 (25%)
        dims.append(self._score_vwap(stock_code))

        # 2. Delta持续性 (30%)
        dims.append(self._score_delta(stock_code))

        # 3. 盘口压力 OFI (15%)
        dims.append(self._score_pressure(stock_code))

        # 4. 成交量加速度 (15%)
        dims.append(self._score_volume(stock_code))

        # 5. OFI趋势 (15%)
        dims.append(self._score_ofi_trend(stock_code))

        # 加权汇总
        total = sum(d.score * d.weight for d in dims)
        total = _clamp(total, -100, 100)

        # 置信度: 基于数据完整度和维度一致性
        data_count = sum(1 for d in dims if abs(d.score) > 5)
        data_ratio = data_count / len(dims)

        # 方向一致性
        pos = [d for d in dims if d.score > 15]
        neg = [d for d in dims if d.score < -15]
        if pos and neg:
            consistency = 0.5
        elif data_count >= 3:
            consistency = 1.0
        else:
            consistency = 0.7
        confidence = _clamp(data_ratio * consistency, 0, 1)

        # 背离检测
        has_div = False
        div_desc = ""
        significant = [d for d in dims if abs(d.score) > 20]
        if significant:
            pos_dims = [d for d in significant if d.score > 0]
            neg_dims = [d for d in significant if d.score < 0]
            if pos_dims and neg_dims:
                has_div = True
                pos_names = [f"{d.name}(+{d.score:.0f})" for d in pos_dims]
                neg_names = [f"{d.name}({d.score:.0f})" for d in neg_dims]
                div_desc = f"看涨{','.join(pos_names)} vs 看跌{','.join(neg_names)}"
                confidence *= 0.6  # 背离时降低置信度

        label = _score_to_label(total)

        return TrendScoreResult(
            total_score=round(total, 1),
            label=label,
            confidence=round(confidence, 2),
            has_divergence=has_div,
            divergence_desc=div_desc,
            dimensions=[
                {"name": d.name, "score": round(d.score, 1),
                 "weight": d.weight, "desc": d.description}
                for d in dims
            ],
        )

    # ------ 五维评分实现 ------

    def _score_vwap(self, stock_code: str) -> TrendDimension:
        """VWAP偏离: 价格在VWAP上方=看涨, 下方=看跌"""
        score = 0.0
        desc = "无VWAP数据"
        try:
            sig_eng = self._engine._signal_engine
            if sig_eng and hasattr(sig_eng, '_vwap_service') and sig_eng._vwap_service:
                cache = sig_eng._vwap_service._cache
                vwap_data = cache.get(stock_code)
                if vwap_data and vwap_data.get("vwap", 0) > 0:
                    vwap = vwap_data["vwap"]
                    price = vwap_data.get("last_price", vwap)
                    deviation = (price - vwap) / vwap * 100  # 偏离百分比
                    # clamp to [-3%, +3%] → map to [-100, +100]
                    score = _clamp(deviation, -3, 3) / 3 * 100
                    desc = f"偏离VWAP {deviation:+.2f}%"
        except Exception:
            pass
        return TrendDimension("VWAP", score, WEIGHTS["vwap"], desc)

    def _score_delta(self, stock_code: str) -> TrendDimension:
        """Delta持续性: 近6期Delta的方向一致性和magnitude"""
        score = 0.0
        desc = "无Delta数据"
        try:
            recent = self._engine._delta_calculator.get_recent_deltas(stock_code, 6)
            if recent and len(recent) >= 2:
                deltas = [d.delta for d in recent]
                # 正值占比
                pos_count = sum(1 for d in deltas if d > 0)
                pos_ratio = pos_count / len(deltas)
                # 映射 [0, 1] → [-100, +100]
                direction_score = (pos_ratio - 0.5) * 200

                # 近期magnitude加权（后3期权重更大）
                total_mag = sum(abs(d) for d in deltas)
                if total_mag > 0:
                    recent_mag = sum(abs(d) for d in deltas[-3:])
                    early_mag = sum(abs(d) for d in deltas[:-3]) or 1
                    accel = recent_mag / (early_mag + 1)
                    # 加速时增强得分, 减速时削弱
                    mag_factor = _clamp(accel, 0.5, 2.0)
                    direction_score *= mag_factor

                score = _clamp(direction_score, -100, 100)
                desc = f"正向{pos_count}/{len(deltas)}期"
        except Exception:
            pass
        return TrendDimension("Delta", score, WEIGHTS["delta"], desc)

    def _score_pressure(self, stock_code: str) -> TrendDimension:
        """盘口压力OFI: 当前OFI值直接映射"""
        score = 0.0
        desc = "无OFI数据"
        try:
            ofi_calc = self._engine._ofi_calculator
            if ofi_calc:
                ofi = ofi_calc.get_current_ofi(stock_code)
                if ofi is not None:
                    # OFI [-1, +1] → [-100, +100]
                    score = _clamp(ofi, -1, 1) * 100
                    desc = f"OFI={ofi:+.2f}"
        except Exception:
            pass
        return TrendDimension("盘口", score, WEIGHTS["pressure"], desc)

    def _score_volume(self, stock_code: str) -> TrendDimension:
        """成交量加速度: TapeVelocity/基准 的倍数"""
        score = 0.0
        desc = "无量能数据"
        try:
            tv = self._engine._tape_velocity
            count = tv.get_window_count(stock_code)
            baseline = tv.get_baseline_avg(stock_code)
            if baseline > 0:
                ratio = count / baseline
                # 获取Delta方向来判断是同向放量还是反向放量
                recent = self._engine._delta_calculator.get_recent_deltas(stock_code, 1)
                delta_dir = recent[-1].delta if recent else 0

                if ratio > 1.5:  # 放量
                    # 同向放量加分, 反向放量可能是洗盘
                    if delta_dir > 0:
                        score = min((ratio - 1) * 60, 100)
                    elif delta_dir < 0:
                        score = max(-(ratio - 1) * 60, -100)
                    else:
                        score = 0
                    desc = f"量比={ratio:.1f}x"
                else:
                    score = 0
                    desc = f"量比={ratio:.1f}x 平稳"
        except Exception:
            pass
        return TrendDimension("量能", score, WEIGHTS["volume"], desc)

    def _score_ofi_trend(self, stock_code: str) -> TrendDimension:
        """OFI趋势: 近5期OFI历史的方向一致性"""
        score = 0.0
        desc = "无OFI历史"
        try:
            ofi_calc = self._engine._ofi_calculator
            if ofi_calc:
                history = ofi_calc.get_history(stock_code)
                if history and len(history) >= 3:
                    recent = history[-5:]
                    values = [v for _, v in recent]
                    avg_ofi = sum(values) / len(values)
                    # 方向一致性
                    pos = sum(1 for v in values if v > 0)
                    consistency = pos / len(values)  # 0~1
                    # avg_ofi [-1, +1] × 一致性
                    raw = avg_ofi * (consistency if avg_ofi > 0 else (1 - consistency))
                    score = _clamp(raw * 100, -100, 100)
                    desc = f"均值{avg_ofi:+.2f} 一致{max(consistency, 1-consistency):.0%}"
        except Exception:
            pass
        return TrendDimension("OFI趋势", score, WEIGHTS["ofi"], desc)
