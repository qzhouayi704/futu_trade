#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
长期横盘启动扫描器

识别类似"富通国际"的底部横盘→放量启动模式：
1. 90日价格位置低（< 35%），排除高位回落反弹
2. 横盘期（第4~15日前）振幅窄（< 20%），说明长期横盘
3. 近3日放量（> 横盘期均量 × 2）
4. 近3日温和上涨（0~20%）
5. 换手率开始活跃（近3日均换手 > 1%）

与 BreakoutScanner 的区别：
- BreakoutScanner 检测"突破那一天"（短期5日，涨幅≥5%）
- 本扫描器检测"启动初期"（长期30-90日横盘后刚开始放量）
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class ConsolidationBreakoutCandidate:
    """横盘启动候选股"""
    code: str = ""
    name: str = ""
    price: float = 0
    # 位置
    pos_30d: float = 0       # 30日价格位置%
    pos_90d: float = 0       # 90日价格位置%
    # 横盘特征
    consol_range: float = 0  # 横盘期振幅%
    consol_days: int = 0     # 横盘天数
    # 启动特征
    vol_ratio: float = 0     # 放量倍数（近3日/横盘期）
    change_3d: float = 0     # 3日涨幅%
    turnover_3d: float = 0   # 近3日平均换手率%
    breakout: bool = False   # 是否已突破横盘上沿
    # 评分
    score: float = 0
    signal_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            'code': self.code,
            'name': self.name,
            'price': round(self.price, 3),
            'pos_30d': round(self.pos_30d, 1),
            'pos_90d': round(self.pos_90d, 1),
            'consol_range': round(self.consol_range, 1),
            'vol_ratio': round(self.vol_ratio, 1),
            'change_3d': round(self.change_3d, 2),
            'turnover_3d': round(self.turnover_3d, 2),
            'breakout': self.breakout,
            'score': round(self.score, 1),
            'signal_note': self.signal_note,
        }


class ConsolidationBreakoutScanner:
    """长期横盘启动扫描器"""

    # 筛选阈值
    POS_90D_MAX = 35.0      # 90日位置上限%（排除高位回落）
    POS_30D_MAX = 45.0      # 30日位置上限%
    CONSOL_RANGE_MAX = 20.0 # 横盘期振幅上限%
    VOL_RATIO_MIN = 1.5     # 放量倍数下限
    CHANGE_3D_MIN = 0.0     # 3日涨幅下限%
    CHANGE_3D_MAX = 20.0    # 3日涨幅上限%
    TURNOVER_3D_MIN = 0.8   # 近3日均换手率下限%

    def __init__(self, db_manager=None):
        self.db = db_manager

    def scan(self) -> List[ConsolidationBreakoutCandidate]:
        """扫描全市场，返回横盘启动候选股"""
        if not self.db:
            logger.warning("【横盘启动】db_manager 不可用")
            return []

        stocks = self.db.execute_query(
            "SELECT code, name FROM stocks WHERE is_low_activity = 0"
        )
        if not stocks:
            return []

        candidates = []
        for code, name in stocks:
            result = self._check_stock(code, name)
            if result:
                candidates.append(result)

        candidates.sort(key=lambda x: x.score, reverse=True)
        logger.info(f"【横盘启动】扫描 {len(stocks)} 只，发现 {len(candidates)} 只候选")
        return candidates

    def _check_stock(self, code: str, name: str) -> Optional[ConsolidationBreakoutCandidate]:
        """检查单只股票"""
        rows = self.db.execute_query(
            "SELECT close_price, high_price, low_price, volume, turnover_rate "
            "FROM kline_data WHERE stock_code = ? ORDER BY time_key DESC LIMIT 90",
            (code,)
        )
        if not rows or len(rows) < 25:
            return None

        cur = rows[0][0]
        if not cur or cur <= 0:
            return None

        # 30日区间
        h30 = max(r[1] for r in rows[:30] if r[1])
        l30 = min(r[2] for r in rows[:30] if r[2] and r[2] > 0)
        if not h30 or not l30 or h30 == l30:
            return None
        pos30 = (cur - l30) / (h30 - l30) * 100
        if pos30 > self.POS_30D_MAX:
            return None

        # 90日区间
        h90 = max(r[1] for r in rows if r[1])
        l90 = min(r[2] for r in rows if r[2] and r[2] > 0)
        if not h90 or not l90 or h90 == l90:
            return None
        pos90 = (cur - l90) / (h90 - l90) * 100
        if pos90 > self.POS_90D_MAX:
            return None

        # 横盘期（第4~15日）
        consol = rows[4:15]
        if len(consol) < 8:
            return None
        ch = max(r[1] for r in consol if r[1])
        cl = min(r[2] for r in consol if r[2] and r[2] > 0)
        if not ch or not cl:
            return None
        cm = (ch + cl) / 2
        if cm <= 0:
            return None
        consol_range = (ch - cl) / cm * 100
        if consol_range > self.CONSOL_RANGE_MAX:
            return None

        # 横盘期均量
        consol_vols = [r[3] for r in consol if r[3] and r[3] > 0]
        if not consol_vols:
            return None
        consol_avg_vol = sum(consol_vols) / len(consol_vols)
        if consol_avg_vol <= 0:
            return None

        # 近3日放量
        v3 = sum(r[3] for r in rows[:3] if r[3]) / 3
        vol_ratio = v3 / consol_avg_vol
        if vol_ratio < self.VOL_RATIO_MIN:
            return None

        # 近3日涨幅
        p3 = rows[2][0]
        if not p3 or p3 <= 0:
            return None
        change_3d = (cur - p3) / p3 * 100
        if change_3d < self.CHANGE_3D_MIN or change_3d > self.CHANGE_3D_MAX:
            return None

        # 换手率
        tr3 = sum((r[4] or 0) for r in rows[:3]) / 3
        if tr3 < self.TURNOVER_3D_MIN:
            return None

        # 是否突破横盘上沿
        breakout = cur > ch

        # 评分
        score = self._calc_score(consol_range, vol_ratio, pos90, change_3d, breakout)

        # 信号描述
        bo_text = "已突破" if breakout else "接近突破"
        note = f"横盘{consol_range:.0f}%→放量{vol_ratio:.0f}倍，90日位置{pos90:.0f}%，{bo_text}"

        return ConsolidationBreakoutCandidate(
            code=code, name=name, price=cur,
            pos_30d=pos30, pos_90d=pos90,
            consol_range=consol_range,
            vol_ratio=vol_ratio, change_3d=change_3d,
            turnover_3d=tr3, breakout=breakout,
            score=score, signal_note=note,
        )

    def _calc_score(self, consol_range, vol_ratio, pos90, change_3d, breakout) -> float:
        """综合评分 0~100"""
        # 横盘越紧越好 (30%)
        range_score = max(0, (20 - consol_range) / 20 * 100) * 0.30

        # 放量越大越好 (25%)
        vol_score = min(vol_ratio / 8 * 100, 100) * 0.25

        # 90日位置越低越好 (25%)
        pos_score = max(0, (35 - pos90) / 35 * 100) * 0.25

        # 已突破加分 (20%)
        bo_score = (80 if breakout else 30) * 0.20

        return range_score + vol_score + pos_score + bo_score
