#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K线数据存储服务
负责K线数据的保存、更新和清理
"""

import logging
from datetime import datetime
from typing import Dict, Any, List
from ....database.core.db_manager import DatabaseManager
from ....utils.market_helper import MarketTimeHelper


class KlineStorage:
    """K线数据存储服务"""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    def save_kline_batch(self, stock_code: str, kline_data: List[Dict[str, Any]]) -> int:
        """批量保存K线数据到数据库（去重，使用 executemany）

        Args:
            stock_code: 股票代码
            kline_data: K线数据列表（字典或 KlineData 对象）

        Returns:
            保存的记录数
        """
        if not kline_data:
            return 0

        try:
            params_list = []
            for data in kline_data:
                # 兼容字典和 KlineData 对象
                if hasattr(data, 'time_key'):
                    params_list.append((
                        stock_code, data.time_key,
                        data.open_price, data.close_price, data.high_price, data.low_price,
                        data.volume, data.turnover, data.pe_ratio, data.turnover_rate
                    ))
                else:
                    params_list.append((
                        stock_code, data['time_key'],
                        data['open_price'], data['close_price'], data['high_price'], data['low_price'],
                        data['volume'], data['turnover'], data['pe_ratio'], data['turnover_rate']
                    ))

            result = self.db_manager.execute_many('''
                INSERT OR REPLACE INTO kline_data
                (stock_code, time_key, open_price, close_price, high_price, low_price,
                 volume, turnover, pe_ratio, turnover_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', params_list)

            saved_count = result if result >= 0 else 0
            return saved_count

        except Exception as e:
            logging.error(f"批量保存K线数据失败: {stock_code}, {e}")
            return 0

    def update_stock_pool(self, processed_stocks: List[tuple]) -> Dict[str, Any]:
        """增量更新股票池

        Args:
            processed_stocks: 已处理的股票列表

        Returns:
            更新结果
        """
        result = {
            'new_stocks_added': 0,
            'updated_stocks': 0
        }

        try:
            for stock in processed_stocks:
                stock_id, stock_code, stock_name, market = stock[:4]

                # 检查股票是否已存在
                existing = self.db_manager.execute_query(
                    'SELECT id FROM stocks WHERE code = ?', (stock_code,)
                )

                if not existing:
                    # 新股票，添加到股票池
                    try:
                        self.db_manager.execute_update('''
                            INSERT OR REPLACE INTO stocks (code, name, market)
                            VALUES (?, ?, ?)
                        ''', (stock_code, stock_name or '', market or 'HK'))

                        result['new_stocks_added'] += 1
                        logging.info(f"新增股票到股票池: {stock_code} {stock_name}")

                    except Exception as e:
                        logging.debug(f"添加股票失败: {e}")
                else:
                    # 更新现有股票信息
                    try:
                        self.db_manager.execute_update('''
                            UPDATE stocks SET name = ? WHERE code = ?
                        ''', (stock_name or '', stock_code))

                        result['updated_stocks'] += 1

                    except Exception as e:
                        logging.debug(f"更新股票失败: {e}")

            logging.info(f"股票池增量更新完成: 新增{result['new_stocks_added']}只，更新{result['updated_stocks']}只")

        except Exception as e:
            logging.error(f"增量更新股票池失败: {e}", exc_info=True)

        return result

    def clean_today_incomplete_kline(self) -> Dict[str, Any]:
        """清理今天的不完整K线数据（考虑时差）

        当天的K线数据在收盘前是不完整的，可能会影响策略判断。
        系统启动时应调用此方法清理已存在的当天数据。

        注意：港股和美股的"今天"日期不同，需要分别清理。

        Returns:
            清理结果，包含删除的记录数和日期
        """
        result = {
            'success': False,
            'deleted_count': 0,
            'date': '',
            'message': '',
            'details': []
        }

        total_deleted = 0

        try:
            # 分别清理港股和美股的"今天"数据
            for market in ['HK', 'US']:
                today_str = MarketTimeHelper.get_market_today(market)
                market_prefix = f'{market}.'

                # 统计要删除的记录数（只统计该市场的股票）
                count_result = self.db_manager.execute_query('''
                    SELECT COUNT(*) FROM kline_data
                    WHERE stock_code LIKE ? AND time_key LIKE ?
                ''', (f'{market_prefix}%', f'{today_str}%'))

                count_before = count_result[0][0] if count_result else 0

                if count_before > 0:
                    # 删除该市场今天的K线数据
                    self.db_manager.execute_update('''
                        DELETE FROM kline_data
                        WHERE stock_code LIKE ? AND time_key LIKE ?
                    ''', (f'{market_prefix}%', f'{today_str}%'))

                    total_deleted += count_before
                    result['details'].append(f"{market}({today_str}): {count_before}条")
                    logging.info(f"清理{market}市场今天({today_str})的K线数据: {count_before}条")

            result['deleted_count'] = total_deleted

            if total_deleted == 0:
                result['success'] = True
                result['message'] = "没有需要清理的当天K线数据"
            else:
                result['success'] = True
                result['message'] = f"已清理当天不完整K线数据: {total_deleted}条 ({', '.join(result['details'])})"

            logging.info(result['message'])

        except Exception as e:
            error_msg = f"清理今天K线数据失败: {e}"
            logging.error(error_msg)
            result['message'] = error_msg

        return result

    def clean_incomplete_kline_by_date(self, date_str: str) -> Dict[str, Any]:
        """清理指定日期的K线数据

        Args:
            date_str: 日期字符串，格式 YYYY-MM-DD

        Returns:
            清理结果
        """
        result = {
            'success': False,
            'deleted_count': 0,
            'date': date_str,
            'message': ''
        }

        try:
            # 验证日期格式
            datetime.strptime(date_str, '%Y-%m-%d')

            # 统计要删除的记录数
            count_result = self.db_manager.execute_query('''
                SELECT COUNT(*) FROM kline_data WHERE time_key LIKE ?
            ''', (f'{date_str}%',))

            count_before = count_result[0][0] if count_result else 0

            if count_before == 0:
                result['success'] = True
                result['message'] = f"没有找到日期为{date_str}的K线数据"
                return result

            # 删除指定日期的K线数据
            self.db_manager.execute_update('''
                DELETE FROM kline_data WHERE time_key LIKE ?
            ''', (f'{date_str}%',))

            result.update({
                'success': True,
                'deleted_count': count_before,
                'message': f"已清理{date_str}的K线数据: {count_before}条记录"
            })

            logging.info(result['message'])

        except ValueError:
            result['message'] = f"无效的日期格式: {date_str}，应为 YYYY-MM-DD"
            logging.error(result['message'])
        except Exception as e:
            result['message'] = f"清理K线数据失败: {e}"
            logging.error(result['message'])

        return result

    def delete_kline_by_stock(self, stock_code: str) -> int:
        """删除指定股票的所有K线数据

        Args:
            stock_code: 股票代码

        Returns:
            删除的记录数
        """
        try:
            # 统计要删除的记录数
            count_result = self.db_manager.execute_query('''
                SELECT COUNT(*) FROM kline_data WHERE stock_code = ?
            ''', (stock_code,))

            count_before = count_result[0][0] if count_result else 0

            if count_before > 0:
                # 删除K线数据
                self.db_manager.execute_update('''
                    DELETE FROM kline_data WHERE stock_code = ?
                ''', (stock_code,))

                logging.info(f"删除股票{stock_code}的K线数据: {count_before}条")

            return count_before

        except Exception as e:
            logging.error(f"删除股票{stock_code}的K线数据失败: {e}", exc_info=True)
            return 0

    def get_kline_count(self, stock_code: str = None) -> int:
        """获取K线数据数量

        Args:
            stock_code: 股票代码，如果为None则统计所有股票

        Returns:
            K线数据数量
        """
        try:
            if stock_code:
                result = self.db_manager.execute_query('''
                    SELECT COUNT(*) FROM kline_data WHERE stock_code = ?
                ''', (stock_code,))
            else:
                result = self.db_manager.execute_query('''
                    SELECT COUNT(*) FROM kline_data
                ''')

            return result[0][0] if result else 0

        except Exception as e:
            logging.error(f"获取K线数据数量失败: {e}", exc_info=True)
            return 0
