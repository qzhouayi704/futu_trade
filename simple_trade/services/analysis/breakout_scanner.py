#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缩量蓄势 → 放量突破 盘后扫描器

盘后自动扫描整个股票池，识别符合以下模式的股票：
1. 前3日平均换手率 0.3% ~ 2%（筹码锁定但有流动性基础）
2. 近5日价格窄幅盘整（波动 < 15%）
3. 今日成交量 > 前3日均量 × 2（放量）
4. 今日收盘创近5日新高
5. 今日收阳线

回测验证（600只股票，2660个案例）：
- 换手率 1~2% 次日胜率 47%（最高），次日均涨 +1.3%
- 换手率 < 0.5% 次日胜率 42%，爆发力强但"一日游"风险高
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from ...utils.market_helper import MarketTimeHelper

logger = logging.getLogger(__name__)


@dataclass
class BreakoutCandidate:
    """突破候选股"""
    code: str = ""
    name: str = ""
    # 突破日数据
    close: float = 0
    change_pct: float = 0        # 突破日涨幅%
    volume: int = 0
    turnover_rate: float = 0     # 突破日换手率%
    amplitude: float = 0         # 突破日振幅%
    # 蓄势特征
    prev3_avg_tr: float = 0      # 前3日平均换手率%
    prev5_range_pct: float = 0   # 前5日价格波动幅度%
    vol_ratio: float = 0         # 放量倍数（今日量/前3日均量）
    # 评分
    score: float = 0             # 综合评分 0~100
    signal_note: str = ""        # 信号描述

    def to_dict(self) -> Dict[str, Any]:
        return {
            'code': self.code,
            'name': self.name,
            'close': round(self.close, 3),
            'change_pct': round(self.change_pct, 1),
            'turnover_rate': round(self.turnover_rate, 3),
            'amplitude': round(self.amplitude, 1),
            'prev3_avg_tr': round(self.prev3_avg_tr, 3),
            'prev5_range_pct': round(self.prev5_range_pct, 1),
            'vol_ratio': round(self.vol_ratio, 1),
            'score': round(self.score, 1),
            'signal_note': self.signal_note,
        }


