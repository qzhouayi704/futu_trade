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
        api_fetched_codes = []

        for stock_code in stock_codes:
            # 检查缓存
            if use_cache:
                cached_data = self._get_cached_capital_flow(stock_code, cache_ttl=effective_ttl)
                if cached_data:
                    result[stock_code] = cached_data
                    continue
                else:
                    logging.info(f"[资金流向] {stock_code}: 缓存未命中，调API")

            # 从API获取
            capital_data = self._fetch_from_api(stock_code)
            if capital_data:
                result[stock_code] = capital_data
                self._save_to_cache(stock_code, capital_data)
                api_fetched_codes.append(stock_code)
            else:
                logging.warning(f"[资金流向] {stock_code}: API返回空")

        # 后台填充日线缓存（不阻塞主流程）
        if api_fetched_codes:
            import threading
            threading.Thread(
                target=self._batch_ensure_daily_cache,
                args=(api_fetched_codes,),
                daemon=True,
            ).start()

        return result

    def _fetch_from_api(self, stock_code: str) -> Optional[dict]:
        """从富途API获取资金分布数据（流入/流出分开）

        使用 get_capital_distribution 接口，返回各级别真实的流入和流出数据。
        """
        try:
            from futu import RET_OK

            logging.info(f"[资金分布API] {stock_code}: 开始调用 get_capital_distribution")
            ret, data = self.futu_client.get_capital_distribution(stock_code)

            if ret == RET_OK and data is not None and len(data) > 0:
                logging.info(f"[资金分布API] {stock_code}: 成功，{len(data)}条数据")
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
        计算资金评分（v2：50 分基准 + 三维偏移）

        评分公式：
        total = 50 + net_flow_offset(±20) + order_structure_offset(±15) + continuity_offset(±15)

        Returns:
            0-100 的评分
        """
        # 维度 1：主力净流入方向 (±20)
        net_inflow_ratio = capital_data.get('net_inflow_ratio', 0)
        net_flow_off = self._net_flow_offset(net_inflow_ratio)

        # 维度 2：大单买入占比 (±15)
        big_order_ratio = capital_data.get('big_order_buy_ratio', 0.5)
        order_off = self._order_structure_offset(big_order_ratio)

        # 维度 3：多日资金持续性 (±15)
        stock_code = capital_data.get('stock_code', '')
        cont_off = self._continuity_offset(stock_code)

        total = 50 + net_flow_off + order_off + cont_off
        score = round(max(0, min(100, total)), 2)
        logging.info(f"[资金评分v2] {stock_code}: flow={net_flow_off:+.1f} order={order_off:+.1f} cont={cont_off:+.1f} => {score}")
        return score

    @staticmethod
    def _net_flow_offset(ratio: float) -> float:
        """净流入占比 -> ±20 偏移（满偏范围 ±0.15）"""
        clamped = max(-0.15, min(0.15, ratio))
        return round(clamped / 0.15 * 20, 2)

    @staticmethod
    def _order_structure_offset(buy_ratio: float) -> float:
        """大单买入占比 -> ±15 偏移（0.30~0.70 映射，0.50 为中性）"""
        clamped = max(0.30, min(0.70, buy_ratio))
        return round((clamped - 0.50) / 0.20 * 15, 2)

    def _continuity_offset(self, stock_code: str) -> float:
        """多日资金持续性 -> ±15 偏移（仅查 DB，不调 API）"""
        if not stock_code:
            return 0.0
        try:
            rows = self.db_manager.execute_query("""
                SELECT net_inflow_ratio FROM capital_flow_daily
                WHERE stock_code = ? ORDER BY date DESC LIMIT 5
            """, (stock_code,))
        except Exception:
            return 0.0
        if not rows or len(rows) < 2:
            return 0.0
        ratios = [r[0] for r in rows]
        positive_count = sum(1 for r in ratios if r > 0)
        positive_pct = positive_count / len(ratios)
        return round((positive_pct - 0.5) * 30, 2)

    def _batch_ensure_daily_cache(self, stock_codes: list) -> None:
        """后台批量填充日线缓存（在独立线程中运行）"""
        for code in stock_codes:
            try:
                self._ensure_daily_cache(code)
            except Exception as e:
                logging.debug(f"[日线缓存] 后台填充 {code} 失败: {e}")

    def _ensure_daily_cache(self, stock_code: str) -> None:
        """确保 capital_flow_daily 有该股票的日线数据，没有则从 API 拉取"""
        # 内存级标记：本次运行已检查过的股票不再重复查询
        if not hasattr(self, '_daily_cache_checked'):
            self._daily_cache_checked = set()
        if stock_code in self._daily_cache_checked:
            return
        self._daily_cache_checked.add(stock_code)
        logging.info(f"[日线缓存] {stock_code}: 首次检查，开始查询...")

        try:
            self.db_manager.execute_update("""
                CREATE TABLE IF NOT EXISTS capital_flow_daily (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code VARCHAR(20) NOT NULL,
                    date DATE NOT NULL,
                    net_inflow DECIMAL(15,2),
                    net_inflow_ratio DECIMAL(5,4),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(stock_code, date)
                )
            """)
            from datetime import date
            today = date.today().strftime('%Y-%m-%d')
            existing = self.db_manager.execute_query(
                "SELECT 1 FROM capital_flow_daily WHERE stock_code = ? AND date = ?",
                (stock_code, today)
            )
            if existing and len(existing) > 0:
                logging.info(f"[日线缓存] {stock_code}: 今日已有缓存，跳过")
                return
            logging.info(f"[日线缓存] {stock_code}: 无今日缓存，调API获取历史...")
            history = self.fetch_capital_flow_history(stock_code)
            if not history:
                logging.info(f"[日线缓存] {stock_code}: API返回空数据")
                return
            logging.info(f"[日线缓存] {stock_code}: 获取到{len(history)}条日线数据")
            for day in history:
                flow_date = str(day.get('date', ''))[:10]
                net_inflow = day.get('net_inflow', 0) or day.get('main_net_inflow', 0)
                total_abs = abs(net_inflow) * 2 if net_inflow != 0 else 1
                ratio = net_inflow / total_abs if total_abs > 0 else 0
                if flow_date:
                    try:
                        self.db_manager.execute_update("""
                            INSERT OR IGNORE INTO capital_flow_daily
                            (stock_code, date, net_inflow, net_inflow_ratio)
                            VALUES (?, ?, ?, ?)
                        """, (stock_code, flow_date, net_inflow, ratio))
                    except Exception:
                        pass
        except Exception as e:
            logging.warning(f"[日线缓存] {stock_code}: 失败 - {e}")

    def detect_capital_continuity(self, stock_code: str, periods: int = 5) -> ContinuityResult:
        """
        检测资金流入持续性（使用日线级数据）

        Args:
            stock_code: 股票代码
            periods: 检查的交易日数

        Returns:
            ContinuityResult 持续性检测结果
        """
        result = ContinuityResult()
        try:
            rows = self.db_manager.execute_query("""
                SELECT net_inflow_ratio FROM capital_flow_daily
                WHERE stock_code = ?
                ORDER BY date DESC LIMIT ?
            """, (stock_code, periods))

            if not rows or len(rows) == 0:
                return result

            ratios = [r[0] for r in rows]
            result.periods_count = len(ratios)
            result.avg_inflow_ratio = sum(ratios) / len(ratios) if ratios else 0
            result.is_continuous = all(r > 0 for r in ratios) and len(ratios) >= periods

            positive_count = sum(1 for r in ratios if r > 0)
            positive_ratio = positive_count / len(ratios) if ratios else 0
            base_score = positive_ratio * 60
            intensity_score = min(max(result.avg_inflow_ratio * 100, 0), 40)
            result.score = round(base_score + intensity_score, 2)

            if len(ratios) >= 2:
                recent = ratios[0]
                earliest = ratios[-1]
                if earliest > 0:
                    r = recent / earliest
                    if r > 1.2:
                        result.trend = "accelerating"
                    elif r < 0.8:
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

            logging.info(f"[日线历史API] {stock_code}: 开始调用 get_capital_flow {start}~{end}")
            ret, data = self.futu_client.get_capital_flow(
                stock_code, period_type='DAY', start=start, end=end
            )

            if ret != RET_OK or data is None or len(data) == 0:
                logging.warning(f"[日线历史] {stock_code}: API返回失败 ret={ret}")
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
