#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
订阅验证器模块

负责订阅相关的错误检测（额度检查等），
无效股票检测逻辑委托给 InvalidStockDetector。
"""

import logging
import re
from typing import List, Optional, Tuple

class SubscriptionValidator:
    """订阅验证器 - 负责订阅错误检测和无效股票处理

    无效股票检测逻辑委托给 InvalidStockDetector，
    保留订阅特有的额度检查逻辑。
    """

    def __init__(self, futu_client, db_manager=None):
        """
        初始化验证器

        Args:
            futu_client: 富途客户端实例
            db_manager: 数据库管理器实例
        """
        # 延迟导入，避免 api → services → api 循环依赖
        from simple_trade.services.market_data.invalid_stock_detector import InvalidStockDetector

        self._futu_client = futu_client
        self._db_manager = db_manager
        self._detector = InvalidStockDetector(futu_client, db_manager)
        self.logger = logging.getLogger(__name__)

    # ---- 委托给 InvalidStockDetector 的方法（保持向后兼容） ----

    def is_otc_error(self, error_msg: str) -> bool:
        """检查是否是OTC股票错误（委托给 detector）"""
        return self._detector.is_invalid_stock_error(error_msg)

    def is_unknown_stock_error(self, error_msg: str) -> bool:
        """检查是否是未知股票错误（委托给 detector）"""
        return self._detector.is_invalid_stock_error(error_msg)

    def is_invalid_stock_error(self, error_msg: str) -> bool:
        """检查是否是无效股票错误（OTC或未知股票）"""
        return self._detector.is_invalid_stock_error(error_msg)

    def detect_invalid_stocks(self, stock_codes: List[str]) -> tuple:
        """快速检测无效股票（OTC 或未知股票）

        Args:
            stock_codes: 股票代码列表

        Returns:
            (invalid_stocks, valid_stocks): 无效股票列表和有效股票列表
        """
        return self._detector.detect_invalid_stocks(stock_codes)

    def remove_invalid_stocks_from_db(self, invalid_stocks: List[str]) -> None:
        """从数据库移除无效股票（OTC或未知股票）

        Args:
            invalid_stocks: 无效股票代码列表
        """
        self._detector.remove_invalid_stocks(invalid_stocks)

    # ---- 订阅特有的逻辑（保留不变） ----

    def is_quota_error(self, error_msg: str) -> bool:
        """检查是否是订阅额度不足错误"""
        if not error_msg:
            return False

        quota_keywords = ['订阅额度不足', 'quota insufficient', '已达上限', 'quota limit']
        error_lower = error_msg.lower()

        return any(kw.lower() in error_lower for kw in quota_keywords)

    def parse_quota_info(self, error_msg: str) -> Optional[Tuple[int, int]]:
        """
        从错误消息中解析额度信息

        例如: "已用订阅额度：125/300" -> (125, 300)

        Returns:
            (used_quota, total_quota) 或 None 如果无法解析
        """
        if not error_msg:
            return None

        # 尝试匹配 "已用订阅额度：125/300" 格式
        match = re.search(r'已用订阅额度[：:]\s*(\d+)/(\d+)', error_msg)
        if match:
            used, total = int(match.group(1)), int(match.group(2))
            return used, total

        # 尝试匹配 "quota: 125/300" 格式
        match = re.search(r'quota[：:]\s*(\d+)/(\d+)', error_msg, re.IGNORECASE)
        if match:
            used, total = int(match.group(1)), int(match.group(2))
            return used, total

        return None

    def get_remaining_quota(self, error_msg: str) -> int:
        """
        从错误消息中计算剩余额度

        Returns:
            剩余额度数量，0 表示无法解析或已满
        """
        quota_info = self.parse_quota_info(error_msg)
        if quota_info is None:
            return 0

        used, total = quota_info
        remaining = total - used
        self.logger.debug(f"额度解析: 已用 {used}/{total}，剩余 {remaining}")
        return max(0, remaining)
