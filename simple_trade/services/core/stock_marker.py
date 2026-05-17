#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票标记服务

职责：
1. 标记 OTC 股票
2. 标记低活跃度股票
3. 清除低活跃度标记
"""

import logging
from typing import List


class StockMarkerService:
    """
    股票标记服务

    负责标记 OTC 股票和低活跃度股票到数据库
    """

    # 低活跃度排除阈值：连续 N 次标记为低活跃后临时排除
    # （可通过 recheck_days 过期后自动恢复，通过活跃度检查时 count 衰减）
    LOW_ACTIVITY_THRESHOLD = 5

    def __init__(self, db_manager):
        """
        初始化股票标记服务

        Args:
            db_manager: 数据库管理器
        """
        self.db_manager = db_manager
        self.logger = logging.getLogger(__name__)

    def mark_otc_stocks(self, stock_codes: List[str]) -> int:
        """标记 OTC 股票到数据库，下次启动时自动排除

        Args:
            stock_codes: OTC 股票代码列表

        Returns:
            int: 标记成功的股票数量
        """
        if not stock_codes:
            return 0

        marked_count = 0

        try:
            for code in stock_codes:
                try:
                    # 更新 OTC 标记
                    result = self.db_manager.execute_update('''
                        UPDATE stocks SET is_otc = 1 WHERE code = ?
                    ''', (code,))

                    if result > 0:
                        marked_count += 1
                        self.logger.info(f"标记 OTC 股票: {code}")
                    else:
                        self.logger.debug(f"未找到股票记录: {code}")

                except Exception as e:
                    self.logger.error(f"标记单只 OTC 股票失败 {code}: {e}")
                    continue

            if marked_count > 0:
                self.logger.info(
                    f"OTC 股票标记完成: 成功标记 {marked_count} 只，下次启动将自动排除"
                )

        except Exception as e:
            self.logger.error(f"标记 OTC 股票失败: {e}")

        return marked_count

    def mark_low_activity_stocks(self, stock_codes: List[str], activity_scores: dict = None):
        """标记低活跃度股票到数据库

        Args:
            stock_codes: 低活跃度股票代码列表
            activity_scores: 股票代码到活跃度评分的映射 {code: score}

        Note:
            - 增加 low_activity_count 计数器，达到阈值后临时排除
            - 已达阈值的股票不再递增，等待 recheck_days 过期后自动恢复
        """
        if not stock_codes:
            return

        try:
            threshold_reached_count = 0
            already_excluded_count = 0

            for code in stock_codes:
                result = self.db_manager.execute_query(
                    'SELECT low_activity_count FROM stocks WHERE code = ?',
                    (code,)
                )

                current_count = result[0][0] if result and result[0][0] is not None else 0

                # 已达排除阈值的股票，跳过，不再递增
                if current_count >= self.LOW_ACTIVITY_THRESHOLD:
                    already_excluded_count += 1
                    continue

                new_count = current_count + 1
                score = activity_scores.get(code, 0) if activity_scores else 0

                self.db_manager.execute_update('''
                    UPDATE stocks
                    SET is_low_activity = 1,
                        low_activity_checked_at = datetime('now', 'localtime'),
                        low_activity_count = ?,
                        activity_score = ?,
                        last_activity_check = datetime('now', 'localtime')
                    WHERE code = ?
                ''', (new_count, score, code))

                if new_count == self.LOW_ACTIVITY_THRESHOLD:
                    threshold_reached_count += 1

            if threshold_reached_count > 0:
                self.logger.debug(
                    f"【低活跃排除】{threshold_reached_count} 只股票连续{self.LOW_ACTIVITY_THRESHOLD}次"
                    f"标记为低活跃度，将被临时排除（recheck_days 过期后自动恢复）"
                )

            self.logger.debug(
                f"【低活跃度标记】标记 {len(stock_codes)} 只，"
                f"新达阈值 {threshold_reached_count} 只，"
                f"已排除跳过 {already_excluded_count} 只"
            )

        except Exception as e:
            self.logger.error(f"标记低活跃度股票失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())

    def clear_low_activity_mark(self, stock_codes: List[str] = None, reset_count: bool = True):
        """清除低活跃度标记（用于活跃股票或重检过期的股票）

        Args:
            stock_codes: 要清除标记的股票代码列表，为 None 时清除所有
            reset_count: 是否重置 low_activity_count 计数器（默认True）
        """
        try:
            if stock_codes is None:
                if reset_count:
                    self.db_manager.execute_update('''
                        UPDATE stocks
                        SET is_low_activity = 0,
                            low_activity_checked_at = NULL,
                            low_activity_count = 0
                    ''')
                else:
                    self.db_manager.execute_update('''
                        UPDATE stocks
                        SET is_low_activity = 0,
                            low_activity_checked_at = NULL
                    ''')
                self.logger.info("已清除所有低活跃度标记")
            else:
                for code in stock_codes:
                    if reset_count:
                        self.db_manager.execute_update('''
                            UPDATE stocks
                            SET is_low_activity = 0,
                                low_activity_checked_at = NULL,
                                low_activity_count = 0
                            WHERE code = ?
                        ''', (code,))
                    else:
                        self.db_manager.execute_update('''
                            UPDATE stocks
                            SET is_low_activity = 0,
                                low_activity_checked_at = NULL
                            WHERE code = ?
                        ''', (code,))
                self.logger.info(f"清除 {len(stock_codes)} 只股票的低活跃度标记")

        except Exception as e:
            self.logger.error(f"清除低活跃度标记失败: {e}")

    def decrement_low_activity_count(self, stock_codes: List[str]):
        """衰减低活跃度计数（股票通过活跃度检查时调用）

        每次通过活跃度检查时 count-1（最低为0），实现渐进恢复。
        同时清除 is_low_activity 标记。

        Args:
            stock_codes: 通过活跃度检查的股票代码列表
        """
        if not stock_codes:
            return

        try:
            for code in stock_codes:
                self.db_manager.execute_update('''
                    UPDATE stocks
                    SET is_low_activity = 0,
                        low_activity_checked_at = NULL,
                        low_activity_count = MAX(0, COALESCE(low_activity_count, 0) - 1),
                        last_activity_check = datetime('now', 'localtime')
                    WHERE code = ?
                ''', (code,))
        except Exception as e:
            self.logger.error(f"衰减低活跃度计数失败: {e}")
