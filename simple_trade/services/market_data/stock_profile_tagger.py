#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票行为标签器

基于日K线历史数据，为每只股票计算行为标签：
- 锁仓控盘：低换手率 + 高ATR（振幅/换手率比）+ 高成交量波动比
- 暴量拉升：成交量波动比极高，有单日暴涨后连续阴跌
- 仙股炒作：股价极低 + 高波动 + 高量比
- 明星高波动：ATR高但成交量稳定，正常高波动股
- 正常：各项指标均在正常范围

同时判定操控周期阶段（吸筹/拉升/出货/下跌）。
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class StockProfileTag:
    """股票画像标签"""
    label: str = "正常"            # 锁仓控盘 / 暴量拉升 / 仙股炒作 / 明星高波动 / 正常
    phase: str = ""               # 吸筹期 / 拉升期 / 出货期 / 下跌期（仅控盘/暴量标签）
    atr: float = 0.0              # 振幅/换手率比（ATR）
    vol_ratio: float = 0.0        # 成交量波动比（max/min）
    avg_amplitude: float = 0.0    # 平均振幅%
    avg_turnover_rate: float = 0.0  # 平均换手率%
    high_amp_ratio: float = 0.0   # 高振幅天数占比
    risk_note: str = ""           # 风险提示文字

    def to_dict(self) -> Dict[str, Any]:
        return {
            'label': self.label,
            'phase': self.phase,
            'atr': round(self.atr, 1),
            'vol_ratio': round(self.vol_ratio, 1),
            'avg_amplitude': round(self.avg_amplitude, 1),
            'avg_turnover_rate': round(self.avg_turnover_rate, 3),
            'high_amp_ratio': round(self.high_amp_ratio, 2),
            'risk_note': self.risk_note,
        }


