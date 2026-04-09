#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
订阅优化器模块

负责批处理、额度优化和重试逻辑
"""

import logging
import time
from typing import List, Dict, Any

try:
    from futu import SubType, RET_OK
    FUTU_AVAILABLE = True
except ImportError:
    FUTU_AVAILABLE = False
    SubType = None
    RET_OK = None


class SubscriptionOptimizer:
    """订阅优化器 - 负责批处理和额度优化"""

    BATCH_SIZE = 300  # 富途API单批订阅上限
    SINGLE_RETRY_DELAY = 0.1  # 单股重试延时(秒)
    BATCH_DELAY = 0.5  # 批次间延时(秒)

    def __init__(self, futu_client, validator):
        """
        初始化优化器

        Args:
            futu_client: 富途客户端实例
            validator: 订阅验证器实例
        """
        self._futu_client = futu_client
        self._validator = validator
        self.logger = logging.getLogger(__name__)

    def process_batches(self, stocks: List[str], result: Dict):
        """分批处理订阅"""
        total_batches = (len(stocks) + self.BATCH_SIZE - 1) // self.BATCH_SIZE
        self.logger.debug(f"开始分批订阅 {len(stocks)} 只股票，分 {total_batches} 批")

        for i in range(0, len(stocks), self.BATCH_SIZE):
            batch = stocks[i:i + self.BATCH_SIZE]
            batch_num = i // self.BATCH_SIZE + 1

            self.subscribe_batch(batch, batch_num, total_batches, result)

            # 批次间延时
            if i + self.BATCH_SIZE < len(stocks):
                time.sleep(self.BATCH_DELAY)

        # 批次处理完成后输出摘要
        if result['successful_stocks']:
            self.logger.info(f"批量订阅完成: 成功 {len(result['successful_stocks'])} 只，失败 {len(result['failed_stocks'])} 只")

    def subscribe_batch(self, batch: List[str], batch_num: int,
                        total_batches: int, result: Dict):
        """订阅单个批次"""
        try:
            self.logger.debug(f"订阅第 {batch_num}/{total_batches} 批: {len(batch)} 只")

            ret, err_msg = self._futu_client.client.subscribe(
                batch, [SubType.QUOTE]
            )

            if ret == RET_OK:
                result['successful_stocks'].extend(batch)
                # 成功的批次不输出日志，减少噪音
            else:
                # 检查是否是订阅额度不足
                if self._validator.is_quota_error(err_msg):
                    self._handle_quota_error(batch, err_msg, result)
                    return  # 额度不足时停止处理后续批次

                # 批次失败，检查是否是无效股票错误（OTC或未知股票）
                if self._validator.is_invalid_stock_error(err_msg):
                    self._handle_invalid_stock_error(batch, batch_num, result)
                else:
                    # 非无效股票错误，直接单股重试
                    self.logger.warning(f"第 {batch_num} 批订阅失败: {err_msg}，尝试单股重试")
                    self.retry_single_stocks(batch, result)

        except Exception as e:
            result['failed_stocks'].extend(batch)
            result['errors'].append(f"第 {batch_num} 批订阅异常: {e}")
            self.logger.error(f"第 {batch_num} 批订阅异常: {e}")

    def _handle_quota_error(self, batch: List[str], err_msg: str, result: Dict):
        """处理订阅额度不足错误"""
        remaining_quota = self._validator.get_remaining_quota(err_msg)

        if remaining_quota > 0:
            # 有剩余额度，使用剩余额度订阅部分股票
            self.logger.warning(
                f"订阅额度不足，但还有 {remaining_quota} 个额度，"
                f"从 {len(batch)} 只股票中选择订阅"
            )

            # 尝试订阅剩余额度允许的股票数
            stocks_to_subscribe = batch[:remaining_quota]
            stocks_to_defer = batch[remaining_quota:]

            # 订阅可以用额度的股票
            ret2, err_msg2 = self._futu_client.client.subscribe(
                stocks_to_subscribe, [SubType.QUOTE]
            )

            if ret2 == RET_OK:
                result['successful_stocks'].extend(stocks_to_subscribe)
                self.logger.info(f"使用剩余额度订阅了 {len(stocks_to_subscribe)} 只")
            else:
                # 即使有剩余额度，单次也可能失败，尝试单股订阅
                self.logger.warning(f"使用剩余额度批量订阅失败，尝试单股订阅")
                self.retry_single_stocks(stocks_to_subscribe, result)

            # 延迟股票加到结果中
            result['deferred_stocks'] = result.get('deferred_stocks', [])
            result['deferred_stocks'].extend(stocks_to_defer)
            self.logger.info(f"暂存 {len(stocks_to_defer)} 只股票待后续订阅")
        else:
            # 额度已完全耗尽
            result['failed_stocks'].extend(batch)
            result['errors'].append(f"订阅额度已完全耗尽: {err_msg}")
            self.logger.error(f"订阅额度已完全耗尽: {err_msg}")

    def _handle_invalid_stock_error(self, batch: List[str], batch_num: int, result: Dict):
        """处理无效股票错误"""
        self.logger.warning(f"第 {batch_num} 批包含无效股票，开始快速检测...")

        # 快速检测无效股票
        invalid_stocks, valid_stocks = self._validator.detect_invalid_stocks(batch)

        # 从数据库移除无效股票
        if invalid_stocks:
            self._validator.remove_invalid_stocks_from_db(invalid_stocks)
            result['otc_stocks'].extend(invalid_stocks)

        # 批量重订阅剩余有效股票
        if valid_stocks:
            self._retry_valid_stocks(valid_stocks, result)

    def _retry_valid_stocks(self, valid_stocks: List[str], result: Dict):
        """重新订阅有效股票"""
        self.logger.info(f"重新批量订阅 {len(valid_stocks)} 只有效股票...")
        ret2, err_msg2 = self._futu_client.client.subscribe(
            valid_stocks, [SubType.QUOTE]
        )

        if ret2 == RET_OK:
            result['successful_stocks'].extend(valid_stocks)
            self.logger.info(f"批量重订阅成功: {len(valid_stocks)} 只")
        else:
            # 检查重试时是否也遇到额度不足
            if self._validator.is_quota_error(err_msg2):
                self._handle_retry_quota_error(valid_stocks, err_msg2, result)
                return

            # 如果批量重订阅还失败，才逐个重试
            self.logger.warning(f"批量重订阅失败: {err_msg2}，尝试单股重试")
            self.retry_single_stocks(valid_stocks, result)

    def _handle_retry_quota_error(self, valid_stocks: List[str], err_msg: str, result: Dict):
        """处理重试时的额度不足错误"""
        remaining_quota = self._validator.get_remaining_quota(err_msg)
        if remaining_quota > 0:
            # 还有剩余额度
            stocks_to_sub = valid_stocks[:remaining_quota]
            stocks_to_defer = valid_stocks[remaining_quota:]
            ret3, err_msg3 = self._futu_client.client.subscribe(
                stocks_to_sub, [SubType.QUOTE]
            )
            if ret3 == RET_OK:
                result['successful_stocks'].extend(stocks_to_sub)
                self.logger.info(f"使用剩余额度订阅 {len(stocks_to_sub)} 只")
            else:
                self.retry_single_stocks(stocks_to_sub, result)

            result['deferred_stocks'] = result.get('deferred_stocks', [])
            result['deferred_stocks'].extend(stocks_to_defer)
        else:
            result['failed_stocks'].extend(valid_stocks)
            result['errors'].append(f"重试时订阅额度已耗尽: {err_msg}")
            self.logger.error(f"重试时订阅额度已耗尽: {err_msg}")

    def retry_single_stocks(self, stocks: List[str], result: Dict):
        """单股重试订阅，检测并删除无效股票"""
        for stock_code in stocks:
            try:
                time.sleep(self.SINGLE_RETRY_DELAY)

                ret, err_msg = self._futu_client.client.subscribe(
                    [stock_code], [SubType.QUOTE]
                )

                if ret == RET_OK:
                    result['successful_stocks'].append(stock_code)
                else:
                    # 检查是否是订阅额度不足
                    if self._validator.is_quota_error(err_msg):
                        result['failed_stocks'].append(stock_code)
                        result['errors'].append(f"订阅额度不足: {err_msg}")
                        self.logger.error(f"单股订阅时额度已不足: {stock_code} - {err_msg}")
                        break  # 停止单股重试

                    # 检查是否是无效股票错误
                    if self._validator.is_invalid_stock_error(err_msg):
                        self.logger.warning(f"检测到无效股票: {stock_code} - {err_msg}")
                        self._validator.remove_invalid_stocks_from_db([stock_code])
                        result['otc_stocks'].append(stock_code)
                    else:
                        result['failed_stocks'].append(stock_code)
                        self.logger.warning(f"单股订阅失败: {stock_code} - {err_msg}")

            except Exception as e:
                result['failed_stocks'].append(stock_code)
                self.logger.warning(f"单股订阅异常: {stock_code} - {e}")
