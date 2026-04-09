#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
默认数据提供器
提供默认的板块和股票数据，并负责将其保存到��据库
"""

import logging
from typing import Dict, List, Tuple, Any
from ...database.core.db_manager import DatabaseManager


class DefaultDataProvider:
    """
    默认数据提供器

    职责：
    1. 提供默认板块和股票数据
    2. 将默认数据保存到数据库
    """

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def get_default_plates() -> List[Dict]:
        """获取默认板块数据"""
        return [
            {'code': 'BK1027', 'name': '港股科技', 'market': 'HK', 'category': '科技'},
            {'code': 'BK1046', 'name': '港股医药', 'market': 'HK', 'category': '医药'},
            {'code': 'BK1033', 'name': '港股新能源', 'market': 'HK', 'category': '新能源'},
            {'code': 'BK1001', 'name': '中概股', 'market': 'US', 'category': '科网股'},
            {'code': 'BK1002', 'name': '芯片概念', 'market': 'US', 'category': '芯片'}
        ]

    @staticmethod
    def get_default_stocks() -> Dict[str, List[Tuple[str, str]]]:
        """获取默认股票数据"""
        return {
            'BK1027': [('HK.00700', '腾讯控股'), ('HK.00981', '中芯国际'), ('HK.09988', '阿里巴巴-SW')],
            'BK1046': [('HK.01093', '石药集团'), ('HK.01177', '中国生物制药'), ('HK.02269', '药明生物')],
            'BK1033': [('HK.01211', '比亚迪股份'), ('HK.00175', '吉利汽车')],
            'BK1001': [('US.BABA', '阿里巴巴'), ('US.JD', '京东'), ('US.BIDU', '百度')],
            'BK1002': [('US.NVDA', '英伟达'), ('US.AMD', 'AMD'), ('US.TSM', '台积电')]
        }

    def initialize_default_data(self, stock_service) -> Dict[str, Any]:
        """
        使用默认数据初始化数据库

        Args:
            stock_service: 股票初始化服务（用于保存股票和关联）

        Returns:
            Dict: 初始化结果
        """
        result = {
            'success': True,
            'message': '使用默认数据初始化',
            'plates_total': 0,
            'plates_target': 0,
            'stocks_total': 0,
            'stocks_unique': 0,
            'errors': []
        }

        try:
            # 获取默认数据
            default_plates = self.get_default_plates()
            default_stocks = self.get_default_stocks()

            # 保存默认板块
            for plate_data in default_plates:
                self.db_manager.execute_update('''
                    INSERT OR REPLACE INTO plates
                    (plate_code, plate_name, market, category, is_target, priority, match_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    plate_data['code'],
                    plate_data['name'],
                    plate_data['market'],
                    plate_data.get('category', ''),
                    True,
                    100,
                    100
                ))

            result['plates_total'] = len(default_plates)
            result['plates_target'] = len(default_plates)

            # 构建股票和关联数据
            all_stocks = {}
            stock_plate_map = {}

            for plate_code, stocks in default_stocks.items():
                plate_result = self.db_manager.execute_query(
                    'SELECT id FROM plates WHERE plate_code = ?', (plate_code,)
                )
                if not plate_result:
                    continue

                plate_id = plate_result[0][0]

                for stock_code, stock_name in stocks:
                    if stock_code not in all_stocks:
                        market = 'HK' if stock_code.startswith('HK.') else 'US'
                        all_stocks[stock_code] = {'code': stock_code, 'name': stock_name, 'market': market}
                        stock_plate_map[stock_code] = set()

                    stock_plate_map[stock_code].add(plate_id)

            # 保存股票和关联（委托给stock_service）
            stock_service.save_stocks_with_relations(all_stocks, stock_plate_map)

            result['stocks_total'] = sum(len(stocks) for stocks in default_stocks.values())
            result['stocks_unique'] = len(all_stocks)
            result['message'] = f'默认数据初始化完成: {result["plates_target"]}个板块, {result["stocks_unique"]}只股票'

            self.logger.info(result['message'])

        except Exception as e:
            self.logger.error(f"默认数据初始化失败: {e}")
            result.update({
                'success': False,
                'message': f'默认数据初始化失败: {str(e)}'
            })
            result['errors'].append(str(e))

        return result
