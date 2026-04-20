#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
活跃度筛选服务 - 协调器

职责：
1. 协调活跃度计算和订阅优化
2. 提供统一的筛选接口（含截断 / 不截断两种模式）
3. 管理子服务生命周期
"""

import logging
from typing import List, Dict, Any, Tuple, NamedTuple
from ..realtime.activity_calculator import ActivityCalculator
from ..realtime.subscription_optimizer import SubscriptionOptimizer


class _FilterStats(NamedTuple):
    """活跃度筛选过程中的统计数据"""
    priority_count: int
    cached_active_count: int
    batch_active_count: int
    batch_inactive_count: int


class ActivityFilterService:
    """
    活跃度筛选服务 - 协调器

    负责协调活跃度计算和订阅优化，提供统一的筛选接口
    """

    def __init__(self, subscription_manager, quote_service, config=None, db_manager=None, container=None, quote_cache=None):
        """
        初始化活跃度筛选服务

        Args:
            subscription_manager: 订阅管理器
            quote_service: 报价服务
            config: 配置对象
            db_manager: 数据库管理器（用于缓存）
            container: 服务容器（保留以便向后兼容）
            quote_cache: 全局报价缓存（可选）
        """
        self.logger = logging.getLogger(__name__)

        # 初始化子服务
        self.calculator = ActivityCalculator(config=config, db_manager=db_manager)
        self.optimizer = SubscriptionOptimizer(
            subscription_manager=subscription_manager,
            quote_service=quote_service,
            quote_cache=quote_cache
        )

        # 保留引用以便向后兼容
        self.subscription_manager = subscription_manager
        self.quote_service = quote_service
        self.config = config
        self.db_manager = db_manager
        self.container = container

    def _do_activity_filter(
        self,
        stocks: List[Dict[str, Any]],
        activity_config: Dict[str, Any],
        priority_stocks: List[str] = None
    ) -> Tuple[List[Dict[str, Any]], _FilterStats]:
        """核心活跃度筛选逻辑（不含市场限制截断）

        处理优先股票、缓存检查、分批实时筛选，返回全部活跃股票和统计数据。

        Args:
            stocks: 股票列表
            activity_config: 活跃度筛选配置
            priority_stocks: 优先股票列表（持仓等）

        Returns:
            (active_stocks, filter_stats) 元组
        """
        active_stocks = []

        # 获取筛选配置 - 支持按市场区分
        min_turnover_rate_config = activity_config.get('min_turnover_rate', 1.0)
        min_turnover_amount = activity_config.get('min_turnover_amount', 5000000)
        min_volume_config = activity_config.get('min_volume', self.calculator.get_min_volume())
        min_price_config = self.calculator.get_min_price_config()

        self._log_filter_params(min_turnover_rate_config, min_turnover_amount, min_volume_config)

        # 处理优先股票
        pending_stocks, priority_added = self.calculator.handle_priority_stocks(
            stocks, priority_stocks
        )
        active_stocks.extend(priority_added)

        if priority_added:
            self.logger.info(
                f"【优先股票】已添加 {len(priority_added)} 只优先股票，"
                f"剩余 {len(pending_stocks)} 只待筛选"
            )

        # 检查缓存（1小时内的活跃度数据）
        cached_stocks, uncached_stocks = self.calculator.check_activity_cache(pending_stocks)
        if cached_stocks:
            self.logger.info(
                f"【缓存命中】{len(cached_stocks)} 只股票使用缓存的活跃度数据，跳过实时筛选"
            )
            active_stocks.extend(cached_stocks)

        self.logger.info(
            f"【筛选进度】优先股票: {len(priority_added)}只, "
            f"缓存命中: {len(cached_stocks)}只, 待实时筛选: {len(uncached_stocks)}只"
        )

        # 分批处理未缓存的股票
        batch_active_count = 0
        batch_inactive_count = 0
        if uncached_stocks:
            def filter_callback(batch, quote_data):
                return self.calculator.filter_stocks_by_activity(
                    batch, quote_data,
                    min_turnover_rate_config, min_turnover_amount,
                    min_volume_config, min_price_config
                )

            batch_results = self.optimizer.process_batches(uncached_stocks, filter_callback)
            active_stocks.extend(batch_results['active'])
            batch_active_count = len(batch_results['active'])
            batch_inactive_count = len(batch_results['inactive'])

            # 处理检查失败的股票
            failed_codes = batch_results.get('failed', [])
            if failed_codes:
                self.logger.warning(f"【检查失败】{len(failed_codes)} 只股票检查失败，标记为失败状态")
                for code in failed_codes:
                    market = 'HK' if code.startswith('HK.') else 'US' if code.startswith('US.') else 'HK'
                    self.calculator.save_activity_cache(
                        code=code,
                        activity_score=-1,
                        market=market,
                        is_active=False,
                        check_failed=True
                    )

            self.logger.info(
                f"【实时筛选】完成，活跃: {batch_active_count}只, "
                f"不活跃: {batch_inactive_count}只, 失败: {len(failed_codes)}只"
            )

        stats = _FilterStats(
            priority_count=len(priority_added),
            cached_active_count=len(cached_stocks),
            batch_active_count=batch_active_count,
            batch_inactive_count=batch_inactive_count
        )
        return active_stocks, stats

    def filter_by_realtime_activity(
        self,
        stocks: List[Dict[str, Any]],
        market_limits: Dict[str, int],
        activity_config: Dict[str, Any],
        priority_stocks: List[str] = None
    ) -> List[Dict[str, Any]]:
        """基于实时报价的当日活跃度筛选（含市场限制截断）

        流程：优先股票 → 缓存检查 → 分批实时筛选 → 市场限制截断

        Args:
            stocks: 股票列表
            market_limits: 按市场的数量限制 {'HK': 100, 'US': 100}
            activity_config: 活跃度筛选配置
            priority_stocks: 优先股票列表（持仓等）

        Returns:
            筛选后的股票列表（已应用市场限制截断）
        """
        try:
            active_stocks, stats = self._do_activity_filter(stocks, activity_config, priority_stocks)

            # 应用市场限制
            filtered_stocks = self.calculator.apply_market_limits(active_stocks, market_limits)

            # 输出筛选统计日志（含市场限制信息）
            self._log_filter_statistics(stocks, filtered_stocks, market_limits, stats)

            return filtered_stocks

        except Exception as e:
            self.logger.error(f"活跃度筛选失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return self.calculator.apply_market_limits(stocks, market_limits)

    def filter_active_stocks(
        self,
        stocks: List[Dict[str, Any]],
        activity_config: Dict[str, Any],
        priority_stocks: List[str] = None
    ) -> List[Dict[str, Any]]:
        """活跃度筛选（不应用市场限制截断）

        返回所有通过活跃度条件的股票，供 Pipeline 后续处理。
        与 filter_by_realtime_activity() 的区别：不调用 apply_market_limits()。

        Args:
            stocks: 股票列表
            activity_config: 活跃度筛选配置
            priority_stocks: 优先股票列表（持仓等）

        Returns:
            全部活跃股票列表（未截断）
        """
        try:
            active_stocks, stats = self._do_activity_filter(stocks, activity_config, priority_stocks)

            # 记录各市场的活跃股票总数（不含市场限制统计）
            market_counts: Dict[str, int] = {}
            for stock in active_stocks:
                code = stock.get('code', '')
                market = 'HK' if code.startswith('HK.') else 'US' if code.startswith('US.') else 'OTHER'
                market_counts[market] = market_counts.get(market, 0) + 1

            self.logger.info(
                f"【活跃度筛选(不截断)】总计: {len(stocks)}只, 活跃: {len(active_stocks)}只 "
                f"(优先: {stats.priority_count}, 缓存: {stats.cached_active_count}, "
                f"实时活跃: {stats.batch_active_count}, 实时不活跃: {stats.batch_inactive_count})"
            )
            for market in sorted(market_counts):
                self.logger.info(f"【活跃度筛选-{market}】活跃: {market_counts[market]}只")

            return active_stocks

        except Exception as e:
            self.logger.error(f"活跃度筛选(不截断)失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return stocks

    def _log_filter_params(self, min_turnover_rate_config, min_turnover_amount, min_volume_config):
        """记录筛选参数日志"""
        if isinstance(min_turnover_rate_config, dict):
            self.logger.info(
                f"活跃度筛选参数（按市场）: "
                f"换手率=US:{min_turnover_rate_config.get('US', 0.5)}%/HK:{min_turnover_rate_config.get('HK', 0.1)}%, "
                f"成交额={min_turnover_amount}, "
                f"成交量=US:{min_volume_config.get('US', 3000000) if isinstance(min_volume_config, dict) else min_volume_config}/"
                f"HK:{min_volume_config.get('HK', 500000) if isinstance(min_volume_config, dict) else min_volume_config}"
            )
        else:
            self.logger.info(
                f"活跃度筛选参数: 最低换手率={min_turnover_rate_config}%, "
                f"最低成交额={min_turnover_amount}, 最低成交量={min_volume_config}"
            )

    def _log_filter_statistics(
        self,
        total_stocks: List[Dict[str, Any]],
        active_stocks: List[Dict[str, Any]],
        market_limits: Dict[str, int],
        stats: '_FilterStats'
    ) -> None:
        """输出筛选统计信息（含市场限制）"""
        total = len(total_stocks)
        active = len(active_stocks)
        checked = stats.priority_count + stats.cached_active_count + stats.batch_active_count + stats.batch_inactive_count
        unchecked = total - checked

        self.logger.info(
            f"【筛选统计】总计: {total}只, 已检查: {checked}只, "
            f"活跃: {active}只, 不活跃: {stats.batch_inactive_count}只, "
            f"未检查: {unchecked}只 "
            f"(优先: {stats.priority_count}, 缓存命中: {stats.cached_active_count}, "
            f"实时活跃: {stats.batch_active_count}, 实时不活跃: {stats.batch_inactive_count})"
        )

        # 按市场分组统计
        market_active: Dict[str, int] = {}
        market_total: Dict[str, int] = {}

        for stock in total_stocks:
            code = stock.get('code', '')
            market = 'HK' if code.startswith('HK.') else 'US' if code.startswith('US.') else 'OTHER'
            market_total[market] = market_total.get(market, 0) + 1

        for stock in active_stocks:
            code = stock.get('code', '')
            market = 'HK' if code.startswith('HK.') else 'US' if code.startswith('US.') else 'OTHER'
            market_active[market] = market_active.get(market, 0) + 1

        for market in sorted(set(list(market_total.keys()) + list(market_active.keys()))):
            m_total = market_total.get(market, 0)
            m_active = market_active.get(market, 0)
            m_limit = market_limits.get(market, 0)
            self.logger.info(
                f"【筛选统计-{market}】总计: {m_total}只, "
                f"活跃: {m_active}只, 市场限制: {m_limit}只"
            )

            if m_limit > 0 and m_active < m_limit * 0.2:
                self.logger.warning(
                    f"【筛选警告-{market}】活跃股票数({m_active})低于市场限制的20%"
                    f"({m_limit}×20%={int(m_limit * 0.2)})，"
                    f"可能需要调整筛选参数"
                )
