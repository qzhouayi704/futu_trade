#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
无效股票检测器模块

从 SubscriptionValidator 提取的通用无效股票检测服务，
可被 StockHeatCalculator 和 API 层 SubscriptionOptimizer 共享使用。

职责：
- 错误消息分类（OTC / 未知股票）
- 批量检测无效股票
- 从数据库清理无效股票
"""

import logging
import time
from typing import List, Tuple

from ...utils.rate_limiter import wait_for_api
from ...utils.retry_helper import parse_error_type, ErrorType

try:
    from futu import RET_OK
    FUTU_AVAILABLE = True
except ImportError:
    FUTU_AVAILABLE = False
    RET_OK = None


class InvalidStockDetector:
    """无效股票检测器 - 通用服务

    合并 OTC 股票和未知股票的检测逻辑，提供统一的检测与清理接口。
    """

    OTC_KEYWORDS = ['OTC', '暂不提供美股 OTC 市场行情', 'OTC市场', 'OTC股票']
    UNKNOWN_KEYWORDS = ['未知股票', 'unknown stock', '无效股票', 'invalid stock']

    def __init__(self, futu_client, db_manager=None):
        """
        初始化检测器

        Args:
            futu_client: 富途客户端实例（需要有 client.get_market_snapshot 方法）
            db_manager: 数据库管理器实例（可选，用于清理无效股票）
        """
        self.futu_client = futu_client
        self.db_manager = db_manager
        self.logger = logging.getLogger(__name__)

    def is_invalid_stock_error(self, error_msg: str) -> bool:
        """判断错误消息是否由无效股票引起（合并 OTC + 未知股票检测）

        Args:
            error_msg: API 返回的错误消息字符串

        Returns:
            True 表示错误由无效股票引起
        """
        if not error_msg:
            return False

        error_lower = error_msg.lower()
        all_keywords = self.OTC_KEYWORDS + self.UNKNOWN_KEYWORDS

        return any(kw.lower() in error_lower for kw in all_keywords)

    def detect_invalid_stocks(self, stock_codes: List[str]) -> Tuple[List[str], List[str]]:
        """从一组股票中检测无效股票（二分法，减少 API 调用次数）

        使用二分法将列表不断对半拆分，快速定位无效股票。
        相比逐只检测（N 次调用），二分法通常只需 O(K * log(N/K)) 次调用（K 为无效股票数）。

        Args:
            stock_codes: 待检测的股票代码列表

        Returns:
            (invalid_stocks, valid_stocks): 无效股票列表和有效股票列表
        """
        if not stock_codes:
            return [], []

        self.logger.info(f"开始二分法检测 {len(stock_codes)} 只股票中的无效股票...")

        invalid_stocks = []
        valid_stocks = []
        self._bisect_detect(stock_codes, invalid_stocks, valid_stocks)

        self.logger.info(
            f"检测完成: 无效 {len(invalid_stocks)} 只, 有效 {len(valid_stocks)} 只"
        )
        return invalid_stocks, valid_stocks

    def _bisect_detect(
        self,
        codes: List[str],
        invalid_out: List[str],
        valid_out: List[str]
    ) -> None:
        """递归二分检测无效股票

        对一组股票调用批量 API：
        - 成功 → 全部有效
        - 失败且是无效股票错误 → 对半拆分继续检测
        - 失败且是频率限制 → 等待后重试
        - 其他错误 → 全部归入有效（保守策略）
        """
        if not codes:
            return

        # 单只股票直接检测
        if len(codes) == 1:
            self._check_single_stock(codes[0], invalid_out, valid_out)
            return

        # 批量检测
        wait_for_api('market_snapshot')
        try:
            ret, data = self.futu_client.client.get_market_snapshot(codes)

            if ret == RET_OK:
                # 整批成功，全部有效
                valid_out.extend(codes)
                return

            error_msg = data if isinstance(data, str) else str(data)

            # 频率限制：等待后重试整批
            error_type = parse_error_type(error_msg)
            if error_type == ErrorType.RATE_LIMIT:
                self.logger.warning(f"无效股票检测触发频率限制，等待 30 秒后重试")
                time.sleep(30)
                wait_for_api('market_snapshot')
                ret2, data2 = self.futu_client.client.get_market_snapshot(codes)
                if ret2 == RET_OK:
                    valid_out.extend(codes)
                    return
                error_msg = data2 if isinstance(data2, str) else str(data2)
                if not self.is_invalid_stock_error(error_msg):
                    # 仍然不是无效股票错误，保守归入有效
                    valid_out.extend(codes)
                    return

            # 非无效股票错误，保守归入有效
            if not self.is_invalid_stock_error(error_msg):
                valid_out.extend(codes)
                return

        except Exception as e:
            self.logger.error(f"批量检测异常: {e}")
            valid_out.extend(codes)
            return

        # 无效股票错误 → 二分继续查找
        mid = len(codes) // 2
        self._bisect_detect(codes[:mid], invalid_out, valid_out)
        self._bisect_detect(codes[mid:], invalid_out, valid_out)

    def _check_single_stock(
        self,
        code: str,
        invalid_out: List[str],
        valid_out: List[str]
    ) -> None:
        """检测单只股票是否无效"""
        wait_for_api('market_snapshot')
        try:
            ret, data = self.futu_client.client.get_market_snapshot([code])
            if ret != RET_OK:
                error_msg = data if isinstance(data, str) else str(data)
                if self.is_invalid_stock_error(error_msg):
                    invalid_out.append(code)
                    self.logger.warning(f"检测到无效股票: {code} - {error_msg}")
                    return
            valid_out.append(code)
        except Exception as e:
            self.logger.error(f"检测股票 {code} 时异常: {e}")
            valid_out.append(code)

    def remove_invalid_stocks(self, invalid_stocks: List[str]) -> None:
        """从数据库移除无效股票

        Args:
            invalid_stocks: 无效股票代码列表
        """
        if not invalid_stocks or not self.db_manager:
            return

        try:
            placeholders = ','.join(['?' for _ in invalid_stocks])
            delete_sql = f"DELETE FROM stocks WHERE code IN ({placeholders})"

            self.db_manager.execute_update(delete_sql, invalid_stocks)
            self.logger.info(
                f"已从数据库移除 {len(invalid_stocks)} 只无效股票: "
                f"{', '.join(invalid_stocks[:5])}"
                f"{'...' if len(invalid_stocks) > 5 else ''}"
            )
        except Exception as e:
            self.logger.error(f"从数据库移除无效股票失败: {e}")
