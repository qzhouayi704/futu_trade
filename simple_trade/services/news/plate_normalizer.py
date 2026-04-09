#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
板块名称标准化器
将不同来源（Gemini AI、关键词分析）的板块名称映射到统一的标准名称，
从根源消除热门板块列表中的重复问题。
"""

import logging
from dataclasses import dataclass
from typing import Dict, List

logger = logging.getLogger(__name__)


@dataclass
class NormalizedPlate:
    """标准化后的板块信息"""
    plate_code: str
    plate_name: str


class PlateNormalizer:
    """板块名称标准化器

    通过维护别名映射表，将同一概念的不同表述（如 "AI"、"人工智能"、"人工智慧"）
    映射到统一的标准 plate_code 和 plate_name。

    标准化逻辑：先查 plate_code，再查 plate_name，都没匹配则保留原值。
    """

    # 别名 → 标准名称映射（覆盖简体、繁体、英文）
    ALIAS_MAP: Dict[str, NormalizedPlate] = {
        # 科技相关
        'AI': NormalizedPlate('科技', '科技'),
        '人工智能': NormalizedPlate('科技', '科技'),
        '人工智慧': NormalizedPlate('科技', '科技'),
        '互联网': NormalizedPlate('科技', '科技'),
        '互聯網': NormalizedPlate('科技', '科技'),
        '芯片': NormalizedPlate('科技', '科技'),
        '晶片': NormalizedPlate('科技', '科技'),
        '半导体': NormalizedPlate('科技', '科技'),
        '半導體': NormalizedPlate('科技', '科技'),
        # 新能源相关
        '电动车': NormalizedPlate('新能源', '新能源'),
        '電動車': NormalizedPlate('新能源', '新能源'),
        '锂电': NormalizedPlate('新能源', '新能源'),
        '鋰電': NormalizedPlate('新能源', '新能源'),
        '光伏': NormalizedPlate('新能源', '新能源'),
        '储能': NormalizedPlate('新能源', '新能源'),
        '儲能': NormalizedPlate('新能源', '新能源'),
        # 医药相关
        '生物': NormalizedPlate('医药', '医药'),
        '疫苗': NormalizedPlate('医药', '医药'),
        '创新药': NormalizedPlate('医药', '医药'),
        '創新藥': NormalizedPlate('医药', '医药'),
        '醫藥': NormalizedPlate('医药', '医药'),
        # 金融相关
        '银行': NormalizedPlate('金融', '金融'),
        '銀行': NormalizedPlate('金融', '金融'),
        '保险': NormalizedPlate('金融', '金融'),
        '保險': NormalizedPlate('金融', '金融'),
        '券商': NormalizedPlate('金融', '金融'),
        # 消费相关
        '零售': NormalizedPlate('消费', '消费'),
        '餐饮': NormalizedPlate('消费', '消费'),
        '餐飲': NormalizedPlate('消费', '消费'),
        '白酒': NormalizedPlate('消费', '消费'),
        '消費': NormalizedPlate('消费', '消费'),
        # 房地产相关
        '地产': NormalizedPlate('房地产', '房地产'),
        '地產': NormalizedPlate('房地产', '房地产'),
        '房地產': NormalizedPlate('房地产', '房地产'),
        '楼市': NormalizedPlate('房地产', '房地产'),
        '樓市': NormalizedPlate('房地产', '房地产'),
    }

    def normalize(self, plate_code: str, plate_name: str) -> NormalizedPlate:
        """标准化板块名称

        查找顺序：先查 plate_code，再查 plate_name，都没匹配则保留原值。

        Args:
            plate_code: 原始板块代码
            plate_name: 原始板块名称

        Returns:
            标准化后的 NormalizedPlate
        """
        # 先查 plate_code
        if plate_code in self.ALIAS_MAP:
            return self.ALIAS_MAP[plate_code]

        # 再查 plate_name
        if plate_name in self.ALIAS_MAP:
            return self.ALIAS_MAP[plate_name]

        # 都没匹配，保留原值
        return NormalizedPlate(plate_code, plate_name)

    def normalize_plates(self, plates: List[Dict]) -> List[Dict]:
        """批量标准化板块列表，同时去除重复

        标准化后按 plate_code 去重，保留第一个出现的 impact_type。

        Args:
            plates: 板块字典列表，每个字典包含 plate_code, plate_name, impact_type 等字段

        Returns:
            标准化并去重后的板块字典列表
        """
        seen_codes: Dict[str, Dict] = {}

        for plate in plates:
            plate_code = plate.get('plate_code', '')
            plate_name = plate.get('plate_name', '')

            normalized = self.normalize(plate_code, plate_name)

            # 按标准化后的 plate_code 去重，保留第一个出现的
            if normalized.plate_code not in seen_codes:
                seen_codes[normalized.plate_code] = {
                    **plate,
                    'plate_code': normalized.plate_code,
                    'plate_name': normalized.plate_name,
                }

        return list(seen_codes.values())

    def fix_historical_data(self, db_manager) -> Dict[str, int]:
        """修复历史数据中的非标准板块名称

        扫描 news_plates 表所有记录，将非标准 plate_code/plate_name 更新为标准值。
        同一 news_id 下标准化后 plate_code 重复时，删除多余记录（合并）。

        Args:
            db_manager: 数据库管理器，需提供 execute_query 和 execute_update 方法

        Returns:
            统计信息 {'scanned': N, 'updated': N, 'merged': N}
        """
        stats = {'scanned': 0, 'updated': 0, 'merged': 0}

        # 查询所有 news_plates 记录
        rows = db_manager.execute_query(
            "SELECT id, news_id, plate_code, plate_name FROM news_plates"
        )
        if not rows:
            return stats

        stats['scanned'] = len(rows)

        for row in rows:
            record_id, news_id, plate_code, plate_name = row
            try:
                normalized = self.normalize(plate_code, plate_name or '')

                # 标准化后与原值相同，跳过
                if normalized.plate_code == plate_code and normalized.plate_name == (plate_name or ''):
                    continue

                # 检查同一 news_id 下是否已存在标准化后的 plate_code（UNIQUE 冲突检测）
                existing = db_manager.execute_query(
                    "SELECT id FROM news_plates WHERE news_id = ? AND plate_code = ? AND id != ?",
                    (news_id, normalized.plate_code, record_id)
                )

                if existing:
                    # 已存在相同的标准化 plate_code，删除当前记录（合并）
                    db_manager.execute_update(
                        "DELETE FROM news_plates WHERE id = ?",
                        (record_id,)
                    )
                    stats['merged'] += 1
                else:
                    # 不存在冲突，执行更新
                    db_manager.execute_update(
                        "UPDATE news_plates SET plate_code = ?, plate_name = ? WHERE id = ?",
                        (normalized.plate_code, normalized.plate_name, record_id)
                    )
                    stats['updated'] += 1

            except Exception as e:
                logger.error(f"修复记录 id={record_id} 失败: {e}")
                continue

        logger.info(
            f"历史数据修复完成: 扫描 {stats['scanned']} 条, "
            f"更新 {stats['updated']} 条, 合并 {stats['merged']} 条"
        )
        return stats

