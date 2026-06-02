#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多维度阻力位突破 + 大单资金流入 复合扫描器

扫描股票池，识别符合以下模式的股票：
1. 日线级别：今日收盘突破 5/10/20 日最高价
2. 日内级别（可选增强）：突破日内阻力位（成交量聚集区、大单卖出区、盘口挂单墙）
3. 资金确认：主力净流入为正 + 大单买入占比 > 50% + 连续流入天数
4. 量能配合：放量 + 阳线 + 涨幅适中

典型案例：HK.02706 — 缩量整理后放量突破前高，同时主力资金持续涌入。
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from ...utils.market_helper import MarketTimeHelper

logger = logging.getLogger(__name__)


@dataclass
class ResistanceBreakoutCandidate:
    """阻力位突破候选股"""
    code: str = ""
    name: str = ""
    close: float = 0
    change_pct: float = 0

    # 日线突破信息
    daily_breakout_level: str = ""       # "5日高" / "10日高" / "20日高" / ""
    daily_resistance_price: float = 0    # 被突破的日线阻力位
    daily_breakout_pct: float = 0        # 突破幅度%

    # 日内突破信息（可选）
    intraday_breakout: bool = False
    intraday_level_type: str = ""        # "volume_poc" / "big_order_sell" / "order_book_ask"
    intraday_level_label: str = ""       # "成交密集区" / "大单卖出区" / "卖盘挂单墙"
    intraday_resistance_price: float = 0
    intraday_resistance_strength: int = 0

    # 资金信息
    net_inflow_ratio: float = 0
    big_order_buy_ratio: float = 0
    capital_continuity_days: int = 0
    capital_score: float = 0
    main_net_inflow: float = 0

    # 量能
    turnover_rate: float = 0
    volume_ratio: float = 0

    # 综合
    score: float = 0
    signal_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            'code': self.code,
            'name': self.name,
            'close': round(self.close, 3),
            'change_pct': round(self.change_pct, 2),
            # 日线突破
            'daily_breakout_level': self.daily_breakout_level,
            'daily_resistance_price': round(self.daily_resistance_price, 3),
            'daily_breakout_pct': round(self.daily_breakout_pct, 2),
            # 日内突破
            'intraday_breakout': self.intraday_breakout,
            'intraday_level_type': self.intraday_level_type,
            'intraday_level_label': self.intraday_level_label,
            'intraday_resistance_price': round(self.intraday_resistance_price, 3),
            'intraday_resistance_strength': self.intraday_resistance_strength,
            # 资金
            'net_inflow_ratio': round(self.net_inflow_ratio, 4),
            'big_order_buy_ratio': round(self.big_order_buy_ratio, 4),
            'capital_continuity_days': self.capital_continuity_days,
            'capital_score': round(self.capital_score, 1),
            'main_net_inflow': round(self.main_net_inflow, 2),
            # 量能
            'turnover_rate': round(self.turnover_rate, 3),
            'volume_ratio': round(self.volume_ratio, 2),
            # 综合
            'score': round(self.score, 1),
            'signal_note': self.signal_note,
        }


