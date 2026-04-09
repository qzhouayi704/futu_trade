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
        """标记低活跃度股票到数据库，并实现永久排除机制

        Args:
            stock_codes: 低活跃度股票代码列表
            activity_scores: 股票代码到活跃度评分的映射 {code: score}

        Note:
            - 使用 SQL 的 datetime('now', 'localtime') 确保时间格式与查询时一致
            - 增加 low_activity_count 计数器，连续3次标记后永久排除
            - 保存 activity_score 用于缓存
        """
        if not stock_codes:
            return

        try:
            permanently_excluded_count = 0

            # 使用 SQL 的 datetime('now', 'localtime') 存储本地时间
            # 确保与查询时的 datetime('now', 'localtime', '-N days') 格式一致
            for code in stock_codes:
                # 获取当前的 low_activity_count
                result = self.db_manager.execute_query(
                    'SELECT low_activity_count FROM stocks WHERE code = ?',
                    (code,)
                )

                current_count = result[0][0] if result and result[0][0] is not None else 0
                new_count = current_count + 1

                # 获取活跃度评分
                score = activity_scores.get(code, 0) if activity_scores else 0

                # 更新股票信息
                self.db_manager.execute_update('''
                    UPDATE stocks
                    SET is_low_activity = 1,
                        low_activity_checked_at = datetime('now', 'localtime'),
                        low_activity_count = ?,
                        activity_score = ?,
                        last_activity_check = datetime('now', 'localtime')
                    WHERE code = ?
                ''', (new_count, score, code))

                # 检查是否达到永久排除阈值（连续3次）
                if new_count >= 3:
                    permanently_excluded_count += 1

            # 日志输出
            if permanently_excluded_count > 0:
                self.logger.warning(
                    f"【永久排除】{permanently_excluded_count} 只股票连续3次标记为低活跃度，"
                    f"将被永久排除（需手动清除标记才能重新参与筛选）"
                )

            self.logger.info(
                f"【低活跃度标记】已标记 {len(stock_codes)} 只股票为低活跃度，"
                f"其中 {permanently_excluded_count} 只达到永久排除阈值"
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
                # 清除所有标记
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
                # 清除指定股票的标记
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
