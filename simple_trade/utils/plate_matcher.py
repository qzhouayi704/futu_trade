#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能板块匹配器 - 支持文字和语义近似匹配
"""

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from difflib import SequenceMatcher


@dataclass
class MatchResult:
    """匹配结果"""
    matched: bool           # 是否匹配成功
    category: str           # 匹配到的目标类别
    score: int              # 匹配分数 (0-100)
    matched_keyword: str    # 匹配到的关键词
    match_type: str         # 匹配类型: exact/synonym/fuzzy


class PlateMatcher:
    """
    智能板块匹配器
    
    支持三种匹配方式：
    1. 精确匹配 - 板块名包含目标关键词
    2. 同义词匹配 - 通过同义词表匹配
    3. 模糊匹配 - 基于字符相似度匹配
    """
    
    # 目标板块及其同义词/近义词映射
    # 格式: { "目标类别": ["主关键词", "同义词1", "同义词2", ...] }
    TARGET_PLATES: Dict[str, List[str]] = {
        "科技": [
            "科技", "科网", "互联网", "软件", "计算机",
            "信息技术", "数字经济", "信息科技"
        ],
        "AI": [
            "AI", "人工智能", "ChatGPT", "大模型", "大语言模型",
            "机器学习", "深度学习", "神经网络", "算法", "智能",
            "GPT", "生成式AI", "AIGC", "AI应用", "AI芯片",
            "智能算法", "智能科技", "智能应用", "AI技术",
            "人工智慧", "智慧", "智能化", "AI+", "AI赋能"
        ],
        "芯片": [
            "芯片", "半导体", "集成电路", "晶片", "晶圆",
            "半导体设备", "芯片设计", "封测"
        ],
        "医药": [
            "医药", "生物", "医疗", "制药", "健康",
            "生物科技", "生物制药", "创新药", "医疗器械",
            "生物医药", "医药健康"
        ],
        "科网股": [
            "科网", "中概互联", "中概股", "互联网科技",
            "网络科技", "电商", "在线服务"
        ],
        "新能源": [
            "新能源", "电动车", "锂电池", "储能", "光伏",
            "风电", "清洁能源", "新能源车", "新能源汽车",
            "绿色能源", "可再生能源"
        ]
    }
    
    # 黑名单关键词 - 排除这些板块
    BLACKLIST_KEYWORDS: List[str] = [
        "ETF", "etf", "基金", "债券", "指数基金",
        "货币基金", "理财", "信托", "银行理财",
        "REIT", "REITs", "房地产投资信托",
        "期货", "期权", "权证"
    ]
    
    # 匹配阈值配置
    EXACT_MATCH_SCORE = 100      # 精确匹配分数
    SYNONYM_MATCH_SCORE = 85     # 同义词匹配分数
    FUZZY_MATCH_THRESHOLD = 0.7  # 模糊匹配相似度阈值
    FUZZY_MATCH_SCORE = 70       # 模糊匹配基础分数
    MIN_MATCH_SCORE = 60         # 最低匹配分数阈值
    
    def __init__(self):
        """初始化匹配器"""
        self.logger = logging.getLogger(__name__)
        # 构建反向索引：关键词 -> 目标类别
        self._keyword_index: Dict[str, str] = {}
        self._build_keyword_index()
    
    def _build_keyword_index(self):
        """构建关键词反向索引"""
        for category, keywords in self.TARGET_PLATES.items():
            for keyword in keywords:
                # 转小写存储，便于匹配
                self._keyword_index[keyword.lower()] = category
        self.logger.debug(f"构建关键词索引完成，共 {len(self._keyword_index)} 个关键词")
    
    def match(self, plate_name: str) -> MatchResult:
        """
        匹配板块名称
        
        Args:
            plate_name: 板块名称
            
        Returns:
            MatchResult: 匹配结果
        """
        if not plate_name:
            return MatchResult(
                matched=False, category="", score=0,
                matched_keyword="", match_type="none"
            )
        
        # 检查是否在黑名单中
        if self._is_blacklisted(plate_name):
            self.logger.debug(f"板块 '{plate_name}' 在黑名单中，跳过")
            return MatchResult(
                matched=False, category="", score=0,
                matched_keyword="blacklisted", match_type="blacklist"
            )
        
        plate_name_lower = plate_name.lower()
        
        # 1. 尝试精确匹配
        result = self._exact_match(plate_name_lower)
        if result.matched:
            self._log_match(plate_name, result)
            return result
        
        # 2. 尝试同义词匹配
        result = self._synonym_match(plate_name_lower)
        if result.matched:
            self._log_match(plate_name, result)
            return result
        
        # 3. 尝试模糊匹配
        result = self._fuzzy_match(plate_name_lower)
        if result.matched:
            self._log_match(plate_name, result)
            return result
        
        # 未匹配
        return MatchResult(
            matched=False, category="", score=0,
            matched_keyword="", match_type="none"
        )
    
    def _is_blacklisted(self, plate_name: str) -> bool:
        """检查板块是否在黑名单中"""
        plate_name_lower = plate_name.lower()
        for keyword in self.BLACKLIST_KEYWORDS:
            if keyword.lower() in plate_name_lower:
                return True
        return False
    
    def _exact_match(self, plate_name_lower: str) -> MatchResult:
        """
        精确匹配 - 板块名包含目标关键词
        
        Args:
            plate_name_lower: 小写的板块名称
            
        Returns:
            MatchResult: 匹配结果
        """
        for category, keywords in self.TARGET_PLATES.items():
            for keyword in keywords:
                keyword_lower = keyword.lower()
                if keyword_lower in plate_name_lower:
                    return MatchResult(
                        matched=True,
                        category=category,
                        score=self.EXACT_MATCH_SCORE,
                        matched_keyword=keyword,
                        match_type="exact"
                    )
        
        return MatchResult(
            matched=False, category="", score=0,
            matched_keyword="", match_type="none"
        )
    
    def _synonym_match(self, plate_name_lower: str) -> MatchResult:
        """
        同义词匹配 - 通过同义词表匹配
        
        对于一些变体形式的匹配，如：
        - "半导体产业" -> "芯片"
        - "创新药物" -> "医药"
        """
        # 提取板块名中的关键部分（去除"概念"、"行业"、"板块"等后缀）
        cleaned_name = self._clean_plate_name(plate_name_lower)
        
        for category, keywords in self.TARGET_PLATES.items():
            for keyword in keywords:
                keyword_lower = keyword.lower()
                # 检查清理后的名称
                if keyword_lower in cleaned_name:
                    return MatchResult(
                        matched=True,
                        category=category,
                        score=self.SYNONYM_MATCH_SCORE,
                        matched_keyword=keyword,
                        match_type="synonym"
                    )
        
        return MatchResult(
            matched=False, category="", score=0,
            matched_keyword="", match_type="none"
        )
    
    def _fuzzy_match(self, plate_name_lower: str) -> MatchResult:
        """
        模糊匹配 - 基于字符相似度匹配
        
        使用 SequenceMatcher 计算字符串相似度
        """
        best_match: Optional[Tuple[str, str, float]] = None  # (category, keyword, similarity)
        
        # 提取板块名的核心部分
        cleaned_name = self._clean_plate_name(plate_name_lower)
        
        for category, keywords in self.TARGET_PLATES.items():
            for keyword in keywords:
                keyword_lower = keyword.lower()
                
                # 计算相似度
                similarity = SequenceMatcher(
                    None, cleaned_name, keyword_lower
                ).ratio()
                
                if similarity >= self.FUZZY_MATCH_THRESHOLD:
                    if best_match is None or similarity > best_match[2]:
                        best_match = (category, keyword, similarity)
        
        if best_match:
            # 根据相似度计算分数
            similarity_bonus = int((best_match[2] - self.FUZZY_MATCH_THRESHOLD) * 100)
            score = min(self.FUZZY_MATCH_SCORE + similarity_bonus, 
                       self.SYNONYM_MATCH_SCORE - 1)  # 不超过同义词匹配分数
            
            return MatchResult(
                matched=True,
                category=best_match[0],
                score=score,
                matched_keyword=best_match[1],
                match_type="fuzzy"
            )
        
        return MatchResult(
            matched=False, category="", score=0,
            matched_keyword="", match_type="none"
        )
    
    def _clean_plate_name(self, plate_name: str) -> str:
        """
        清理板块名称，去除常见后缀
        
        Args:
            plate_name: 板块名称
            
        Returns:
            str: 清理后的名称
        """
        # 需要移除的后缀
        suffixes = [
            "概念", "行业", "板块", "指数", "主题",
            "股", "股票", "相关", "产业", "领域"
        ]
        
        cleaned = plate_name
        for suffix in suffixes:
            cleaned = cleaned.replace(suffix.lower(), "")
        
        # 去除空格和标点
        cleaned = re.sub(r'[\s\-_\.]+', '', cleaned)
        
        return cleaned.strip()
    
    def _log_match(self, plate_name: str, result: MatchResult):
        """记录匹配日志"""
        self.logger.info(
            f"板块匹配成功: '{plate_name}' -> "
            f"类别='{result.category}', "
            f"关键词='{result.matched_keyword}', "
            f"分数={result.score}, "
            f"类型={result.match_type}"
        )
    
    def batch_match(self, plate_names: List[str]) -> Dict[str, MatchResult]:
        """
        批量匹配板块名称
        
        Args:
            plate_names: 板块名称列表
            
        Returns:
            Dict[str, MatchResult]: 板块名 -> 匹配结果
        """
        results = {}
        matched_count = 0
        
        for name in plate_names:
            result = self.match(name)
            results[name] = result
            if result.matched:
                matched_count += 1
        
        self.logger.info(
            f"批量匹配完成: 共 {len(plate_names)} 个板块, "
            f"匹配成功 {matched_count} 个"
        )
        
        return results
    
    def get_target_categories(self) -> List[str]:
        """获取所有目标类别"""
        return list(self.TARGET_PLATES.keys())
    
    def get_category_keywords(self, category: str) -> List[str]:
        """获取指定类别的所有关键词"""
        return self.TARGET_PLATES.get(category, [])
    
    def add_custom_keyword(self, category: str, keyword: str):
        """
        动态添加自定义关键词
        
        Args:
            category: 目标类别
            keyword: 新关键词
        """
        if category in self.TARGET_PLATES:
            if keyword not in self.TARGET_PLATES[category]:
                self.TARGET_PLATES[category].append(keyword)
                self._keyword_index[keyword.lower()] = category
                self.logger.info(f"添加自定义关键词: {category} -> {keyword}")
        else:
            self.logger.warning(f"未知类别: {category}")


# 全局单例
_plate_matcher: Optional[PlateMatcher] = None


def get_plate_matcher() -> PlateMatcher:
    """获取板块匹配器单例"""
    global _plate_matcher
    if _plate_matcher is None:
        _plate_matcher = PlateMatcher()
    return _plate_matcher
