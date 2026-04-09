#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票池管理服务
负责股票池的管理操作，包括板块添加/删除、股票添加/删除、状态更新等
"""

import logging
from typing import Dict, Any, List, Optional, Set
from ...database.core.db_manager import DatabaseManager
from ...api.futu_client import FutuClient
from ..market_data.plate.plate_manager import PlateManager


# 默认数据配置
DEFAULT_PLATES = [
    {'code': 'BK1027', 'name': '港股科技', 'market': 'HK', 'category': '科技'},
    {'code': 'BK1046', 'name': '港股医药', 'market': 'HK', 'category': '医药'},
    {'code': 'BK1033', 'name': '港股新能源', 'market': 'HK', 'category': '新能源'},
    {'code': 'BK1001', 'name': '中概股', 'market': 'US', 'category': '科网股'},
    {'code': 'BK1002', 'name': '芯片概念', 'market': 'US', 'category': '芯片'}
]

DEFAULT_STOCKS = {
    'BK1027': [('HK.00700', '腾讯控股'), ('HK.00981', '中芯国际'), ('HK.09988', '阿里巴巴-SW')],
    'BK1046': [('HK.01093', '石药集团'), ('HK.01177', '中国生物制药'), ('HK.02269', '药明生物')],
    'BK1033': [('HK.01211', '比亚迪股份'), ('HK.00175', '吉利汽车')],
    'BK1001': [('US.BABA', '阿里巴巴'), ('US.JD', '京东'), ('US.BIDU', '百度')],
    'BK1002': [('US.NVDA', '英伟达'), ('US.AMD', 'AMD'), ('US.TSM', '台积电')]
}


class StockPoolManagerService:
    """股票池管理服务 - 负责所有管理操作"""

    def __init__(self, db_manager: DatabaseManager, futu_client: FutuClient):
        self.db_manager = db_manager
        self.futu_client = futu_client
        self.plate_manager = PlateManager(db_manager, futu_client)
        self.logger = logging.getLogger(__name__)

    def add_plate(self, plate_code: str) -> Dict[str, Any]:
        """添加板块到股票池"""
        try:
            # 获取板块信息
            plate_info = self.plate_manager.get_plate_info(plate_code) if hasattr(self.plate_manager, 'get_plate_info') else None
            if not plate_info:
                plate_info = {'code': plate_code, 'name': f'板块_{plate_code}', 'market': 'HK'}

            # 保存板块
            self.db_manager.execute_update(
                'INSERT OR REPLACE INTO plates (plate_code, plate_name, market, stock_count, is_target, priority) VALUES (?, ?, ?, ?, ?, ?)',
                (plate_info['code'], plate_info['name'], plate_info['market'], 0, True, 50)
            )

            # 获取板块ID
            plate_result = self.db_manager.execute_query('SELECT id FROM plates WHERE plate_code = ?', (plate_code,))
            if not plate_result:
                return {'success': False, 'message': '保存板块失败'}

            plate_id = plate_result[0][0]

            # 获取并添加板块股票
            stocks = self.plate_manager.get_plate_stocks(plate_code)
            added_count = self._add_stocks_to_plate(stocks, plate_id)

            # 更新板块股票数量
            self.db_manager.execute_update('UPDATE plates SET stock_count = ? WHERE id = ?', (added_count, plate_id))

            return {
                'success': True,
                'message': f'板块 {plate_code} 添加成功，包含 {added_count} 只股票',
                'plate_id': plate_id,
                'stocks_count': added_count
            }

        except Exception as e:
            self.logger.error(f"添加板块失败: {e}")
            return {'success': False, 'message': f'添加板块失败: {str(e)}'}

    def remove_plate(self, plate_id: int) -> Dict[str, Any]:
        """删除板块及其关联"""
        try:
            # 1. 找出将要成为孤儿的股票
            orphan_stocks = self.db_manager.execute_query('''
                SELECT DISTINCT sp.stock_id
                FROM stock_plates sp
                WHERE sp.plate_id = ?
                AND sp.stock_id NOT IN (
                    SELECT stock_id FROM stock_plates WHERE plate_id != ?
                )
                AND sp.stock_id IN (
                    SELECT id FROM stocks WHERE is_manual = 0
                )
            ''', (plate_id, plate_id))

            # 2. 删除这些孤儿股票的交易信号
            if orphan_stocks:
                orphan_ids = [row[0] for row in orphan_stocks]
                placeholders = ','.join('?' * len(orphan_ids))
                self.db_manager.execute_update(
                    f'DELETE FROM trade_signals WHERE stock_id IN ({placeholders})',
                    orphan_ids
                )

            # 3. 删除板块-股票关联
            self.db_manager.execute_update('DELETE FROM stock_plates WHERE plate_id = ?', (plate_id,))

            # 4. 删除板块
            self.db_manager.execute_update('DELETE FROM plates WHERE id = ?', (plate_id,))

            # 5. 删除孤儿股票（排除手动添加的股票）
            self.db_manager.execute_update('''
                DELETE FROM stocks
                WHERE id NOT IN (SELECT DISTINCT stock_id FROM stock_plates)
                AND is_manual = 0
            ''')

            return {'success': True, 'message': '板块删除成功'}
        except Exception as e:
            self.logger.error(f"删除板块失败: {e}")
            return {'success': False, 'message': f'删除板块失败: {str(e)}'}

    def add_stocks(self, stock_codes: List[str], plate_id: int = None) -> Dict[str, Any]:
        """添加股票到指定板块（批量优化版）"""
        try:
            # 确定目标板块
            if plate_id is None:
                plate_result = self.db_manager.execute_query('SELECT id FROM plates WHERE is_target = 1 LIMIT 1')
                if plate_result:
                    plate_id = plate_result[0][0]
                else:
                    return {'success': False, 'message': '没有可用的目标板块'}

            if not stock_codes:
                return {'success': True, 'message': '没有股票需要添加', 'added_count': 0, 'failed_codes': []}

            # 1. 批量获取股票信息
            stock_infos = []
            failed_codes = []
            for stock_code in stock_codes:
                try:
                    stock_info = self._get_stock_info(stock_code)
                    if stock_info:
                        stock_infos.append(stock_info)
                    else:
                        failed_codes.append(stock_code)
                except Exception as e:
                    self.logger.warning(f"获取股票信息失败 {stock_code}: {e}")
                    failed_codes.append(stock_code)

            if not stock_infos:
                return {'success': True, 'message': '没有有效的股票信息', 'added_count': 0, 'failed_codes': failed_codes}

            # 2. 批量插入股票（使用 executemany）
            stock_values = [(info['code'], info['name'], info['market']) for info in stock_infos]
            self.db_manager.execute_many(
                'INSERT OR IGNORE INTO stocks (code, name, market) VALUES (?, ?, ?)',
                stock_values
            )

            # 3. 批量查询股票ID
            codes_str = ','.join(['?' for _ in stock_infos])
            codes_list = [info['code'] for info in stock_infos]
            stock_id_results = self.db_manager.execute_query(
                f'SELECT id, code FROM stocks WHERE code IN ({codes_str})',
                codes_list
            )

            # 4. 批量插入股票-板块关联
            if stock_id_results:
                stock_plate_values = [(row[0], plate_id) for row in stock_id_results]
                self.db_manager.execute_many(
                    'INSERT OR IGNORE INTO stock_plates (stock_id, plate_id) VALUES (?, ?)',
                    stock_plate_values
                )
                added_count = len(stock_id_results)
            else:
                added_count = 0

            # 5. 更新板块股票数量
            self._update_plate_stock_count(plate_id)

            return {
                'success': True,
                'message': f'成功添加 {added_count} 只股票',
                'added_count': added_count,
                'failed_codes': failed_codes
            }

        except Exception as e:
            self.logger.error(f"添加股票失败: {e}")
            return {'success': False, 'message': f'添加股票失败: {str(e)}'}

    def remove_stock(self, stock_id: int) -> Dict[str, Any]:
        """删除股票及其关联"""
        try:
            # 1. 删除交易信号
            self.db_manager.execute_update('DELETE FROM trade_signals WHERE stock_id = ?', (stock_id,))

            # 2. 删除股票-板块关联
            self.db_manager.execute_update('DELETE FROM stock_plates WHERE stock_id = ?', (stock_id,))

            # 3. 删除股票
            self.db_manager.execute_update('DELETE FROM stocks WHERE id = ?', (stock_id,))

            return {'success': True, 'message': '股票删除成功'}
        except Exception as e:
            self.logger.error(f"删除股票失败: {e}")
            return {'success': False, 'message': f'删除股票失败: {str(e)}'}

    def clear_database(self) -> Dict[str, Any]:
        """清空股票池数据库"""
        try:
            self.logger.info("开始清空股票池数据库...")
            # 按正确的顺序删除，避免外键约束错误
            self.db_manager.execute_update('DELETE FROM trade_signals')  # 1. 先删除交易信号
            self.db_manager.execute_update('DELETE FROM stock_plates')   # 2. 再删除关联
            self.db_manager.execute_update('DELETE FROM stocks')         # 3. 然后删除股票
            self.db_manager.execute_update('DELETE FROM plates')         # 4. 最后删除板块
            self.db_manager.execute_update('DELETE FROM plate_match_log')
            self.logger.info("股票池数据库清空完成")
            return {'success': True, 'message': '数据库清空成功'}
        except Exception as e:
            self.logger.error(f"清空股票池数据库失败: {e}")
            return {'success': False, 'message': f'清空数据库失败: {str(e)}'}

    def init_with_default_data(self) -> Dict[str, Any]:
        """使用默认数据初始化股票池

        Returns:
            Dict: 操作结果
        """
        result = {'success': True, 'message': '使用默认数据初始化', 'plates_count': 0, 'stocks_count': 0}

        try:
            all_stocks: Dict[str, Dict[str, Any]] = {}
            stock_plate_map: Dict[str, Set[int]] = {}

            # 保存板块并收集股票信息
            for plate_data in DEFAULT_PLATES:
                self.db_manager.execute_update('''
                    INSERT OR REPLACE INTO plates
                    (plate_code, plate_name, market, category, stock_count, is_target, is_enabled, priority, match_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (plate_data['code'], plate_data['name'], plate_data['market'],
                      plate_data.get('category', ''), 0, 1, 1, 100, 100))

                plate_result = self.db_manager.execute_query(
                    'SELECT id FROM plates WHERE plate_code = ?', (plate_data['code'],)
                )
                if plate_result:
                    plate_id = plate_result[0][0]
                    for stock_code, stock_name in DEFAULT_STOCKS.get(plate_data['code'], []):
                        market = 'HK' if stock_code.startswith('HK.') else 'US'
                        if stock_code not in all_stocks:
                            all_stocks[stock_code] = {'code': stock_code, 'name': stock_name, 'market': market}
                            stock_plate_map[stock_code] = set()
                        stock_plate_map[stock_code].add(plate_id)

            result['plates_count'] = len(DEFAULT_PLATES)

            # 保存股票和关联
            for code, stock_info in all_stocks.items():
                self.db_manager.execute_update(
                    'INSERT OR REPLACE INTO stocks (code, name, market) VALUES (?, ?, ?)',
                    (code, stock_info['name'], stock_info['market'])
                )
                stock_result = self.db_manager.execute_query('SELECT id FROM stocks WHERE code = ?', (code,))
                if stock_result:
                    stock_id = stock_result[0][0]
                    for plate_id in stock_plate_map.get(code, set()):
                        self.db_manager.execute_update(
                            'INSERT OR IGNORE INTO stock_plates (stock_id, plate_id) VALUES (?, ?)',
                            (stock_id, plate_id)
                        )

            result['stocks_count'] = len(all_stocks)

            # 更新板块股票数量
            self.db_manager.execute_update('''
                UPDATE plates SET stock_count = (
                    SELECT COUNT(DISTINCT sp.stock_id) FROM stock_plates sp WHERE sp.plate_id = plates.id
                )
            ''')

            self.logger.info(f"默认数据初始化完成: {result['plates_count']}个板块，{result['stocks_count']}只股票")

        except Exception as e:
            self.logger.error(f"默认数据初始化失败: {e}")
            result.update({'success': False, 'message': f'默认数据初始化失败: {str(e)}'})

        return result

    def _update_plate_stock_count(self, plate_id: int):
        """更新板块的股票数量"""
        try:
            self.db_manager.execute_update(
                'UPDATE plates SET stock_count = (SELECT COUNT(DISTINCT stock_id) FROM stock_plates WHERE plate_id = ?) WHERE id = ?',
                (plate_id, plate_id)
            )
        except Exception as e:
            self.logger.warning(f"更新板块股票数量失败: {e}")

    def _get_stock_info(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """获取股票信息"""
        try:
            market = 'HK' if stock_code.isdigit() or stock_code.startswith('HK.') else 'US'
            return {'code': stock_code, 'name': f'{stock_code}_股票', 'market': market}
        except Exception as e:
            self.logger.warning(f"获取股票 {stock_code} 信息失败: {e}")
            return None

    def _add_stocks_to_plate(self, stocks: List[Dict[str, Any]], plate_id: int) -> int:
        """批量添加股票到板块"""
        added_count = 0
        for stock in stocks:
            try:
                self.db_manager.execute_update(
                    'INSERT OR IGNORE INTO stocks (code, name, market) VALUES (?, ?, ?)',
                    (stock['code'], stock['name'], stock['market'])
                )
                stock_result = self.db_manager.execute_query('SELECT id FROM stocks WHERE code = ?', (stock['code'],))
                if stock_result:
                    stock_id = stock_result[0][0]
                    self.db_manager.execute_update(
                        'INSERT OR IGNORE INTO stock_plates (stock_id, plate_id) VALUES (?, ?)',
                        (stock_id, plate_id)
                    )
                    added_count += 1
            except Exception as e:
                self.logger.warning(f"添加股票 {stock['code']} 失败: {e}")
        return added_count
