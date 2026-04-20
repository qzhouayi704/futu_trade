#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
订阅优化管理服务

职责：
1. 订阅列表管理
2. 订阅优先级计算
3. 订阅数量控制
4. 订阅更新策略
"""

import logging
import time
from typing import List, Dict, Any
from ...api.market_types import ReturnCode


class SubscriptionOptimizer:
    """
    订阅优化管理服务

    负责管理订阅流程、优化订阅策略、控制订阅数量
    """

    # 时间配置常量
    SUBSCRIBE_WAIT_SECONDS = 6  # 订阅后等待时间（秒）- 增加到6秒确保订阅生效
    UNSUBSCRIBE_WAIT_SECONDS = 90  # 反订阅前等待时间（秒）
    QUOTE_RETRY_WAIT = 3  # 获取报价重试等待时间（秒）
    MAX_QUOTE_RETRIES = 3  # 获取报价最大重试次数
    MAX_QUOTA = 300  # 富途API订阅额度限制

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
        total_batches = (len(pending_stocks) + self.MAX_QUOTA - 1) // self.MAX_QUOTA

        self.logger.info(
            f"开始分批活跃度筛选: 共 {len(pending_stocks)} 只股票，分 {total_batches} 批处理"
        )

        while pending_stocks:
            batch_num += 1
            batch = pending_stocks[:self.MAX_QUOTA]
            pending_stocks = pending_stocks[self.MAX_QUOTA:]

            self.logger.info("=" * 50)
            self.logger.info(f"批次 {batch_num}/{total_batches}: 处理 {len(batch)} 只股票")

            batch_result = self.process_single_batch(batch, batch_num, filter_callback)

            active_stocks.extend(batch_result['active'])
            inactive_codes.extend(batch_result['inactive'])
            failed_codes.extend(batch_result.get('failed', []))

            self.logger.info(
                f"批次 {batch_num}/{total_batches} 完成: 累计活跃股票 {len(active_stocks)} 只"
            )

            if pending_stocks:
                time.sleep(1)

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
        subscribe_start_time = time.time()

        # 步骤1: 订阅
        subscribe_result = self.subscribe_batch(batch_codes, batch_num)
        if not subscribe_result['success']:
            return {'active': [], 'inactive': [], 'failed': batch_codes}

        # 获取成功订阅的代码，并根据成功订阅的代码过滤原始 batch
        successful_codes = set(subscribe_result['codes'])
        batch_codes = subscribe_result['codes']
        batch = [s for s in batch if s['code'] in successful_codes]

        # 步骤2: 获取报价
        quote_data = self.get_quotes_with_retry(batch_codes, batch_num)
        if quote_data is None:
            self.wait_and_unsubscribe(batch_codes, subscribe_start_time)
            return {'active': [], 'inactive': [], 'failed': batch_codes}

        # 步骤3: 筛选活跃股票（通过回调）
        filter_result = filter_callback(batch, quote_data)

        self.logger.info(
            f"[步骤3] 筛选结果: 活跃 {len(filter_result['active'])} 只, "
            f"不活跃 {len(filter_result['inactive'])} 只"
        )

        # 步骤4: 反订阅不活跃股票
        if filter_result['inactive']:
            self.wait_and_unsubscribe(
                filter_result['inactive'],
                subscribe_start_time
            )

        # 添加 failed 字段（如果回调没有返回）
        if 'failed' not in filter_result:
            filter_result['failed'] = []

        return filter_result

    def subscribe_batch(
        self,
        batch_codes: List[str],
        batch_num: int
    ) -> Dict[str, Any]:
        """订阅批次股票

        Args:
            batch_codes: 股票代码列表
            batch_num: 批次编号

        Returns:
            {'success': bool, 'codes': [...]}
        """
        self.logger.info(f"[步骤1] 订阅 {len(batch_codes)} 只股票...")
        subscribe_result = self.subscription_manager.subscribe(batch_codes)

        if not subscribe_result['success'] and not subscribe_result.get('already_subscribed'):
            self.logger.warning(f"批次{batch_num} 订阅失败: {subscribe_result['message']}")
            return {'success': False, 'codes': []}

        successful_codes = (
            subscribe_result.get('successful_stocks', []) +
            subscribe_result.get('already_subscribed', [])
        )

        self.logger.info(f"[步骤1] 订阅完成: 成功 {len(successful_codes)} 只")

        if subscribe_result.get('failed_stocks'):
            self.logger.warning(
                f"[步骤1] 订阅失败: {len(subscribe_result['failed_stocks'])} 只"
            )

        return {'success': True, 'codes': successful_codes}

    def get_quotes_with_retry(self, batch_codes: List[str], batch_num: int):
        """获取报价（支持重试）

        Args:
            batch_codes: 股票代码列表
            batch_num: 批次编号

        Returns:
            报价数据DataFrame或None
        """
        self.logger.info(f"[步骤2] 等待 {self.SUBSCRIBE_WAIT_SECONDS} 秒让报价数据就绪...")
        time.sleep(self.SUBSCRIBE_WAIT_SECONDS)

        for retry in range(self.MAX_QUOTE_RETRIES):
            self.logger.info(f"[步骤2] 获取报价尝试 {retry + 1}/{self.MAX_QUOTE_RETRIES}...")
            ret, data = self.quote_service.get_stock_quote(batch_codes)

            if ReturnCode.is_ok(ret) and data is not None and not data.empty:
                self.logger.info(f"[步骤2] 成功获取 {len(data)} 只股票的报价")
                # 写入全局报价缓存
                if self.quote_cache:
                    cached = self.quote_cache.bulk_update_from_dataframe(data)
                    self.logger.debug(f"[步骤2] 已缓存 {cached} 只股票报价")
                return data

            self.logger.warning(
                f"[步骤2] 获取报价失败 (尝试 {retry + 1}): ret={ret}, 错误信息: {data}"
            )
            if retry < self.MAX_QUOTE_RETRIES - 1:
                self.logger.info(f"[步骤2] 等待 {self.QUOTE_RETRY_WAIT} 秒后重试...")
                time.sleep(self.QUOTE_RETRY_WAIT)

        self.logger.error(f"批次{batch_num} 获取报价失败，跳过（不标记低活跃）")
        return None

    def wait_and_unsubscribe(
        self,
        stock_codes: List[str],
        subscribe_start_time: float
    ):
        """等待满足时间限制后反订阅

        Args:
            stock_codes: 股票代码列表
            subscribe_start_time: 订阅开始时间戳
        """
        elapsed = time.time() - subscribe_start_time
        remaining_wait = max(0, self.UNSUBSCRIBE_WAIT_SECONDS - elapsed)

        if remaining_wait > 0:
            self.logger.info(
                f"[步骤4] 等待 {remaining_wait:.0f} 秒后反订阅 "
                f"(已过 {elapsed:.0f} 秒，需等满 {self.UNSUBSCRIBE_WAIT_SECONDS} 秒)..."
            )
            time.sleep(remaining_wait)

        self.logger.info(f"[步骤4] 反订阅 {len(stock_codes)} 只股票...")
        self.subscription_manager.unsubscribe(stock_codes)
        self.logger.info(f"[步骤4] 反订阅完成，释放额度")
