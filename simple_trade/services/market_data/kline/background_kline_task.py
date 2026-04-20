#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
后台K线下载任务模块

职责：管理后台K线下载任务的提交和执行，包含额度预检查和快速失败逻辑。
从活跃度筛选流程中解耦，异步执行K线数据补齐。
"""

import time
import logging
from dataclasses import dataclass
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


@dataclass
class KlineDownloadResult:
    """K线下载结果统计"""
    total: int              # 待处理股票总数
    skipped: int            # 已有充足数据跳过的数量
    downloaded: int         # 新下载成功的数量
    failed: int             # 下载失败的数量
    quota_exhausted: bool   # 是否因额度耗尽而提前终止
    skipped_by_quota: int   # 因额度耗尽而跳过的剩余股票数量
    elapsed_seconds: float  # 整个下载过程耗时（秒）
    subscribed_stocks_count: int = 0  # 已占用额度的股票数量
    quota_limited_mode: bool = False  # 是否处于额度受限模式


class BackgroundKlineTask:
    """后台K线下载任务管理器"""

    # 数据充足性判断所需的最少天数
    REQUIRED_DAYS = 12
    # 下载K线数据的天数
    DOWNLOAD_DAYS = 30

    def __init__(self, container):
        """
        Args:
            container: 服务容器（需包含 kline_service）
        """
        self._container = container
        self._executor = ThreadPoolExecutor(max_workers=1)

    def submit(self, stocks: List[Dict[str, Any]]) -> None:
        """提交后台下载任务（非阻塞）

        Args:
            stocks: 筛选后的有潜力股票列表，每个元素需包含 'code' 字段
        """
        if not stocks:
            logger.info("[后台K线] 无待下载股票，跳过")
            return

        try:
            self._executor.submit(self._execute, stocks)
            logger.info(f"[后台K线] 已提交 {len(stocks)} 只股票的下载任务")
        except RuntimeError:
            logger.warning("[后台K线] 线程池已关闭，无法提交任务")

    def _execute(self, stocks: List[Dict[str, Any]]) -> KlineDownloadResult:
        """执行K线下载（在后台线程中运行）

        流程：
        1. 查询额度，额度为零则立即终止
        2. 逐只检查数据充足性，不足则下载
        3. 下载失败且为额度耗尽错误时，立即终止所有后续下载
        4. 记录统计日志
        """
        start_time = time.time()
        kline_service = self._container.kline_service
        request_delay = max(kline_service.config.kline_rate_limit.get("request_delay", 1.0), 3.0)

        total = len(stocks)
        skipped = 0
        downloaded = 0
        failed = 0
        quota_exhausted = False
        skipped_by_quota = 0

        # 步骤1：额度预检查 + 获取已订阅股票列表
        subscribed_stocks = set()  # 已占用额度的股票集合
        quota_limited_mode = False  # 是否处于额度受限模式

        try:
            quota_info = kline_service.get_quota_info(force_refresh=True)
            remaining = quota_info.get('remaining', 0)
            status = quota_info.get('status', 'unknown')

            # 获取已占用额度的股票列表
            quota_detail = kline_service.futu_client.get_kline_quota_detail()
            if quota_detail['success']:
                subscribed_stocks = quota_detail['kline_stocks']
                logger.info(
                    f"[后台K线] 开始下载 {total} 只股票，"
                    f"当前额度: 剩余{remaining}, 状态={status}, "
                    f"已订阅{len(subscribed_stocks)}只"
                )
            else:
                logger.warning(f"[后台K线] 获取已订阅股票列表失败: {quota_detail['message']}")
                logger.info(
                    f"[后台K线] 开始下载 {total} 只股票，"
                    f"当前额度: 剩余{remaining}, 状态={status}"
                )

            # 检查是否需要进入额度受限模式
            if status != 'connected':
                logger.warning(f"[后台K线] API未连接(状态={status})，终止下载")
                elapsed = time.time() - start_time
                return KlineDownloadResult(
                    total=total, skipped=0, downloaded=0, failed=0,
                    quota_exhausted=True, skipped_by_quota=total,
                    elapsed_seconds=round(elapsed, 2),
                    subscribed_stocks_count=len(subscribed_stocks),
                    quota_limited_mode=False
                )

            if remaining <= 0:
                if subscribed_stocks:
                    # 额度受限模式：只处理已订阅的股票
                    quota_limited_mode = True
                    logger.warning(
                        f"[后台K线] 额度受限模式：剩余{remaining}，"
                        f"但有{len(subscribed_stocks)}只已订阅股票可继续下载"
                    )
                else:
                    # 完全无额度，终止
                    logger.warning(f"[后台K线] 额度不足(剩余={remaining})且无已订阅股票，终止下载")
                    elapsed = time.time() - start_time
                    return KlineDownloadResult(
                        total=total, skipped=0, downloaded=0, failed=0,
                        quota_exhausted=True, skipped_by_quota=total,
                        elapsed_seconds=round(elapsed, 2),
                        subscribed_stocks_count=0,
                        quota_limited_mode=False
                    )

        except Exception as e:
            logger.error(f"[后台K线] 额度查询失败: {e}，终止下载")
            elapsed = time.time() - start_time
            return KlineDownloadResult(
                total=total, skipped=0, downloaded=0, failed=0,
                quota_exhausted=False, skipped_by_quota=0,
                elapsed_seconds=round(elapsed, 2),
                subscribed_stocks_count=0,
                quota_limited_mode=False
            )

        # 步骤2：逐只检查并下载
        for i, stock in enumerate(stocks):
            stock_code = stock.get('code', '')
            if not stock_code:
                failed += 1
                logger.warning(f"[后台K线] 第{i+1}只股票缺少code字段，跳过")
                continue

            # 额度受限模式下的额外检查
            is_subscribed = stock_code in subscribed_stocks
            if quota_limited_mode and not is_subscribed:
                skipped_by_quota += 1
                logger.debug(
                    f"[后台K线] {stock_code} (新股票) 额度受限，跳过 "
                    f"({i+1}/{total})"
                )
                continue

            try:
                # 检查数据充足性
                if kline_service.parser.has_enough_kline_data(stock_code, self.REQUIRED_DAYS):
                    skipped += 1
                    logger.debug(f"[后台K线] {stock_code} 数据充足，跳过")
                    continue

                # 数据不足，发起下载
                stock_label = "(已订阅)" if is_subscribed else "(新股票)"
                logger.info(
                    f"[后台K线] {stock_code} {stock_label} 数据不足，"
                    f"开始下载 ({i+1}/{total})"
                )
                kline_data = kline_service.fetcher.fetch_kline_data_with_limit(
                    stock_code, days=self.DOWNLOAD_DAYS, limit_days=self.DOWNLOAD_DAYS
                )

                if kline_data:
                    filtered_data = kline_service.parser.filter_today_incomplete_data(
                        stock_code, kline_data
                    )
                    saved_count = kline_service.storage.save_kline_batch(stock_code, filtered_data)
                    if saved_count > 0:
                        downloaded += 1
                        logger.info(f"[后台K线] {stock_code} 下载完成，保存{saved_count}条记录")
                    else:
                        failed += 1
                        logger.warning(f"[后台K线] {stock_code} 保存失败")
                else:
                    failed += 1
                    logger.warning(f"[后台K线] {stock_code} 下载返回空数据")

                # 遵守请求延迟间隔
                time.sleep(request_delay)

            except Exception as e:
                # 步骤3：额度耗尽快速终止
                if self._is_quota_exhausted_error(e):
                    failed += 1
                    skipped_by_quota = total - (skipped + downloaded + failed)
                    quota_exhausted = True
                    logger.warning(
                        f"[后台K线] {stock_code} 下载时额度耗尽: {e}，"
                        f"终止后续下载，跳过剩余 {skipped_by_quota} 只"
                    )
                    break
                else:
                    failed += 1
                    logger.error(f"[后台K线] {stock_code} 下载异常: {e}")

        # 步骤4：记录统计日志
        elapsed = round(time.time() - start_time, 2)
        result = KlineDownloadResult(
            total=total,
            skipped=skipped,
            downloaded=downloaded,
            failed=failed,
            quota_exhausted=quota_exhausted,
            skipped_by_quota=skipped_by_quota,
            elapsed_seconds=elapsed,
            subscribed_stocks_count=len(subscribed_stocks),
            quota_limited_mode=quota_limited_mode,
        )

        if quota_limited_mode:
            logger.info(
                f"[后台K线] 下载完成(额度受限模式) - 总计:{result.total}, "
                f"已订阅:{result.subscribed_stocks_count}, "
                f"跳过:{result.skipped}, 下载:{result.downloaded}, "
                f"失败:{result.failed}, 跳过新股票:{result.skipped_by_quota}, "
                f"耗时:{result.elapsed_seconds}s"
            )
        else:
            logger.info(
                f"[后台K线] 下载完成 - 总计:{result.total}, "
                f"跳过:{result.skipped}, 下载:{result.downloaded}, "
                f"失败:{result.failed}, 额度耗尽:{result.quota_exhausted}, "
                f"因额度跳过:{result.skipped_by_quota}, 耗时:{result.elapsed_seconds}s"
            )
        return result

    @staticmethod
    def _is_quota_exhausted_error(error: Exception) -> bool:
        """判断异常是否为额度耗尽错误

        通过检查异常消息中的关键词来判断是否为额度耗尽。
        """
        error_msg = str(error).lower()
        quota_keywords = ['quota', '额度', 'limit exceeded', 'rate limit', '超出限制']
        return any(kw in error_msg for kw in quota_keywords)
