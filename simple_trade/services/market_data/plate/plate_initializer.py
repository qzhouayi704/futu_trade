#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
板块初始化服务
负责板块数据的获取、匹配和保存
"""

import logging
from typing import Dict, Any, List
from ....database.core.db_manager import DatabaseManager
from ....api.futu_client import FutuClient
from ....api.market_types import MarketType, ReturnCode
from ....utils.field_mapper import FieldMapper
from ....utils.plate_matcher import get_plate_matcher, MatchResult


class PlateInitializerService:
    """
    板块初始化服务

    职责：
    1. 从富途API获取市场板块列表
    2. 使用智能匹配器筛选目标板块
    3. 保存板块数据到数据库
    4. 记录匹配日志
    """

    def __init__(self, db_manager: DatabaseManager, futu_client: FutuClient):
        self.db_manager = db_manager
        self.futu_client = futu_client
        self.plate_matcher = get_plate_matcher()
        self.logger = logging.getLogger(__name__)

    def fetch_market_plates(self, market_code: str) -> List[Dict[str, Any]]:
        """
        获取指定市场的所有板块

        Args:
            market_code: 市场代码 ('HK' 或 'US')

        Returns:
            List: 板块列表
        """
        plates = []

        try:
            market = MarketType.get_market_by_code(market_code)
            if not market:
                self.logger.error(f"不支持的市场代码: {market_code}")
                return plates

            if not self.futu_client.is_available():
                self.logger.error(f"富途API不可用")
                return plates

            ret, plate_data = self.futu_client.get_plate_list(market, 'ALL')

            if ReturnCode.is_ok(ret) and plate_data is not None and not plate_data.empty:
                for _, plate_row in plate_data.iterrows():
                    plate_info = FieldMapper.extract_plate_info(plate_row, market_code)
                    if plate_info:
                        plates.append(plate_info)

                self.logger.info(f"成功获取 {market_code} 市场 {len(plates)} 个板块")
            else:
                self.logger.warning(f"获取 {market_code} 市场板块失败: ret={ret}")

        except Exception as e:
            self.logger.error(f"获取 {market_code} 市场板块异常: {e}")

        return plates

    def match_target_plates(self, plates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        使用智能匹配器筛选目标板块

        Args:
            plates: 所有板块列表

        Returns:
            List: 匹配的目标板块列表
        """
        target_plates = []

        for plate in plates:
            plate_name = plate['name']
            plate_code = plate['code']

            # 使用智能匹配器
            match_result = self.plate_matcher.match(plate_name)

            # 记录匹配日志到数据库
            self._save_match_log(plate_code, plate_name, match_result)

            if match_result.matched and match_result.score >= self.plate_matcher.MIN_MATCH_SCORE:
                plate['category'] = match_result.category
                plate['match_score'] = match_result.score
                plate['matched_keyword'] = match_result.matched_keyword
                plate['match_type'] = match_result.match_type
                plate['is_target'] = True
                plate['priority'] = match_result.score  # 使用匹配分数作为优先级
                target_plates.append(plate)

        # 按匹配分数排序
        target_plates.sort(key=lambda x: x.get('match_score', 0), reverse=True)

        self.logger.info(f"智能匹配完成: {len(plates)} 个板块中匹配到 {len(target_plates)} 个目标板块")

        return target_plates

    def save_plates(self, plates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        保存板块到数据库

        Args:
            plates: 板块列表

        Returns:
            List: 保存成功的板块列表（包含数据库ID）
        """
        saved_plates = []

        try:
            for plate in plates:
                # 插入或更新板块
                self.db_manager.execute_update('''
                    INSERT OR REPLACE INTO plates
                    (plate_code, plate_name, market, category, stock_count, is_target, priority, match_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    plate['code'],
                    plate['name'],
                    plate['market'],
                    plate.get('category', ''),
                    0,
                    plate.get('is_target', True),
                    plate.get('priority', 0),
                    plate.get('match_score', 0)
                ))

                # 获取板块ID
                result = self.db_manager.execute_query(
                    'SELECT id FROM plates WHERE plate_code = ?',
                    (plate['code'],)
                )
                if result:
                    plate['id'] = result[0][0]
                    saved_plates.append(plate)

            self.logger.info(f"成功保存 {len(saved_plates)} 个板块")

        except Exception as e:
            self.logger.error(f"保存板块失败: {e}")

        return saved_plates

    def _save_match_log(self, plate_code: str, plate_name: str, match_result: MatchResult):
        """
        保存匹配日志到数据库

        Args:
            plate_code: 板块代码
            plate_name: 板块名称
            match_result: 匹配结果
        """
        try:
            self.db_manager.execute_update('''
                INSERT INTO plate_match_log
                (plate_code, plate_name, matched, category, match_score, matched_keyword, match_type)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                plate_code,
                plate_name,
                match_result.matched,
                match_result.category,
                match_result.score,
                match_result.matched_keyword,
                match_result.match_type
            ))
        except Exception as e:
            self.logger.warning(f"保存匹配日志失败: {e}")

    def fetch_and_match_all_markets(self) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        获取并匹配所有市场的板块

        Returns:
            tuple: (所有板块列表, 目标板块列表)
        """
        all_plates = []

        # 获取港股板块
        self.logger.info("获取港股板块列表...")
        hk_plates = self.fetch_market_plates('HK')
        all_plates.extend(hk_plates)
        self.logger.info(f"获取到 {len(hk_plates)} 个港股板块")

        # 获取美股板块
        self.logger.info("获取美股板块列表...")
        us_plates = self.fetch_market_plates('US')
        all_plates.extend(us_plates)
        self.logger.info(f"获取到 {len(us_plates)} 个美股板块")

        # 匹配目标板块
        if all_plates:
            self.logger.info("使用智能匹配器筛选目标板块...")
            target_plates = self.match_target_plates(all_plates)
            self.logger.info(f"匹配到 {len(target_plates)} 个目标板块")
            return all_plates, target_plates

        return [], []
