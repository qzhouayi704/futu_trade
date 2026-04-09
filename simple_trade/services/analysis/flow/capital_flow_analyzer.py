#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资金流向分析器

职责：
1. 获取股票的资金流向数据（主力、超大单、大单、中单、小单）
2. 计算资金评分（基于净流入占比、大单买入占比、资金持续性）
3. 检测资金流入持续性
4. 提供资金流向缓存机制
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from ....utils.converters import safe_float


class CacheTTL:
    """资金流缓存时效常量（秒）"""
    REALTIME = 60       # 实时场景（日内交易）
    SCREENING = 300     # 筛选场景（策略筛选）
    DASHBOARD = 900     # 仪表盘场景（默认，与原 15 分钟一致）


@dataclass
class ContinuityResult:
    """资金持续性检测结果"""
    is_continuous: bool = False          # 向后兼容：是否所有周期都净流入
    score: float = 0.0                   # 持续性评分 0-100
    trend: str = "unknown"               # accelerating / stable / decelerating / unknown
    periods_count: int = 0               # 实际检测的周期数
    avg_inflow_ratio: float = 0.0        # 平均净流入占比


class CapitalFlowAnalyzer:
    """资金流向分析器"""

    def __init__(self, futu_client=None, db_manager=None, config: dict = None, *, ctx=None):
        """
        初始化资金流向分析器

        Args:
            ctx: AnalysisContext（推荐）
            futu_client: 富途API客户端（向后兼容）
            db_manager: 数据库管理器（向后兼容）
            config: 配置字典（向后兼容）
        """
        if ctx is not None:
            self.futu_client = ctx.futu_client
            self.db_manager = ctx.db_manager
            self.config = ctx.enhanced_heat_config
        else:
            self.futu_client = futu_client
            self.db_manager = db_manager
            self.config = (config or {}).get('enhanced_heat_config', {})
        self.capital_config = self.config.get('capital_flow_config', {})
        self.cache_duration = self.config.get('cache_duration', {}).get('capital_flow', 900)

        # 配置参数
        self.min_net_inflow_ratio = self.capital_config.get('min_net_inflow_ratio', 0.1)
        self.min_big_order_ratio = self.capital_config.get('min_big_order_ratio', 0.5)
        self.continuity_periods = self.capital_config.get('continuity_periods', 2)

    def fetch_capital_flow_data(
        self, stock_codes: List[str],
        use_cache: bool = True,
        cache_ttl: Optional[int] = None,
    ) -> Dict[str, dict]:
        """
        获取多只股票的资金流向数据

        Args:
            stock_codes: 股票代码列表
            use_cache: 是否使用缓存
            cache_ttl: 缓存时效（秒），None 时使用默认值。可传入 CacheTTL 常量

        Returns:
            {stock_code: {资金流向数据}} 字典
        """
        effective_ttl = cache_ttl if cache_ttl is not None else self.cache_duration
        result = {}

        for stock_code in stock_codes:
            # 检查缓存
            if use_cache:
                cached_data = self._get_cached_capital_flow(stock_code, cache_ttl=effective_ttl)
                if cached_data:
                    result[stock_code] = cached_data
                    continue

            # 从富途API获取
            capital_data = self._fetch_from_api(stock_code)
            if capital_data:
                result[stock_code] = capital_data
                # 保存到缓存
                self._save_to_cache(stock_code, capital_data)

        return result

    def _fetch_from_api(self, stock_code: str) -> Optional[dict]:
        """从富途API获取资金分布数据（流入/流出分开）

        使用 get_capital_distribution 接口，返回各级别真实的流入和流出数据。
        """
        try:
            from futu import RET_OK

            ret, data = self.futu_client.get_capital_distribution(stock_code)

            if ret == RET_OK and data is not None and len(data) > 0:
                latest = data.iloc[-1]

                super_large_inflow = safe_float(latest.get('capital_in_super'))
                large_inflow = safe_float(latest.get('capital_in_big'))
                medium_inflow = safe_float(latest.get('capital_in_mid'))
                small_inflow = safe_float(latest.get('capital_in_small'))

                super_large_outflow = safe_float(latest.get('capital_out_super'))
                large_outflow = safe_float(latest.get('capital_out_big'))
                medium_outflow = safe_float(latest.get('capital_out_mid'))
                small_outflow = safe_float(latest.get('capital_out_small'))

                # 主力 = 超大单 + 大单
                main_inflow = super_large_inflow + large_inflow
                main_outflow = super_large_outflow + large_outflow
                main_net_inflow = main_inflow - main_outflow

                total_flow = (super_large_inflow + large_inflow + medium_inflow + small_inflow +
                             super_large_outflow + large_outflow + medium_outflow + small_outflow)
                net_inflow_ratio = main_net_inflow / total_flow if total_flow > 0 else 0

                big_order_buy_ratio = (
                    main_inflow / (main_inflow + main_outflow)
                    if (main_inflow + main_outflow) > 0 else 0
                )

                return {
                    'stock_code': stock_code,
                    'timestamp': datetime.now(),
                    'main_net_inflow': main_net_inflow,
                    'super_large_inflow': super_large_inflow,
                    'large_inflow': large_inflow,
                    'medium_inflow': medium_inflow,
                    'small_inflow': small_inflow,
                    'super_large_outflow': super_large_outflow,
                    'large_outflow': large_outflow,
                    'medium_outflow': medium_outflow,
                    'small_outflow': small_outflow,
                    'net_inflow_ratio': net_inflow_ratio,
                    'big_order_buy_ratio': big_order_buy_ratio,
                    'capital_score': 0.0,
                }
            else:
                logging.warning(f"获取资金分布失败: {stock_code}")
                return None

        except Exception as e:
            logging.error(f"获取资金分布异常: {stock_code}, {e}")
            return None


    def _get_cached_capital_flow(self, stock_code: str, cache_ttl: Optional[int] = None) -> Optional[dict]:
        """从缓存获取资金流向数据"""
        try:
            effective_ttl = cache_ttl if cache_ttl is not None else self.cache_duration
            cache_time_threshold = datetime.now() - timedelta(seconds=effective_ttl)

            rows = self.db_manager.execute_query("""
                SELECT * FROM capital_flow_cache
                WHERE stock_code = ? AND timestamp > ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (stock_code, cache_time_threshold.isoformat()))

            if rows and len(rows) > 0:
                row = rows[0]
                return {
                    'stock_code': row[1],
                    'timestamp': datetime.fromisoformat(row[2]),
                    'main_net_inflow': row[3],
                    'super_large_inflow': row[4],
                    'large_inflow': row[5],
                    'medium_inflow': row[6],
                    'small_inflow': row[7],
                    'super_large_outflow': row[8],
                    'large_outflow': row[9],
                    'medium_outflow': row[10],
                    'small_outflow': row[11],
                    'net_inflow_ratio': row[12],
                    'big_order_buy_ratio': row[13],
                    'capital_score': row[14]
                }

            return None

        except Exception as e:
            logging.error(f"读取资金流向缓存失败: {stock_code}, {e}")
            return None

    def _save_to_cache(self, stock_code: str, capital_data: dict):
        """保存资金流向数据到缓存"""
        try:
            # 计算资金评分
            capital_score = self.calculate_capital_score(capital_data)
            capital_data['capital_score'] = capital_score

            self.db_manager.execute_update("""
                INSERT OR REPLACE INTO capital_flow_cache
                (stock_code, timestamp, main_net_inflow, super_large_inflow, large_inflow,
                 medium_inflow, small_inflow, super_large_outflow, large_outflow,
                 medium_outflow, small_outflow, net_inflow_ratio, big_order_buy_ratio, capital_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                stock_code,
                capital_data['timestamp'].isoformat(),
                capital_data['main_net_inflow'],
                capital_data['super_large_inflow'],
                capital_data['large_inflow'],
                capital_data['medium_inflow'],
                capital_data['small_inflow'],
                capital_data['super_large_outflow'],
                capital_data['large_outflow'],
                capital_data['medium_outflow'],
                capital_data['small_outflow'],
                capital_data['net_inflow_ratio'],
                capital_data['big_order_buy_ratio'],
                capital_score
            ))

        except Exception as e:
            logging.error(f"保存资金流向缓存失败: {stock_code}, {e}")

    def calculate_capital_score(self, capital_data: dict) -> float:
        """
        计算资金评分

        评分公式：
        资金评分 = (主力净流入占比 × 0.5) + (大单买入占比 × 0.3) + (资金持续性 × 0.2)

        Returns:
            0-100的评分
        """
        # 净流入占比评分 (0-50分)
        net_inflow_ratio = capital_data.get('net_inflow_ratio', 0)
        net_inflow_score = min(max(net_inflow_ratio * 100, 0), 50)

        # 大单买入占比评分 (0-30分)
        big_order_ratio = capital_data.get('big_order_buy_ratio', 0)
        big_order_score = min(max((big_order_ratio - 0.5) * 60, 0), 30)

        # 资金持续性评分 (0-20分)
        continuity = self.detect_capital_continuity(capital_data['stock_code'], self.continuity_periods)
        # 持续性评分从 0/20 二值改为 0-20 连续值
        continuity_score = round(continuity.score * 0.2, 2)  # score 0-100 映射到 0-20

        total_score = net_inflow_score + big_order_score + continuity_score

        return round(total_score, 2)

    def detect_capital_continuity(self, stock_code: str, periods: int = 2) -> ContinuityResult:
        """
        检测资金流入持续性

        Args:
            stock_code: 股票代码
            periods: 检查的周期数

        Returns:
            ContinuityResult 持续性检测结果
        """
        result = ContinuityResult()
        try:
            rows = self.db_manager.execute_query("""
                SELECT net_inflow_ratio FROM capital_flow_cache
                WHERE stock_code = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (stock_code, periods))

            if not rows or len(rows) == 0:
                return result

            ratios = [row[0] for row in rows]
            result.periods_count = len(ratios)
            result.avg_inflow_ratio = sum(ratios) / len(ratios) if ratios else 0

            # 向后兼容：所有周期都净流入
            result.is_continuous = all(r > 0 for r in ratios) and len(ratios) >= periods

            # 持续性评分（0-100）
            positive_count = sum(1 for r in ratios if r > 0)
            positive_ratio = positive_count / len(ratios) if ratios else 0
            # 基础分 = 正流入周期占比 × 60
            base_score = positive_ratio * 60
            # 强度分 = 平均流入占比 × 40（上限 40）
            intensity_score = min(max(result.avg_inflow_ratio * 100, 0), 40)
            result.score = round(base_score + intensity_score, 2)

            # 趋势判断：比较最近 vs 最早
            if len(ratios) >= 2:
                # ratios[0] 是最新的，ratios[-1] 是最早的
                recent = ratios[0]
                earliest = ratios[-1]
                if earliest > 0:
                    ratio = recent / earliest
                    if ratio > 1.2:
                        result.trend = "accelerating"
                    elif ratio < 0.8:
                        result.trend = "decelerating"
                    else:
                        result.trend = "stable"
                elif recent > 0:
                    result.trend = "accelerating"
                else:
                    result.trend = "stable"

            return result

        except Exception as e:
            logging.error(f"检测资金持续性失败: {stock_code}, {e}")
            return result

    def get_big_order_strength(self, capital_data: dict) -> float:
        """
        计算大单强度

        Returns:
            0-1的强度值
        """
        big_order_ratio = capital_data.get('big_order_buy_ratio', 0)
        return min(max(big_order_ratio, 0), 1)

    def fetch_capital_flow_history(self, stock_code: str,
                                   start: str = None, end: str = None) -> List[dict]:
        """获取历史每日资金流向（按天粒度）

        Args:
            stock_code: 股票代码
            start: 开始日期 'YYYY-MM-DD'，默认30天前
            end: 结束日期 'YYYY-MM-DD'，默认今天

        Returns:
            按日期排序的资金流向列表
        """
        try:
            from futu import RET_OK
            from datetime import date

            if not end:
                end = date.today().strftime('%Y-%m-%d')
            if not start:
                start = (date.today() - timedelta(days=30)).strftime('%Y-%m-%d')

            ret, data = self.futu_client.get_capital_flow(
                stock_code, period_type='DAY', start=start, end=end
            )

            if ret != RET_OK or data is None or len(data) == 0:
                logging.warning(f"获取历史资金流向失败: {stock_code}")
                return []

            result = []
            for _, row in data.iterrows():
                main_in = safe_float(row.get('main_in_flow'))
                super_in = safe_float(row.get('super_in_flow'))
                big_in = safe_float(row.get('big_in_flow'))
                mid_in = safe_float(row.get('mid_in_flow'))
                sml_in = safe_float(row.get('sml_in_flow'))
                net_inflow = safe_float(row.get('in_flow'))
                flow_time = row.get('capital_flow_item_time', '')

                result.append({
                    'date': flow_time,
                    'net_inflow': net_inflow,
                    'main_net_inflow': main_in,
                    'super_large_net_inflow': super_in,
                    'large_net_inflow': big_in,
                    'medium_net_inflow': mid_in,
                    'small_net_inflow': sml_in,
                })

            return result

        except Exception as e:
            logging.error(f"获取历史资金流向异常: {stock_code}, {e}")
            return []