class ResistanceBreakoutScanner:
    """多维度阻力位突破 + 资金流入 复合扫描器"""

    # 涨幅限制（避免追高）
    MAX_CHANGE_PCT = 15.0

    def __init__(self, db_manager, intraday_levels_service=None):
        """
        Args:
            db_manager: 数据库管理器
            intraday_levels_service: 日内阻力位服务（可选，有则增加日内维度）
        """
        self.db = db_manager
        self.intraday_levels = intraday_levels_service

    async def scan(self, stock_codes: List[str] = None) -> List[ResistanceBreakoutCandidate]:
        """
        扫描股票池，返回突破阻力位+资金流入的候选股

        Args:
            stock_codes: 指定股票列表，None 则从 DB 自动获取

        Returns:
            按评分降序排列的候选股列表（Top 20）
        """
        if not self.db:
            logger.warning("【突破扫描】db_manager 不可用")
            return []

        # 获取有近期K线的股票
        if stock_codes:
            codes = stock_codes
        else:
            codes = self._get_scannable_stocks()

        if not codes:
            logger.info("【突破扫描】无可扫描股票")
            return []

        candidates = []
        scanned = 0

        for code in codes:
            result = await self._check_stock(code)
            if result:
                candidates.append(result)
            scanned += 1

        # 按评分排序
        candidates.sort(key=lambda x: x.score, reverse=True)

        logger.info(
            f"【突破扫描】扫描 {scanned} 只股票，"
            f"发现 {len(candidates)} 只突破候选"
        )
        return candidates[:20]

    def _get_scannable_stocks(self) -> List[str]:
        """获取有近期K线数据的股票代码列表"""
        try:
            rows = self.db.execute_query("""
                SELECT DISTINCT stock_code FROM kline_data
                WHERE date(time_key) >= date('now', '-3 days')
            """)
            return [r[0] for r in rows] if rows else []
        except Exception as e:
            logger.error(f"【突破扫描】获取股票列表失败: {e}")
            return []

    async def _check_stock(self, stock_code: str) -> Optional[ResistanceBreakoutCandidate]:
        """检查单只股票是否满足突破+资金条件"""

        # Step 1: 日线突破检查（必要条件）
        daily = self._check_daily_breakout(stock_code)
        if not daily:
            return None

        # Step 2: 涨幅限制
        if daily['change_pct'] > self.MAX_CHANGE_PCT:
            return None

        # Step 3: 资金确认
        capital = self._check_capital_flow(stock_code)
        # 资金必须为正
        if capital['net_inflow_ratio'] <= 0:
            return None

        # Step 4: 日内突破检查（可选增强）
        intraday = await self._check_intraday_breakout(stock_code, daily['close'])

        # Step 5: 计算综合评分
        score = self._calc_score(daily, intraday, capital)

        # Step 6: 获取股票名称
        name = self._get_stock_name(stock_code)

        # Step 7: 生成信号描述
        note = self._build_signal_note(daily, intraday, capital)

        return ResistanceBreakoutCandidate(
            code=stock_code,
            name=name,
            close=daily['close'],
            change_pct=daily['change_pct'],
            # 日线
            daily_breakout_level=daily['level'],
            daily_resistance_price=daily['resistance_price'],
            daily_breakout_pct=daily['breakout_pct'],
            # 日内
            intraday_breakout=intraday.get('broken', False),
            intraday_level_type=intraday.get('type', ''),
            intraday_level_label=intraday.get('label', ''),
            intraday_resistance_price=intraday.get('price', 0),
            intraday_resistance_strength=intraday.get('strength', 0),
            # 资金
            net_inflow_ratio=capital['net_inflow_ratio'],
            big_order_buy_ratio=capital['big_order_buy_ratio'],
            capital_continuity_days=capital['continuity_days'],
            capital_score=capital['capital_score'],
            main_net_inflow=capital['main_net_inflow'],
            # 量能
            turnover_rate=daily.get('turnover_rate', 0),
            volume_ratio=daily.get('vol_ratio', 0),
            # 综合
            score=score,
            signal_note=note,
        )

    # ==================== 日线突破检查 ====================

    def _check_daily_breakout(self, stock_code: str) -> Optional[dict]:
        """检查日线级别阻力位突破（5/10/20日高点）"""
        try:
            rows = self.db.execute_query("""
                SELECT time_key, open_price, high_price, low_price, close_price,
                       volume, turnover_rate
                FROM kline_data WHERE stock_code = ?
                ORDER BY time_key DESC LIMIT 25
            """, (stock_code,))

            if not rows or len(rows) < 6:
                return None

            rows = list(reversed(rows))  # 按时间升序

            # 今天 = 最后一根K线
            today = rows[-1]
            t_date, t_open, t_high, t_low, t_close, t_vol, t_tr = today

            # 验证是最新交易日数据
            market = MarketTimeHelper.get_market_from_code(stock_code)
            expected_date = MarketTimeHelper.get_market_today(market)
            if t_date[:10] != expected_date:
                return None

            if not t_close or not t_open or t_close <= 0:
                return None

            # 前一天收盘
            prev_close = rows[-2][4] or 0
            if prev_close <= 0:
                return None

            change_pct = (t_close - prev_close) / prev_close * 100

            # 必须是阳线或至少持平
            if t_close < t_open * 0.995:
                return None

            # 计算各级别阻力位（排除今天）
            prev_bars = rows[:-1]

            # 5日高（前5根K线）
            high_5d = max(r[2] or 0 for r in prev_bars[-5:]) if len(prev_bars) >= 5 else 0
            # 10日高
            high_10d = max(r[2] or 0 for r in prev_bars[-10:]) if len(prev_bars) >= 10 else 0
            # 20日高
            high_20d = max(r[2] or 0 for r in prev_bars[-20:]) if len(prev_bars) >= 20 else 0

            # "刚刚突破"：近3日内至少有1日收盘在阻力位之下，今天站上了
            # 这样能捕捉到 1~3 天前突破并持续站稳的票
            recent_closes = [r[4] or 0 for r in prev_bars[-3:]]

            def _recently_broken(resistance: float) -> bool:
                """今日站上阻力位，且近3日内至少有1日在阻力位之下"""
                if resistance <= 0 or t_close <= resistance:
                    return False
                return any(c <= resistance for c in recent_closes)

            # 检查突破（从高到低检查，命中最高级别）
            level = ""
            resistance_price = 0

            if _recently_broken(high_20d):
                level = "20日高"
                resistance_price = high_20d
            elif _recently_broken(high_10d):
                level = "10日高"
                resistance_price = high_10d
            elif _recently_broken(high_5d):
                level = "5日高"
                resistance_price = high_5d

            if not level:
                return None

            breakout_pct = (t_close - resistance_price) / resistance_price * 100

            # 计算量比（今日成交量 / 前5日均量）
            prev5_vols = [r[5] or 0 for r in prev_bars[-5:]]
            avg_vol = sum(prev5_vols) / len(prev5_vols) if prev5_vols else 1
            vol_ratio = (t_vol or 0) / avg_vol if avg_vol > 0 else 0

            return {
                'close': t_close,
                'open': t_open,
                'change_pct': change_pct,
                'level': level,
                'resistance_price': resistance_price,
                'breakout_pct': breakout_pct,
                'turnover_rate': t_tr or 0,
                'vol_ratio': vol_ratio,
                'high_5d': high_5d,
                'high_10d': high_10d,
                'high_20d': high_20d,
            }

        except Exception as e:
            logger.debug(f"【突破扫描】日线检查失败 {stock_code}: {e}")
            return None

    # ==================== 日内突破检查 ====================

    async def _check_intraday_breakout(self, stock_code: str, current_price: float) -> dict:
        """检查日内阻力位突破（可选增强维度）"""
        result = {'broken': False, 'type': '', 'label': '', 'price': 0, 'strength': 0}

        if not self.intraday_levels or current_price <= 0:
            return result

        try:
            levels_result = await self.intraday_levels.get_levels(stock_code)
            if not levels_result or not levels_result.resistance_levels:
                return result

            # 检查是否已突破某个阻力位
            # 如果所有阻力位的价格都低于当前价，说明已经全部突破
            for level in levels_result.resistance_levels:
                if level.price > 0 and current_price > level.price:
                    result = {
                        'broken': True,
                        'type': level.type,
                        'label': level.label,
                        'price': level.price,
                        'strength': level.strength,
                    }
                    break  # 取第一个被突破的（强度最高的）

            return result

        except Exception as e:
            logger.debug(f"【突破扫描】日内检查失败 {stock_code}: {e}")
            return result

    # ==================== 资金流确认 ====================

    def _check_capital_flow(self, stock_code: str) -> dict:
        """从 DB 缓存读取资金流数据"""
        result = {
            'net_inflow_ratio': 0,
            'big_order_buy_ratio': 0,
            'continuity_days': 0,
            'capital_score': 0,
            'main_net_inflow': 0,
        }

        # 读取 capital_flow_cache（最新资金分布快照）
        try:
            rows = self.db.execute_query(
                "SELECT net_inflow_ratio, big_order_buy_ratio, capital_score, main_net_inflow "
                "FROM capital_flow_cache WHERE stock_code = ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (stock_code,)
            )
            if rows:
                result['net_inflow_ratio'] = rows[0][0] or 0
                result['big_order_buy_ratio'] = rows[0][1] or 0
                result['capital_score'] = rows[0][2] or 0
                result['main_net_inflow'] = rows[0][3] or 0
        except Exception:
            pass

        # 读取 capital_flow_daily（连续流入天数）
        try:
            rows = self.db.execute_query(
                "SELECT net_inflow FROM capital_flow_daily "
                "WHERE stock_code = ? ORDER BY date DESC LIMIT 10",
                (stock_code,)
            )
            if rows:
                days = 0
                for r in rows:
                    if r[0] and r[0] > 0:
                        days += 1
                    else:
                        break
                result['continuity_days'] = days
        except Exception:
            pass

        return result

    # ==================== 评分计算 ====================

    def _calc_score(self, daily: dict, intraday: dict, capital: dict) -> float:
        """
        综合评分 0~100

        维度权重：
        - 日线突破 30%: 突破级别越高分越高 + 突破幅度适中
        - 日内突破 20%: 有日内突破加分，无数据时按50分
        - 资金确认 30%: 净流入占比 + 大单买入比 + 持续天数
        - 量能趋势 20%: 放量 + 阳线 + 涨幅适中
        """

        # === 日线突破分 (30%) ===
        level = daily['level']
        if level == "20日高":
            level_score = 100
        elif level == "10日高":
            level_score = 70
        else:
            level_score = 50

        # 突破幅度修正：0~3%最佳，>5%减分
        bp = daily['breakout_pct']
        if 0 <= bp <= 3:
            bp_factor = 1.0
        elif bp <= 5:
            bp_factor = 0.8
        elif bp <= 8:
            bp_factor = 0.6
        else:
            bp_factor = 0.4

        daily_score = level_score * bp_factor * 0.30

        # === 日内突破分 (20%) ===
        if intraday.get('broken'):
            strength = intraday.get('strength', 50)
            intraday_score = min(strength, 100) * 0.20
        else:
            intraday_score = 50 * 0.20  # 无数据时中性分

        # === 资金确认分 (30%) ===
        # 净流入占比 (0~10分)
        ratio = capital['net_inflow_ratio']
        ratio_score = min(ratio / 0.15 * 100, 100)

        # 大单买入比 (0~10分)
        big_ratio = capital['big_order_buy_ratio']
        big_score = min(max((big_ratio - 0.3) / 0.4 * 100, 0), 100)

        # 持续天数 (0~10分)
        days = capital['continuity_days']
        if days >= 5:
            cont_score = 100
        elif days >= 3:
            cont_score = 80
        elif days >= 2:
            cont_score = 60
        elif days >= 1:
            cont_score = 30
        else:
            cont_score = 0

        capital_score = (ratio_score * 0.4 + big_score * 0.3 + cont_score * 0.3) * 0.30

        # === 量能趋势分 (20%) ===
        vol_ratio = daily.get('vol_ratio', 1)
        change = daily['change_pct']

        # 放量加分
        if vol_ratio >= 2:
            vol_s = 100
        elif vol_ratio >= 1.5:
            vol_s = 80
        elif vol_ratio >= 1:
            vol_s = 50
        else:
            vol_s = 20

        # 涨幅适中加分
        if 1 <= change <= 5:
            chg_s = 100
        elif 0 < change < 1:
            chg_s = 60
        elif 5 < change <= 10:
            chg_s = 70
        else:
            chg_s = 30

        trend_score = (vol_s * 0.6 + chg_s * 0.4) * 0.20

        total = daily_score + intraday_score + capital_score + trend_score
        return round(max(0, min(100, total)), 1)

    # ==================== 辅助方法 ====================

    def _get_stock_name(self, stock_code: str) -> str:
        return self.db.stock_queries.get_stock_name(stock_code)

    def _build_signal_note(self, daily: dict, intraday: dict, capital: dict) -> str:
        """生成可读的信号描述"""
        parts = []

        # 日线突破
        parts.append(f"突破{daily['level']}({daily['resistance_price']:.2f})")
        parts.append(f"+{daily['change_pct']:.1f}%")

        # 日内增强
        if intraday.get('broken'):
            parts.append(f"日内破{intraday['label']}")

        # 资金
        days = capital['continuity_days']
        if days >= 2:
            parts.append(f"资金连续{days}日流入")
        elif capital['net_inflow_ratio'] > 0:
            parts.append("资金净流入")

        # 大单
        if capital['big_order_buy_ratio'] > 0.6:
            parts.append(f"大单买入{capital['big_order_buy_ratio']*100:.0f}%")

        # 放量
        vr = daily.get('vol_ratio', 0)
        if vr >= 1.5:
            parts.append(f"放量{vr:.1f}倍")

        return "，".join(parts)
