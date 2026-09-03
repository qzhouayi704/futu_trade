#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
市场快照活跃度筛选服务

职责：
使用无需预订阅的市场快照完成全市场活跃度初筛，避免发现阶段占用
QUOTE/TICKER 共享额度。只有筛选后的目标股票才进入实时订阅流程。
"""

import logging
from typing import List, Dict, Any
from ...api.market_types import ReturnCode


class SubscriptionOptimizer:
    """
    分批获取市场快照并执行活跃度筛选。
    """

    # 时间配置常量
    MAX_SNAPSHOT_BATCH = 300

    def __init__(self, subscription_manager, quote_service, quote_cache=None):
        """
        初始化订阅优化器

        Args:
            subscription_manager: 订阅管理器
            quote_service: 报价服务
            quote_cache: 全局报价缓存（可选）
        """
        self.subscription_manager = subscription_manager
        self.quote_service = quote_service
        self.quote_cache = quote_cache
        self.logger = logging.getLogger(__name__)

    def process_batches(
        self,
        stocks: List[Dict[str, Any]],
        filter_callback
    ) -> Dict[str, List]:
        """分批处理股票筛选

        Args:
            stocks: 股票列表
            filter_callback: 筛选回调函数，接收(batch, quote_data)返回{'active': [...], 'inactive': [...]}

        Returns:
            {'active': [...], 'inactive': [...], 'failed': [...]}
        """
        pending_stocks = list(stocks)
        active_stocks = []
        inactive_codes = []
        failed_codes = []
        batch_num = 0
        total_batches = (
            len(pending_stocks) + self.MAX_SNAPSHOT_BATCH - 1
        ) // self.MAX_SNAPSHOT_BATCH

        self.logger.info(
            f"开始分批活跃度筛选: 共 {len(pending_stocks)} 只股票，分 {total_batches} 批处理"
        )

        while pending_stocks:
            batch_num += 1
            batch = pending_stocks[:self.MAX_SNAPSHOT_BATCH]
            pending_stocks = pending_stocks[self.MAX_SNAPSHOT_BATCH:]

            self.logger.info("=" * 50)
            self.logger.info(f"批次 {batch_num}/{total_batches}: 处理 {len(batch)} 只股票")

            batch_result = self.process_single_batch(batch, batch_num, filter_callback)

            active_stocks.extend(batch_result['active'])
            inactive_codes.extend(batch_result['inactive'])
            failed_codes.extend(batch_result.get('failed', []))

            self.logger.info(
                f"批次 {batch_num}/{total_batches} 完成: 累计活跃股票 {len(active_stocks)} 只"
            )

        self.logger.info("=" * 50)
        self.logger.info(
            f"活跃度筛选完成: 共处理 {batch_num} 批，筛选出 {len(active_stocks)} 只活跃股票，"
            f"{len(failed_codes)} 只检查失败"
        )

        return {'active': active_stocks, 'inactive': inactive_codes, 'failed': failed_codes}

    def process_single_batch(
        self,
        batch: List[Dict[str, Any]],
        batch_num: int,
        filter_callback
    ) -> Dict[str, List]:
        """处理单个批次的股票筛选

        Args:
            batch: 股票批次
            batch_num: 批次编号
            filter_callback: 筛选回调函数

        Returns:
            {'active': [...], 'inactive': [...], 'failed': [...]}
        """
        batch_codes = [s['code'] for s in batch]
        ret, quote_data = self.quote_service.get_market_snapshot(batch_codes)
        if not ReturnCode.is_ok(ret) or quote_data is None or quote_data.empty:
            self.logger.warning(
                "批次%s市场快照失败，跳过且不标记为低活跃: %s",
                batch_num,
                quote_data,
            )
            return {'active': [], 'inactive': [], 'failed': batch_codes}

        if self.quote_cache:
            cached = self.quote_cache.bulk_update_from_dataframe(quote_data)
            self.logger.debug("批次%s已缓存%s只股票快照", batch_num, cached)

        filter_result = filter_callback(batch, quote_data)

        self.logger.info(
            f"市场快照筛选结果: 活跃 {len(filter_result['active'])} 只, "
            f"不活跃 {len(filter_result['inactive'])} 只"
        )

        # 添加 failed 字段（如果回调没有返回）
        if 'failed' not in filter_result:
            filter_result['failed'] = []

        return filter_result
