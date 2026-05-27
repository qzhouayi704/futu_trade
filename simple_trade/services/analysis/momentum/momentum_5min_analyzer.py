#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
5分钟动量分析器

基于日内分时数据（rt_data）合成5分钟K线，计算动量特征：
- 动量方向：最近N根K线的涨跌方向
- 动量强度：K线实体占比、影线特征
- 动量变化：加速/减速/转向
- 顶底分型：识别日内高低点

数据来源：
- rt_data 表（分时价格数据，由行情管道持续写入）
- 不依赖额外API调用，纯粹基于已有的分时数据合成

由 CapitalFlowSignalEngine 在每个监控周期调用。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Dict, List, Optional

logger = logging.getLogger("momentum.5min")


@dataclass
class Bar5Min:
    """5分钟K线"""
    time_key: str           # "HH:MM"
    open_price: float = 0.0
    close_price: float = 0.0
    high_price: float = 0.0
    low_price: float = 0.0
    volume: float = 0.0
    turnover: float = 0.0

    @property
    def body(self) -> float:
        """实体大小（绝对值）"""
        return abs(self.close_price - self.open_price)

    @property
    def body_pct(self) -> float:
        """实体占振幅百分比"""
        amplitude = self.high_price - self.low_price
        if amplitude <= 0:
            return 0.0
        return self.body / amplitude

    @property
    def is_bullish(self) -> bool:
        """是否阳线"""
        return self.close_price > self.open_price

    @property
    def upper_shadow(self) -> float:
        """上影线长度"""
        return self.high_price - max(self.open_price, self.close_price)

    @property
    def lower_shadow(self) -> float:
        """下影线长度"""
        return min(self.open_price, self.close_price) - self.low_price

    @property
    def change_pct(self) -> float:
        """涨跌幅（%）"""
        if self.open_price <= 0:
            return 0.0
        return (self.close_price - self.open_price) / self.open_price * 100


@dataclass
class MomentumSnapshot:
    """动量快照 — 每只股票的5分钟动量特征汇总

    供 RuleContext 使用，传入信号引擎做买卖判断。
    """
    # 基础
    stock_code: str = ""
    bar_count: int = 0                # 当日可用的5分钟K线数

    # 动量方向 (正=上涨动量, 负=下跌动量)
    momentum_direction: float = 0.0   # -1.0 ~ +1.0，最近3根K线的方向加权
    momentum_strength: float = 0.0    # 0 ~ 1.0，动量强度（实体大小+成交量）

    # 动量变化
    momentum_acceleration: float = 0.0  # >0 加速, <0 减速, ≈0 稳定
    momentum_trend: str = "unknown"     # "accelerating" / "stable" / "decelerating" / "reversing"

    # 形态特征
    has_top_pattern: bool = False      # 是否出现顶分型（冲高回落）
    has_bottom_pattern: bool = False   # 是否出现底分型（跌稳反弹）
    upper_shadow_warning: bool = False # 最近K线上影线过长（冲高被砸）
    lower_shadow_support: bool = False # 最近K线下影线长（有支撑）

    # 最近K线摘要
    last_bar_change_pct: float = 0.0  # 最后一根K线涨跌幅
    last_3_bars_change_pct: float = 0.0  # 最近3根K线累计涨跌幅
    volume_trend: str = "unknown"     # "increasing" / "stable" / "decreasing"

    # 时间戳
    updated_at: str = ""