class StockProfileTagger:
    """股票画像标签器"""

    # 标签判定阈值
    ATR_HIGH = 15.0          # ATR > 15x 视为高
    VOL_RATIO_HIGH = 10.0    # 成交量波动比 > 10x 视为高
    VOL_RATIO_EXTREME = 30.0 # 成交量波动比 > 30x 视为极端
    PENNY_PRICE = 2.0        # 仙股价格阈值（港元）
    PENNY_VOL_RATIO = 15.0   # 仙股量比阈值
    PENNY_AMP = 20.0         # 仙股振幅阈值

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def tag_stock(
        self,
        stock_code: str,
        klines: List[Dict[str, Any]],
        current_price: float = 0
    ) -> StockProfileTag:
        """
        根据日K线数据计算股票行为标签

        Args:
            stock_code: 股票代码
            klines: 日K线数据列表（至少10天），每项需含:
                     open, high, low, close, volume, turnover_rate
            current_price: 当前价格（用于仙股判定）

        Returns:
            StockProfileTag
        """
        tag = StockProfileTag()

        if not klines or len(klines) < 5:
            return tag

        # 计算基础指标
        amplitudes = []
        turnover_rates = []
        volumes = []

        for k in klines:
            h = k.get('high', k.get('high_price', 0)) or 0
            l = k.get('low', k.get('low_price', 0)) or 0
            rate = k.get('turnover_rate', 0) or 0
            vol = k.get('volume', 0) or 0

            amp = ((h - l) / l * 100) if l > 0 else 0
            amplitudes.append(amp)
            turnover_rates.append(rate)
            if vol > 0:
                volumes.append(vol)

        if not amplitudes or not volumes:
            return tag

        # 平均指标
        avg_amp = sum(amplitudes) / len(amplitudes)
        avg_rate = sum(turnover_rates) / len(turnover_rates) if turnover_rates else 0
        atr = avg_amp / avg_rate if avg_rate > 0 else 0
        vol_ratio = max(volumes) / min(volumes) if min(volumes) > 0 else 0
        high_amp_days = sum(1 for a in amplitudes if a > 10)
        high_amp_ratio = high_amp_days / len(amplitudes)

        tag.atr = atr
        tag.vol_ratio = vol_ratio
        tag.avg_amplitude = avg_amp
        tag.avg_turnover_rate = avg_rate
        tag.high_amp_ratio = high_amp_ratio

        # 判定价格（优先用当前价，否则用最后一根K线收盘价）
        price = current_price
        if price <= 0:
            last_k = klines[-1] if klines else {}
            price = last_k.get('close', last_k.get('close_price', 0)) or 0

        # ============ 标签判定（按优先级） ============

        # 1. 仙股炒作：低价 + 高波动 + 高量比
        if (price > 0 and price < self.PENNY_PRICE
                and avg_amp > self.PENNY_AMP
                and vol_ratio > self.PENNY_VOL_RATIO):
            tag.label = "仙股炒作"
            tag.risk_note = f"股价{price:.2f}元，日均振幅{avg_amp:.0f}%，极高风险"

        # 2. 暴量拉升：量比极端（>30x），不管ATR
        elif vol_ratio > self.VOL_RATIO_EXTREME:
            tag.label = "暴量拉升"
            tag.risk_note = f"成交量波动{vol_ratio:.0f}倍，有暴力拉升/砸盘特征"

        # 3. 锁仓控盘：ATR高 + 量比高 + 换手率低
        elif atr > self.ATR_HIGH and vol_ratio > self.VOL_RATIO_HIGH:
            tag.label = "锁仓控盘"
            tag.risk_note = f"换手率仅{avg_rate:.2f}%，但振幅{avg_amp:.0f}%，少量资金操控价格"

        # 4. 明星高波动：ATR高但量比正常
        elif atr > self.ATR_HIGH and vol_ratio <= self.VOL_RATIO_HIGH:
            tag.label = "明星高波动"
            tag.risk_note = f"高波动但成交量稳定，属正常活跃股"

        # 5. 正常
        else:
            tag.label = "正常"
            tag.risk_note = ""

        # ============ 操控周期判定（仅控盘/暴量/仙股标签） ============
        if tag.label in ("锁仓控盘", "暴量拉升", "仙股炒作"):
            tag.phase = self._detect_phase(klines)

        return tag

    def _detect_phase(self, klines: List[Dict[str, Any]]) -> str:
        """
        判定当前操控周期阶段

        基于最近5天的K线形态：
        - 吸筹期：缩量横盘，振幅收窄
        - 拉升期：放量大阳
        - 出货期：连续收阴，高位放量
        - 下跌期：持续阴跌，缩量
        """
        if len(klines) < 5:
            return ""

        recent = klines[-5:]  # 最近5天

        # 统计涨跌
        up_days = 0
        down_days = 0
        recent_volumes = []

        for k in recent:
            o = k.get('open', k.get('open_price', 0)) or 0
            c = k.get('close', k.get('close_price', 0)) or 0
            vol = k.get('volume', 0) or 0

            if c > o:
                up_days += 1
            elif c < o:
                down_days += 1
            recent_volumes.append(vol)

        # 对比前期成交量
        if len(klines) >= 10:
            earlier = klines[-10:-5]
            earlier_avg_vol = sum(
                (k.get('volume', 0) or 0) for k in earlier
            ) / max(len(earlier), 1)
        else:
            earlier_avg_vol = sum(recent_volumes) / max(len(recent_volumes), 1)

        recent_avg_vol = sum(recent_volumes) / max(len(recent_volumes), 1)
        vol_change = recent_avg_vol / earlier_avg_vol if earlier_avg_vol > 0 else 1

        # 最近的振幅变化
        recent_amps = []
        for k in recent:
            h = k.get('high', k.get('high_price', 0)) or 0
            l = k.get('low', k.get('low_price', 0)) or 0
            amp = ((h - l) / l * 100) if l > 0 else 0
            recent_amps.append(amp)
        avg_recent_amp = sum(recent_amps) / len(recent_amps) if recent_amps else 0

        # 判定
        if down_days >= 3 and vol_change > 0.8:
            return "出货期"
        elif down_days >= 3 and vol_change <= 0.8:
            return "下跌期"
        elif up_days >= 3 and vol_change > 1.5:
            return "拉升期"
        elif avg_recent_amp < 5 and vol_change < 0.8:
            return "吸筹期"
        elif up_days >= 2 and vol_change > 1.2:
            return "拉升期"
        elif down_days >= 2:
            return "出货期"
        else:
            return "吸筹期"

    def batch_tag(
        self,
        stocks_klines: Dict[str, List[Dict[str, Any]]],
        current_prices: Dict[str, float] = None
    ) -> Dict[str, StockProfileTag]:
        """
        批量计算股票标签

        Args:
            stocks_klines: {stock_code: [kline_data]}
            current_prices: {stock_code: current_price}

        Returns:
            {stock_code: StockProfileTag}
        """
        prices = current_prices or {}
        result = {}
        for code, klines in stocks_klines.items():
            try:
                result[code] = self.tag_stock(code, klines, prices.get(code, 0))
            except Exception as e:
                self.logger.warning(f"标签计算失败 {code}: {e}")
                result[code] = StockProfileTag()
        return result