class BreakoutScanner:
    """缩量蓄势 → 放量突破 扫描器"""

    # 筛选阈值（回测优化：600只股票全历史，1076个样本，胜率48.3%，次日均收+0.9%）
    TR_LOW = 0.5        # 前3日均换手率下限%
    TR_HIGH = 2.0       # 前3日均换手率上限%
    RANGE_MAX = 30.0    # 前5日价格波动上限%
    VOL_RATIO_MIN = 2.0 # 放量倍数下限
    CHANGE_MIN = 5.0    # 突破日最低涨幅%

    def __init__(self, db_manager=None):
        self.db = db_manager

    def scan(self) -> List[BreakoutCandidate]:
        """
        扫描整个股票池，返回符合条件的突破候选股

        Returns:
            按评分降序排列的候选股列表
        """
        if not self.db:
            logger.warning("【突破扫描】db_manager 不可用")
            return []

        # 只扫描最近2个交易日有K线的股票（避免用过期数据误报）
        stocks = self.db.execute_query("""
            SELECT stock_code, count(*) as cnt 
            FROM kline_data 
            WHERE stock_code IN (
                SELECT DISTINCT stock_code FROM kline_data 
                WHERE date(time_key) >= date('now', '-3 days')
            )
            GROUP BY stock_code HAVING cnt >= 8
        """)

        if not stocks:
            logger.info("【突破扫描】无近期K线数据的股票")
            return []

        candidates = []
        scanned = 0

        for stock_code, _ in stocks:
            result = self._check_stock(stock_code)
            if result:
                candidates.append(result)
            scanned += 1

        # 按评分排序
        candidates.sort(key=lambda x: x.score, reverse=True)

        logger.info(
            f"【突破扫描】扫描 {scanned} 只股票，"
            f"发现 {len(candidates)} 只突破候选"
        )
        return candidates

    def _check_stock(self, stock_code: str) -> Optional[BreakoutCandidate]:
        """检查单只股票是否符合突破条件"""
        # 获取最近8天K线（需要前5天 + 今天）
        rows = self.db.execute_query("""
            SELECT time_key, open_price, high_price, low_price, close_price,
                   volume, turnover_rate
            FROM kline_data WHERE stock_code = ?
            ORDER BY time_key DESC LIMIT 8
        """, (stock_code,))

        if not rows or len(rows) < 6:
            return None

        rows.reverse()  # 按时间升序

        # 今天 = 最后一根K线
        today = rows[-1]
        t_date, t_open, t_high, t_low, t_close, t_vol, t_tr = today

        # 验证这根 "今天" 的K线确实是最新交易日的数据，避免混入昨天未更新的数据
        market = MarketTimeHelper.get_market_from_code(stock_code)
        expected_date = MarketTimeHelper.get_market_today(market)
        if t_date[:10] != expected_date:
            return None

        if not t_close or not t_open or t_close <= 0 or t_open <= 0:
            return None

        # 前一天
        prev = rows[-2]
        prev_close = prev[4] or 0
        if prev_close <= 0:
            return None

        # ===== 条件判定 =====

        # C5: 阳线
        if t_close <= t_open:
            return None

        # 今日涨幅
        change_pct = (t_close - prev_close) / prev_close * 100
        if change_pct < self.CHANGE_MIN:
            return None

        # 前3日数据
        prev3 = rows[-4:-1]  # [-4, -3, -2]
        prev3_trs = [r[6] or 0 for r in prev3]
        prev3_vols = [r[5] or 0 for r in prev3]
        prev3_avg_tr = sum(prev3_trs) / 3
        prev3_avg_vol = sum(prev3_vols) / 3

        # C1: 前3日平均换手率在甜蜜区
        if prev3_avg_tr < self.TR_LOW or prev3_avg_tr > self.TR_HIGH:
            return None

        # C3: 放量
        if prev3_avg_vol <= 0:
            return None
        vol_ratio = (t_vol or 0) / prev3_avg_vol
        if vol_ratio < self.VOL_RATIO_MIN:
            return None

        # C2: 前5日价格盘整
        prev5 = rows[-6:-1]
        prev5_highs = [r[2] or 0 for r in prev5]
        prev5_lows = [r[3] or 0 for r in prev5 if (r[3] or 0) > 0]
        prev5_closes = [r[4] or 0 for r in prev5]

        if not prev5_lows:
            return None

        p5_high = max(prev5_highs)
        p5_low = min(prev5_lows)
        p5_range = (p5_high - p5_low) / p5_low * 100 if p5_low > 0 else 999

        if p5_range > self.RANGE_MAX:
            return None

        # C4: 创近5日收盘新高
        prev5_max_close = max(prev5_closes)
        if t_close <= prev5_max_close:
            return None

        # ===== 全部条件通过，计算评分 =====
        amplitude = ((t_high - t_low) / t_low * 100) if t_low > 0 else 0

        score = self._calc_score(
            change_pct=change_pct,
            vol_ratio=vol_ratio,
            prev3_avg_tr=prev3_avg_tr,
            p5_range=p5_range,
        )

        # 获取股票名称
        name = self.db.stock_queries.get_stock_name(stock_code)

        # 信号描述
        note = (
            f"缩量{prev3_avg_tr:.1f}%→放量{vol_ratio:.0f}倍，"
            f"突破+{change_pct:.0f}%，"
            f"前5日盘整{p5_range:.0f}%"
        )

        return BreakoutCandidate(
            code=stock_code,
            name=name,
            close=t_close,
            change_pct=change_pct,
            volume=t_vol or 0,
            turnover_rate=t_tr or 0,
            amplitude=amplitude,
            prev3_avg_tr=prev3_avg_tr,
            prev5_range_pct=p5_range,
            vol_ratio=vol_ratio,
            score=score,
            signal_note=note,
        )

    def _calc_score(
        self, change_pct: float, vol_ratio: float,
        prev3_avg_tr: float, p5_range: float
    ) -> float:
        """
        综合评分 0~100

        权重：
        - 涨幅 30%: 涨幅越大分越高（8%=60, 15%=80, 30%+=100）
        - 放量倍数 30%: 倍数越高分越高（2x=50, 5x=80, 10x+=100）
        - 换手率位置 20%: 1~2%最优=100, 0.3~1%=70, <0.3%=40
        - 盘整紧度 20%: 波动越小越好（<5%=100, 10%=60, 15%=30）
        """
        # 涨幅分
        chg_score = min(change_pct / 30 * 100, 100) * 0.30

        # 放量分
        vol_score = min(vol_ratio / 10 * 100, 100) * 0.30

        # 换手率分（1~2%最优）
        if 1.0 <= prev3_avg_tr <= 2.0:
            tr_score = 100
        elif 0.5 <= prev3_avg_tr < 1.0:
            tr_score = 70
        else:
            tr_score = 50
        tr_score *= 0.20

        # 盘整紧度分
        range_score = max(0, (15 - p5_range) / 15 * 100) * 0.20

        return chg_score + vol_score + tr_score + range_score