class Momentum5MinAnalyzer:
    """5分钟动量分析器

    从 rt_data（分时数据）合成5分钟K线，计算动量特征。

    使用方式：
        analyzer = Momentum5MinAnalyzer(db_manager)
        snapshot = analyzer.analyze(stock_code)
        # snapshot 传入 RuleContext 供信号规则使用
    """

    # 分析需要的最少K线数
    MIN_BARS = 3

    def __init__(self, db_manager):
        self._db = db_manager
        # 缓存：{stock_code: MomentumSnapshot}
        self._cache: Dict[str, MomentumSnapshot] = {}
        self._cache_date: str = ""

    def analyze(self, stock_code: str) -> Optional[MomentumSnapshot]:
        """分析单只股票的5分钟动量

        Returns:
            MomentumSnapshot 或 None（数据不足时）
        """
        today = date.today().isoformat()
        if self._cache_date != today:
            self._cache.clear()
            self._cache_date = today

        # 缓存命中（60秒内有效）
        cached = self._cache.get(stock_code)
        if cached and cached.updated_at:
            try:
                cache_time = datetime.fromisoformat(cached.updated_at)
                if (datetime.now() - cache_time).total_seconds() < 60:
                    return cached
            except (ValueError, TypeError):
                pass

        # 从 rt_data 合成5分钟K线
        bars = self._build_5min_bars(stock_code)
        if not bars or len(bars) < self.MIN_BARS:
            return None

        snapshot = self._compute_momentum(stock_code, bars)
        self._cache[stock_code] = snapshot
        return snapshot

    def analyze_batch(self, stock_codes: List[str]) -> Dict[str, MomentumSnapshot]:
        """批量分析"""
        results = {}
        for code in stock_codes:
            snap = self.analyze(code)
            if snap:
                results[code] = snap
        return results

    def _build_5min_bars(self, stock_code: str) -> List[Bar5Min]:
        """从 rt_data 合成5分钟K线

        rt_data 表结构：time, cur_price, avg_price, volume, turnover
        按5分钟窗口聚合为 OHLCV K线。
        """
        if not self._db:
            return []

        today = date.today().isoformat()
        try:
            rows = self._db.execute_query("""
                SELECT time, cur_price, volume, turnover
                FROM rt_data
                WHERE stock_code = ? AND trade_date = ?
                ORDER BY time ASC
            """, (stock_code, today))
        except Exception as e:
            logger.debug(f"[动量] 查询 rt_data 失败 {stock_code}: {e}")
            return []

        if not rows or len(rows) < 5:
            return []

        # 按5分钟窗口聚合
        # 时间格式可能是 "2026-05-22 10:05:00" 或 "10:05"
        bar_map: Dict[str, List] = {}
        for row in rows:
            time_str = str(row[0])
            price = float(row[1]) if row[1] else 0
            volume = float(row[2]) if row[2] else 0
            turnover = float(row[3]) if row[3] else 0

            if price <= 0:
                continue

            # 提取 HH:MM
            hhmm = self._extract_hhmm(time_str)
            if not hhmm:
                continue

            # 映射到5分钟窗口（09:30->09:30, 09:31->09:30, 09:34->09:30, 09:35->09:35）
            bar_key = self._to_5min_key(hhmm)
            if bar_key not in bar_map:
                bar_map[bar_key] = []
            bar_map[bar_key].append((price, volume, turnover))

        # 构建 Bar5Min
        bars = []
        for bar_key in sorted(bar_map.keys()):
            ticks = bar_map[bar_key]
            if not ticks:
                continue

            prices = [t[0] for t in ticks]
            volumes = [t[1] for t in ticks]
            turnovers = [t[2] for t in ticks]

            bars.append(Bar5Min(
                time_key=bar_key,
                open_price=prices[0],
                close_price=prices[-1],
                high_price=max(prices),
                low_price=min(prices),
                volume=sum(volumes),
                turnover=sum(turnovers),
            ))

        return bars

    def _compute_momentum(self, stock_code: str, bars: List[Bar5Min]) -> MomentumSnapshot:
        """从5分钟K线计算动量特征"""
        snapshot = MomentumSnapshot(
            stock_code=stock_code,
            bar_count=len(bars),
            updated_at=datetime.now().isoformat(),
        )

        if len(bars) < self.MIN_BARS:
            return snapshot

        # ── 1. 动量方向（最近3根K线加权） ──
        recent = bars[-3:]
        weights = [0.2, 0.3, 0.5]  # 越近权重越大
        direction_sum = 0.0
        for bar, w in zip(recent, weights):
            if bar.is_bullish:
                direction_sum += w
            else:
                direction_sum -= w
        snapshot.momentum_direction = round(direction_sum, 3)

        # ── 2. 动量强度（实体大小 + 成交量变化） ──
        last_bar = bars[-1]
        avg_body = sum(b.body for b in bars) / len(bars) if bars else 0
        if avg_body > 0:
            body_strength = min(last_bar.body / avg_body, 2.0) / 2.0
        else:
            body_strength = 0.0

        # 成交量相对强度
        avg_vol = sum(b.volume for b in bars) / len(bars) if bars else 0
        if avg_vol > 0:
            vol_strength = min(last_bar.volume / avg_vol, 2.0) / 2.0
        else:
            vol_strength = 0.0

        snapshot.momentum_strength = round((body_strength + vol_strength) / 2, 3)

        # ── 3. 动量加速度（最近3根vs前3根的实体变化） ──
        if len(bars) >= 6:
            prev_3 = bars[-6:-3]
            curr_3 = bars[-3:]
            prev_avg_body = sum(b.body for b in prev_3) / 3
            curr_avg_body = sum(b.body for b in curr_3) / 3

            if prev_avg_body > 0:
                accel = (curr_avg_body - prev_avg_body) / prev_avg_body
            else:
                accel = 0.0

            # 考虑方向一致性
            prev_dir = sum(1 if b.is_bullish else -1 for b in prev_3) / 3
            curr_dir = sum(1 if b.is_bullish else -1 for b in curr_3) / 3

            if prev_dir * curr_dir < 0:
                snapshot.momentum_trend = "reversing"
                snapshot.momentum_acceleration = round(-abs(accel), 3)
            elif accel > 0.3:
                snapshot.momentum_trend = "accelerating"
                snapshot.momentum_acceleration = round(accel, 3)
            elif accel < -0.3:
                snapshot.momentum_trend = "decelerating"
                snapshot.momentum_acceleration = round(accel, 3)
            else:
                snapshot.momentum_trend = "stable"
                snapshot.momentum_acceleration = round(accel, 3)

        # ── 4. 形态识别 ──
        if len(bars) >= 3:
            # 顶分型：中间K线最高，两侧低
            b1, b2, b3 = bars[-3], bars[-2], bars[-1]
            if (b2.high_price > b1.high_price and
                    b2.high_price > b3.high_price and
                    b3.close_price < b2.open_price):
                snapshot.has_top_pattern = True

            # 底分型：中间K线最低，两侧高
            if (b2.low_price < b1.low_price and
                    b2.low_price < b3.low_price and
                    b3.close_price > b2.open_price):
                snapshot.has_bottom_pattern = True

        # ── 5. 影线特征 ──
        if last_bar.high_price > last_bar.low_price:
            amplitude = last_bar.high_price - last_bar.low_price
            upper_ratio = last_bar.upper_shadow / amplitude
            lower_ratio = last_bar.lower_shadow / amplitude

            # 上影线 > 振幅60% → 冲高被砸
            if upper_ratio > 0.6 and last_bar.change_pct > 0:
                snapshot.upper_shadow_warning = True

            # 下影线 > 振幅60% → 下方有支撑
            if lower_ratio > 0.6 and last_bar.change_pct < 0:
                snapshot.lower_shadow_support = True

        # ── 6. 涨跌幅汇总 ──
        snapshot.last_bar_change_pct = round(last_bar.change_pct, 3)

        if len(bars) >= 3:
            first_of_3 = bars[-3]
            if first_of_3.open_price > 0:
                snapshot.last_3_bars_change_pct = round(
                    (last_bar.close_price - first_of_3.open_price)
                    / first_of_3.open_price * 100, 3
                )

        # ── 7. 成交量趋势 ──
        if len(bars) >= 6:
            prev_vol = sum(b.volume for b in bars[-6:-3]) / 3
            curr_vol = sum(b.volume for b in bars[-3:]) / 3
            if prev_vol > 0:
                vol_change = (curr_vol - prev_vol) / prev_vol
                if vol_change > 0.3:
                    snapshot.volume_trend = "increasing"
                elif vol_change < -0.3:
                    snapshot.volume_trend = "decreasing"
                else:
                    snapshot.volume_trend = "stable"

        return snapshot

    @staticmethod
    def _extract_hhmm(time_str: str) -> Optional[str]:
        """从各种时间格式中提取 HH:MM"""
        # "2026-05-22 10:05:00" → "10:05"
        # "10:05" → "10:05"
        # "10:05:30" → "10:05"
        try:
            if ' ' in time_str:
                time_part = time_str.split(' ')[-1]
            else:
                time_part = time_str
            parts = time_part.split(':')
            if len(parts) >= 2:
                h, m = int(parts[0]), int(parts[1])
                return f"{h:02d}:{m:02d}"
        except (ValueError, IndexError):
            pass
        return None

    @staticmethod
    def _to_5min_key(hhmm: str) -> str:
        """将 HH:MM 映射到5分钟窗口起点

        09:30 → 09:30, 09:31 → 09:30, 09:34 → 09:30, 09:35 → 09:35
        """
        try:
            h, m = int(hhmm[:2]), int(hhmm[3:5])
            m_floor = (m // 5) * 5
            return f"{h:02d}:{m_floor:02d}"
        except (ValueError, IndexError):
            return hhmm
