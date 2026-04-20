#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
活跃度计算核心服务

职责：
1. 活跃度计算逻辑
2. 筛选条件判断
3. 活跃股票识别
4. 筛选结果生成
"""

import logging
from datetime import datetime
from typing import List, Dict, Any


class ActivityCalculator:
    """
    活跃度计算核心服务

    负责计算股票活跃度、应用筛选条件、生成筛选结果
    """

    def __init__(self, config=None, db_manager=None):
        """
        初始化活跃度计算器

        Args:
            config: 配置对象
            db_manager: 数据库管理器（用于缓存）
        """
        self.config = config
        self.db_manager = db_manager
        self.logger = logging.getLogger(__name__)

        # 延迟创建 StockMarkerService
        self._stock_marker = None
        if db_manager:
            from ..core.stock_marker import StockMarkerService
            self._stock_marker = StockMarkerService(db_manager=db_manager)

    def get_min_volume(self):
        """获取最低成交量配置（支持按市场区分）

        Returns:
            int 或 dict: 如果配置了按市场区分，返回字典 {'US': 3000000, 'HK': 500000}
                        否则返回单一数值
        """
        if self.config:
            # 优先从 realtime_activity_filter 读取
            activity_config = getattr(self.config, 'realtime_activity_filter', {})
            min_volume = activity_config.get('min_volume')
            if min_volume is not None:
                return min_volume

            # 回退到 realtime_hot_filter
            realtime_hot_config = getattr(self.config, 'realtime_hot_filter', {})
            return realtime_hot_config.get('min_volume', 100000)
        return 100000

    def get_min_price_config(self) -> Dict[str, float]:
        """获取最低价格配置"""
        if self.config:
            return getattr(self.config, 'min_stock_price', {})
        return {}

    def handle_priority_stocks(
        self,
        stocks: List[Dict[str, Any]],
        priority_stocks: List[str]
    ) -> tuple:
        """处理优先股票（持仓等），直接加入活跃列表

        Args:
            stocks: 所有股票列表
            priority_stocks: 优先股票代码列表

        Returns:
            (剩余股票列表, 优先股票列表)
        """
        if not priority_stocks:
            return stocks, []

        priority_codes = set(priority_stocks)
        remaining_stocks = []
        priority_added = []

        for stock in stocks:
            if stock['code'] in priority_codes:
                stock_with_priority = dict(stock)
                stock_with_priority['is_priority'] = True
                stock_with_priority['activity_score'] = 1.0
                priority_added.append(stock_with_priority)
                self.logger.info(
                    f"【优先订阅】跳过活跃度筛选: {stock['code']} ({stock.get('name', '')})"
                )
            else:
                remaining_stocks.append(stock)

        if priority_added:
            self.logger.info(
                f"【优先订阅】直接加入 {len(priority_added)} 只优先股票，跳过活跃度筛选"
            )

        return remaining_stocks, priority_added

    def check_activity_cache(
        self,
        stocks: List[Dict[str, Any]],
        cache_minutes: int = 30
    ) -> tuple:
        """检查当天活跃度缓存，返回缓存命中和未命中的股票

        使用 daily_active_stocks 表存储当天的活跃度筛选结果，
        仅返回 cache_minutes 分钟内的未过期缓存记录，过期记录需重新筛选。

        Args:
            stocks: 股票列表
            cache_minutes: 缓存过期时间（分钟），默认 30 分钟

        Returns:
            (缓存命中的活跃股票列表, 需要重新筛选的股票列表)
        """
        if not self.db_manager:
            return [], stocks

        cached_active = []
        uncached = []

        try:
            today = datetime.now().strftime('%Y-%m-%d')
            checked_stocks = self.db_manager.stock_activity_queries.get_daily_checked_stocks_with_expiry(today, cache_minutes)

            if not checked_stocks:
                # 当天没有任何缓存，全部需要检查
                self.logger.info(f"当天无活跃度缓存，需筛选 {len(stocks)} 只股票")
                return [], stocks

            cached_inactive_count = 0
            check_failed_count = 0
            for stock in stocks:
                code = stock['code']
                if code in checked_stocks:
                    info = checked_stocks[code]
                    if info['activity_score'] == -1:
                        # 检查失败，需要重新检查
                        check_failed_count += 1
                        uncached.append(stock)
                    elif info['is_active']:
                        stock_with_cache = dict(stock)
                        stock_with_cache['from_cache'] = True
                        stock_with_cache['activity_score'] = info['activity_score']
                        cached_active.append(stock_with_cache)
                    else:
                        # 不活跃股票，跳过
                        cached_inactive_count += 1
                else:
                    uncached.append(stock)

            self.logger.info(
                f"活跃度缓存(过期{cache_minutes}分钟): 活跃{len(cached_active)}只, "
                f"不活跃{cached_inactive_count}只, "
                f"检查失败{check_failed_count}只, 待检查{len(uncached)}只"
            )

        except Exception as e:
            self.logger.error(f"检查活跃度缓存失败: {e}")
            return [], stocks

        return cached_active, uncached

    def filter_stocks_by_activity(
        self,
        batch: List[Dict[str, Any]],
        quote_data,
        min_turnover_rate,
        min_turnover_amount: float,
        min_volume,
        min_price_config: Dict[str, float]
    ) -> Dict[str, List]:
        """根据报价数据筛选活跃股票

        Args:
            batch: 股票列表
            quote_data: 报价数据DataFrame
            min_turnover_rate: 最低换手率（可以是数字或字典 {'US': 0.5, 'HK': 0.1}）
            min_turnover_amount: 最低成交额
            min_volume: 最低成交量（可以是数字或字典 {'US': 3000000, 'HK': 500000}）
            min_price_config: 最低价格配置

        Returns:
            {'active': [...], 'inactive': [...]}
        """
        self.logger.info(
            f"[步骤3] 筛选活跃股票, 批次股票数: {len(batch)}, "
            f"报价数据行数: {len(quote_data) if quote_data is not None else 0}"
        )

        # 构建报价映射
        quote_map = {}
        for _, row in quote_data.iterrows():
            code = row.get('code', '')
            if code:
                quote_map[code] = {
                    'turnover_rate': float(row.get('turnover_rate', 0) or 0),
                    'turnover': float(row.get('turnover', 0) or 0),
                    'volume': int(row.get('volume', 0) or 0),
                    'last_price': float(row.get('last_price', 0) or 0)
                }

        # 筛选
        active = []
        inactive = []
        filtered_low_price = 0
        filtered_low_turnover_rate = 0
        filtered_low_turnover_amount = 0

        for stock in batch:
            code = stock['code']
            market = stock.get('market', 'HK')
            quote = quote_map.get(code, {})
            turnover_rate = quote.get('turnover_rate', 0)
            turnover = quote.get('turnover', 0)
            volume = quote.get('volume', 0)

            # 检查低价股
            if self.is_low_price_stock(code, quote.get('last_price', 0), min_price_config):
                inactive.append(code)
                filtered_low_price += 1
                # 保存不活跃结果到缓存
                self.save_activity_cache(code, 0, market, False, turnover_rate, turnover)
                continue

            # 检查活跃度 - 根据市场获取对应的阈值
            market_turnover_rate = min_turnover_rate.get(market, 0.1) if isinstance(min_turnover_rate, dict) else min_turnover_rate
            market_min_volume = min_volume.get(market, 500000) if isinstance(min_volume, dict) else min_volume

            if self.is_active_stock(quote, market_turnover_rate, min_turnover_amount, market_min_volume):
                stock_with_activity = dict(stock)
                stock_with_activity.update(quote)
                activity_score = self.calculate_activity_score(quote)
                stock_with_activity['activity_score'] = activity_score
                active.append(stock_with_activity)

                # 保存活跃结果到缓存
                self.save_activity_cache(code, activity_score, market, True, turnover_rate, turnover)
            else:
                inactive.append(code)
                # 统计筛选原因
                if turnover_rate < market_turnover_rate:
                    filtered_low_turnover_rate += 1
                if turnover < min_turnover_amount:
                    filtered_low_turnover_amount += 1
                # 保存不活跃结果到缓存
                self.save_activity_cache(code, 0, market, False, turnover_rate, turnover)

        # 构建详细的筛选结果消息
        total = len(batch)
        active_pct = len(active) * 100 // total if total > 0 else 0
        inactive_pct = len(inactive) * 100 // total if total > 0 else 0

        msg = f"活跃 {len(active)} 只 ({active_pct}%), 不活跃 {len(inactive)} 只 ({inactive_pct}%)"

        # 添加筛选原因统计
        filter_reasons = []
        if filtered_low_price > 0:
            filter_reasons.append(f"低价股 {filtered_low_price}只")
        if filtered_low_turnover_rate > 0:
            filter_reasons.append(f"换手率不足 {filtered_low_turnover_rate}只")
        if filtered_low_turnover_amount > 0:
            filter_reasons.append(f"成交额不足 {filtered_low_turnover_amount}只")

        if filter_reasons:
            msg += f" [筛选原因: {', '.join(filter_reasons)}]"

        self.logger.info(f"[步骤3] 筛选结果: {msg}")

        return {'active': active, 'inactive': inactive}

    def is_low_price_stock(
        self,
        code: str,
        last_price: float,
        min_price_config: Dict[str, float]
    ) -> bool:
        """检查是否为低价股

        Args:
            code: 股票代码
            last_price: 最新价格
            min_price_config: 最低价格配置

        Returns:
            是否为低价股
        """
        if not min_price_config or last_price <= 0:
            return False

        market = 'HK' if code.startswith('HK.') else 'US' if code.startswith('US.') else ''
        min_price = min_price_config.get(market, 0)

        return min_price > 0 and last_price < min_price

    def is_active_stock(
        self,
        quote: Dict[str, Any],
        min_turnover_rate: float,
        min_turnover_amount: float,
        min_volume: int
    ) -> bool:
        """检查股票是否活跃 - 必须同时满足所有条件

        Args:
            quote: 报价数据
            min_turnover_rate: 最低换手率
            min_turnover_amount: 最低成交额
            min_volume: 最低成交量

        Returns:
            是否活跃
        """
        volume = quote.get('volume', 0)
        turnover_rate = quote.get('turnover_rate', 0)
        turnover = quote.get('turnover', 0)

        # 必须同时满足三个条件：成交量、换手率、成交额
        return (volume >= min_volume and
                turnover_rate >= min_turnover_rate and
                turnover >= min_turnover_amount)

    def calculate_activity_score(self, quote: Dict[str, Any]) -> float:
        """计算活跃度分数

        Args:
            quote: 报价数据

        Returns:
            活跃度分数 (0-1)
        """
        turnover_rate = quote.get('turnover_rate', 0)
        turnover = quote.get('turnover', 0)

        turnover_rate_score = min(turnover_rate / 5.0, 1.0)
        turnover_amount_score = min(turnover / 50000000, 1.0)

        return turnover_rate_score * 0.6 + turnover_amount_score * 0.4

    def save_activity_cache(
        self,
        code: str,
        activity_score: float,
        market: str = None,
        is_active: bool = True,
        turnover_rate: float = 0,
        turnover_amount: float = 0,
        check_failed: bool = False
    ):
        """保存活跃度检查结果到数据库

        Args:
            code: 股票代码
            activity_score: 活跃度评分
            market: 市场代码
            is_active: 是否活跃
            turnover_rate: 换手率
            turnover_amount: 成交额
            check_failed: 是否检查失败，True 时强制设置 is_active=False, activity_score=-1
        """
        if not self.db_manager:
            return

        # 检查失败时，强制标记为失败状态
        if check_failed:
            is_active = False
            activity_score = -1
            self.logger.debug(f"股票 {code} 活跃度检查失败，标记为检查失败状态 (activity_score=-1)")

        try:
            today = datetime.now().strftime('%Y-%m-%d')
            # 从股票代码推断市场
            if not market:
                market = 'HK' if code.startswith('HK.') else 'US' if code.startswith('US.') else 'HK'

            self.db_manager.stock_activity_queries.save_daily_activity_result(
                check_date=today,
                stock_code=code,
                market=market,
                is_active=is_active,
                activity_score=activity_score,
                turnover_rate=turnover_rate,
                turnover_amount=turnover_amount
            )

            # 同步更新 stocks 表的 is_low_activity 标记
            # 活跃 → 清除标记（恢复活跃的股票不应继续被排除）
            # 不活跃 → 写入标记（供跨天优化使用）
            if self._stock_marker and not check_failed:
                if is_active:
                    self._stock_marker.clear_low_activity_mark([code])
                else:
                    self._stock_marker.mark_low_activity_stocks(
                        [code], {code: activity_score}
                    )
        except Exception as e:
            self.logger.debug(f"保存活跃度缓存失败 {code}: {e}")

    def apply_market_limits(
        self,
        stocks: List[Dict[str, Any]],
        market_limits: Dict[str, int]
    ) -> List[Dict[str, Any]]:
        """按市场限制股票数量并排序

        Args:
            stocks: 股票列表
            market_limits: 市场限制 {'HK': 100, 'US': 100}

        Returns:
            限制后的股票列表
        """
        # 按市场分组
        market_stocks = {}
        for stock in stocks:
            market = stock.get('market', 'Unknown')
            if market not in market_stocks:
                market_stocks[market] = []
            market_stocks[market].append(stock)

        # 按活跃度排序并限制数量
        filtered_stocks = []
        for market, stocks_list in market_stocks.items():
            # 自选股优先，然后按活跃度排序
            stocks_list.sort(
                key=lambda x: (
                    1 if x.get('is_manual') else 0,
                    x.get('activity_score', 0)
                ),
                reverse=True
            )

            # 应用市场数量限制
            limit = market_limits.get(market, 100)
            limited_stocks = stocks_list[:limit]
            filtered_stocks.extend(limited_stocks)

            self.logger.info(
                f"市场 {market}: 活跃股票 {len(stocks_list)} 只，限制后 {len(limited_stocks)} 只"
            )

            # 记录活跃度前5名
            if limited_stocks:
                top5 = limited_stocks[:5]
                # 检查是否有 activity_score 字段（活跃度筛选后才有）
                if top5[0].get('activity_score') is not None:
                    top5_info = ', '.join([
                        f"{s['name']}({s.get('activity_score', 0):.2f})"
                        for s in top5
                    ])
                    self.logger.info(f"  活跃度前5: {top5_info}")
                else:
                    # 没有活跃度分数时，只显示名称
                    top5_info = ', '.join([s['name'] for s in top5])
                    self.logger.info(f"  前5只股票: {top5_info}")

        return filtered_stocks
