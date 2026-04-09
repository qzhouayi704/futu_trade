#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
板块数据获取模块

负责从数据库、富途API或默认配置获取板块列表数据。
从 plate_manager.py 拆分而来。
"""

import logging
import time
from typing import Dict, Any, List

from ....database.core.db_manager import DatabaseManager
from ....api.futu_client import FutuClient
from ....api.market_types import MarketType, ReturnCode
from ....utils.field_mapper import FieldMapper
from ....utils.plate_matcher import get_plate_matcher, PlateMatcher
from ....core.models import Plate


class PlateFetcher:
    """
    板块数据获取器

    职责：
    1. 从数据库获取目标板块列表
    2. 从富途API获取板块数据并通过智能匹配器筛选
    3. 提供默认板块数据作为兜底
    4. 按类别查询板块
    """

    API_REQUEST_DELAY = 0.1

    def __init__(self, db_manager: DatabaseManager, futu_client: FutuClient):
        self.db_manager = db_manager
        self.futu_client = futu_client
        self.plate_matcher = get_plate_matcher()
        self.logger = logging.getLogger(__name__)

    def get_target_plates(self, from_db: bool = True) -> Dict[str, Any]:
        """
        获取目标板块列表

        Args:
            from_db: 是否优先从数据库获取

        Returns:
            Dict: 包含板块列表的结果
        """
        result = {
            'success': False,
            'message': '',
            'plates': [],
            'source': 'unknown',
            'total_count': 0,
            'errors': []
        }

        try:
            if from_db:
                db_plates = self._get_plates_from_db()
                if db_plates:
                    result.update({
                        'success': True,
                        'message': f'从数据库获取到 {len(db_plates)} 个目标板块',
                        'plates': db_plates,
                        'source': 'database',
                        'total_count': len(db_plates)
                    })
                    return result

            # 从API获取
            if self.futu_client and self.futu_client.is_available():
                self.logger.info("从富途API获取板块数据")
                api_result = self._fetch_plates_from_api()

                if api_result['success']:
                    result.update({
                        'success': True,
                        'message': f'从API获取到 {len(api_result["plates"])} 个目标板块',
                        'plates': api_result['plates'],
                        'source': 'futu_api',
                        'total_count': len(api_result['plates'])
                    })
                else:
                    result['errors'].extend(api_result.get('errors', []))
                    self._fallback_to_default(result, 'API获取失败，使用默认板块数据')
            else:
                self._fallback_to_default(result, 'API不可用，使用默认板块数据')

        except Exception as e:
            self.logger.error(f"获取目标板块失败: {e}")
            result.update({
                'success': False,
                'message': f'获取目标板块异常: {str(e)}'
            })
            result['errors'].append(str(e))

        return result

    def _fallback_to_default(self, result: Dict[str, Any], message: str):
        """使用默认板块数据作为兜底"""
        default_plates = self._get_default_plates()
        result.update({
            'success': True,
            'message': message,
            'plates': default_plates,
            'source': 'default',
            'total_count': len(default_plates)
        })

    def _get_plates_from_db(self) -> List[Dict[str, Any]]:
        """从数据库获取目标板块"""
        try:
            query = '''
                SELECT id, plate_code, plate_name, market, category,
                       stock_count, priority, match_score
                FROM plates
                WHERE is_target = 1
                ORDER BY priority DESC, match_score DESC
            '''
            results = self.db_manager.execute_query(query)

            plate_objects = [Plate.from_db_row(row) for row in results]
            plates = [plate.to_dict() for plate in plate_objects]

            self.logger.info(f"从数据库获取到 {len(plates)} 个目标板块")
            return plates

        except Exception as e:
            self.logger.error(f"从数据库获取板块失败: {e}")
            return []

    def _fetch_plates_from_api(self) -> Dict[str, Any]:
        """从富途API获取板块数据"""
        result = {'success': False, 'plates': [], 'errors': []}

        try:
            target_plates = []

            hk_plates = self._fetch_market_plates('HK')
            target_plates.extend(hk_plates)

            us_plates = self._fetch_market_plates('US')
            target_plates.extend(us_plates)

            if target_plates:
                result.update({
                    'success': True,
                    'plates': target_plates
                })
                self.logger.info(f"成功获取 {len(target_plates)} 个目标板块")
            else:
                result['errors'].append("未找到匹配的目标板块")

        except Exception as e:
            self.logger.error(f"从API获取板块失败: {e}")
            result['errors'].append(str(e))

        return result

    def _fetch_market_plates(self, market_code: str) -> List[Dict[str, Any]]:
        """获取指定市场的目标板块"""
        target_plates = []

        try:
            market = MarketType.get_market_by_code(market_code)
            if not market:
                self.logger.warning(f"不支持的市场代码: {market_code}")
                return target_plates

            ret, plate_data = self.futu_client.get_plate_list(market, 'ALL')

            if ReturnCode.is_ok(ret) and plate_data is not None and not plate_data.empty:
                for _, plate_row in plate_data.iterrows():
                    plate_info = FieldMapper.extract_plate_info(plate_row, market_code)
                    if plate_info:
                        match_result = self.plate_matcher.match(plate_info['name'])

                        if match_result.matched and match_result.score >= self.plate_matcher.MIN_MATCH_SCORE:
                            plate_info['category'] = match_result.category
                            plate_info['match_score'] = match_result.score
                            plate_info['priority'] = match_result.score
                            target_plates.append(plate_info)

                target_plates.sort(key=lambda x: x.get('match_score', 0), reverse=True)
                target_plates = target_plates[:10]

            time.sleep(self.API_REQUEST_DELAY)

        except Exception as e:
            self.logger.error(f"获取 {market_code} 市场板块异常: {e}")

        return target_plates

    def _get_default_plates(self) -> List[Dict[str, Any]]:
        """获取默认板块数据"""
        default_plates = [
            {
                'code': 'BK1027', 'name': '港股科技', 'market': 'HK',
                'category': '科技', 'stock_count': 0, 'priority': 100, 'match_score': 100
            },
            {
                'code': 'BK1046', 'name': '港股医药', 'market': 'HK',
                'category': '医药', 'stock_count': 0, 'priority': 100, 'match_score': 100
            },
            {
                'code': 'BK1033', 'name': '港股新能源', 'market': 'HK',
                'category': '新能源', 'stock_count': 0, 'priority': 100, 'match_score': 100
            },
            {
                'code': 'BK1001', 'name': '中概股', 'market': 'US',
                'category': '科网股', 'stock_count': 0, 'priority': 100, 'match_score': 100
            },
            {
                'code': 'BK1002', 'name': '芯片概念', 'market': 'US',
                'category': '芯片', 'stock_count': 0, 'priority': 100, 'match_score': 100
            },
        ]

        self.logger.info(f"使用默认板块数据: {len(default_plates)} 个板块")
        return default_plates

    def refresh_plates(self, force_api: bool = False) -> Dict[str, Any]:
        """
        刷新板块数据

        Args:
            force_api: 是否强制从API获取

        Returns:
            Dict: 刷新结果
        """
        self.logger.info(f"刷新板块数据 (force_api={force_api})")
        return self.get_target_plates(from_db=not force_api)

    def get_plate_categories(self) -> List[str]:
        """获取所有目标板块类别"""
        return self.plate_matcher.get_target_categories()

    def get_plates_by_category(self, category: str) -> List[Dict[str, Any]]:
        """
        按类别获取板块

        Args:
            category: 板块类别（如：科技、芯片、医药等）

        Returns:
            List: 板块列表
        """
        plates = []

        try:
            query = '''
                SELECT id, plate_code, plate_name, market, category,
                       stock_count, priority, match_score
                FROM plates
                WHERE is_target = 1 AND category = ?
                ORDER BY priority DESC
            '''
            results = self.db_manager.execute_query(query, (category,))

            for row in results:
                plates.append({
                    'id': row[0],
                    'code': row[1],
                    'name': row[2],
                    'market': row[3],
                    'category': row[4] or '',
                    'stock_count': row[5] or 0,
                    'priority': row[6] or 0,
                    'match_score': row[7] or 0
                })

        except Exception as e:
            self.logger.error(f"按类别获取板块失败: {e}")

        return plates
