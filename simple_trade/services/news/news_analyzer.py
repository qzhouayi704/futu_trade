#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新闻分析服务
分析新闻情感和关联股票/板块
支持 Gemini AI 和基于关键词的分析
"""

import re
import json
import logging
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass, field

from .gemini_analyzer import GeminiNewsAnalyzer, GeminiAnalysisResult
from .plate_normalizer import PlateNormalizer


@dataclass
class AnalysisResult:
    """分析结果"""
    sentiment: str
    sentiment_score: float
    related_stocks: List[Dict[str, Any]] = field(default_factory=list)
    related_plates: List[Dict[str, Any]] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)


class NewsAnalyzer:
    """新闻分析器 - 支持 Gemini AI 和关键词分析"""

    # 利好关键词（简体+繁体）
    POSITIVE_KEYWORDS = [
        '上涨', '上漲', '大涨', '大漲', '暴涨', '暴漲', '涨停', '漲停',
        '新高', '突破', '利好', '增长', '增長', '盈利', '超预期', '超預期',
        '回购', '回購', '增持', '分红', '分紅', '获批', '獲批', '中标', '中標',
        '签约', '簽約', '合作', '收购', '收購', '扩产', '擴產', '业绩', '業績',
        '创新高', '創新高', '强势', '強勢', '看涨', '看漲', '买入', '買入',
        '推荐', '推薦', '利多', '反弹', '反彈', '复苏', '復甦'
    ]

    # 利空关键词（简体+繁体）
    NEGATIVE_KEYWORDS = [
        '下跌', '大跌', '暴跌', '跌停', '新低', '破位', '利空',
        '亏损', '虧損', '下滑', '不及预期', '不及預期', '减持', '減持',
        '清仓', '清倉', '违规', '違規', '处罚', '處罰', '诉讼', '訴訟',
        '退市', '暂停', '暫停', '终止', '終止', '裁员', '裁員',
        '破产', '破產', '爆雷', '风险', '風險', '警告', '看跌', '看跌',
        '卖出', '賣出', '利淡', '下调', '下調', '降级', '降級'
    ]

    # 股票代码正则（港股、美股、A股）
    STOCK_CODE_PATTERNS = [
        re.compile(r'([A-Z]{2}\.\d{5})'),           # HK.00700
        re.compile(r'(\d{5})\.HK'),                  # 00700.HK
        re.compile(r'(\d{6})\.(SH|SZ)'),             # 600000.SH
        re.compile(r'\$([A-Z]{1,5})\$'),             # $AAPL$
        re.compile(r'([A-Z]{1,5})(?=\s*\()'),        # AAPL (
    ]

    # 常见股票名称映射
    STOCK_NAME_MAP = {
        '腾讯': 'HK.00700',
        '騰訊': 'HK.00700',
        '阿里': 'HK.09988',
        '阿里巴巴': 'HK.09988',
        '美团': 'HK.03690',
        '美團': 'HK.03690',
        '京东': 'HK.09618',
        '京東': 'HK.09618',
        '小米': 'HK.01810',
        '比亚迪': 'HK.01211',
        '比亞迪': 'HK.01211',
        '蔚来': 'HK.09866',
        '蔚來': 'HK.09866',
        '小鹏': 'HK.09868',
        '小鵬': 'HK.09868',
        '理想': 'HK.02015',
        '网易': 'HK.09999',
        '網易': 'HK.09999',
        '百度': 'HK.09888',
        '快手': 'HK.01024',
        '华为': None,  # 未上市
        '華為': None,
    }

    # 板块关键词映射
    PLATE_KEYWORDS = {
        '科技': ['科技', '互联网', '互聯網', 'AI', '人工智能', '芯片', '晶片'],
        '新能源': ['新能源', '电动车', '電動車', '锂电', '鋰電', '光伏', '储能'],
        '医药': ['医药', '醫藥', '生物', '疫苗', '创新药', '創新藥'],
        '金融': ['银行', '銀行', '保险', '保險', '券商', '金融'],
        '消费': ['消费', '消費', '零售', '餐饮', '餐飲', '白酒'],
        '房地产': ['房地产', '房地產', '地产', '地產', '楼市', '樓市'],
    }

    def __init__(self, db_manager=None, config: Optional[Dict[str, Any]] = None):
        """
        初始化新闻分析器

        Args:
            db_manager: 数据库管理器
            config: 配置字典，包含 gemini 配置
        """
        self.logger = logging.getLogger(__name__)
        self.db_manager = db_manager
        self.normalizer = PlateNormalizer()
        self.gemini_analyzer: Optional[GeminiNewsAnalyzer] = None

        # 初始化 Gemini 分析器
        if config and config.get('gemini', {}).get('enabled', False):
            gemini_config = config['gemini']
            try:
                self.gemini_analyzer = GeminiNewsAnalyzer(
                    api_key=gemini_config['api_key'],
                    model=gemini_config.get('model', 'gemini-3-flash-preview'),
                    timeout=gemini_config.get('timeout', 30)
                )
                if self.gemini_analyzer.is_available():
                    self.logger.info("Gemini 分析器已启用")
                else:
                    self.logger.warning("Gemini 分析器初始化失败，将使用关键词分析")
                    self.gemini_analyzer = None
            except Exception as e:
                self.logger.error(f"初始化 Gemini 分析器失败: {e}")
                self.gemini_analyzer = None

    async def analyze(self, title: str, content: str = "") -> AnalysisResult:
        """
        分析新闻（异步方法）

        Args:
            title: 新闻标题
            content: 新闻内容

        Returns:
            AnalysisResult
        """
        # 优先使用 Gemini 分析
        if self.gemini_analyzer and self.gemini_analyzer.is_available():
            try:
                gemini_result = await self.gemini_analyzer.analyze(title, content)
                if gemini_result:
                    return self._convert_gemini_result(gemini_result)
                else:
                    self.logger.warning("Gemini 分析失败，回退到关键词分析")
            except Exception as e:
                self.logger.error(f"Gemini 分析异常: {e}，回退到关键词分析")

        # 回退到关键词分析
        return self._keyword_analyze(title, content)

    async def analyze_batch(self, news_list: list) -> list:
        """
        批量分析新闻（一次 Gemini API 请求）

        Args:
            news_list: [{'id': int, 'title': str, 'summary': str}, ...]

        Returns:
            [{'id': int, 'result': AnalysisResult}, ...]
        """
        if self.gemini_analyzer and self.gemini_analyzer.is_available():
            try:
                batch_results = await self.gemini_analyzer.analyze_batch(news_list)
                return [
                    {'id': r['id'], 'result': self._convert_gemini_result(r['result'])}
                    for r in batch_results
                ]
            except Exception as e:
                self.logger.error(f"批量 Gemini 分析异常: {e}，回退到逐条关键词分析")

        # 回退：逐条关键词分析
        results = []
        for news in news_list:
            result = self._keyword_analyze(news.get('title', ''), news.get('summary', ''))
            results.append({'id': news['id'], 'result': result})
        return results

    def _convert_gemini_result(self, gemini_result: GeminiAnalysisResult) -> AnalysisResult:
        """将 Gemini 结果转换为 AnalysisResult"""
        return AnalysisResult(
            sentiment=gemini_result.sentiment,
            sentiment_score=gemini_result.sentiment_score,
            related_stocks=gemini_result.related_stocks,
            related_plates=self.normalizer.normalize_plates(gemini_result.related_plates),
            keywords=gemini_result.keywords
        )

    def _keyword_analyze(self, title: str, content: str = "") -> AnalysisResult:
        """基于关键词的分析（回退方案）"""
        text = f"{title} {content}"

        # 情感分析
        sentiment, score = self._analyze_sentiment(text)

        # 提取相关股票
        related_stocks = self._extract_stocks(text, sentiment)

        # 提取相关板块
        related_plates = self._extract_plates(text, sentiment)

        # 提取关键词
        keywords = self._extract_keywords(text)

        return AnalysisResult(
            sentiment=sentiment,
            sentiment_score=score,
            related_stocks=related_stocks,
            related_plates=related_plates,
            keywords=keywords
        )

    def _analyze_sentiment(self, text: str) -> Tuple[str, float]:
        """基于关键词的情感分析"""
        positive_count = sum(1 for kw in self.POSITIVE_KEYWORDS if kw in text)
        negative_count = sum(1 for kw in self.NEGATIVE_KEYWORDS if kw in text)

        total = positive_count + negative_count
        if total == 0:
            return 'neutral', 0.0

        score = (positive_count - negative_count) / total

        if score > 0.2:
            return 'positive', score
        elif score < -0.2:
            return 'negative', score
        else:
            return 'neutral', score

    def _extract_stocks(self, text: str, sentiment: str) -> List[Dict[str, Any]]:
        """提取相关股票"""
        stocks = []
        found_codes = set()

        # 通过正则提取股票代码
        for pattern in self.STOCK_CODE_PATTERNS:
            matches = pattern.findall(text)
            for match in matches:
                code = match if isinstance(match, str) else match[0]
                if code not in found_codes:
                    found_codes.add(code)
                    stocks.append({
                        'stock_code': code,
                        'stock_name': None,
                        'impact_type': sentiment
                    })

        # 通过股票名称匹配
        for name, code in self.STOCK_NAME_MAP.items():
            if name in text and code and code not in found_codes:
                found_codes.add(code)
                stocks.append({
                    'stock_code': code,
                    'stock_name': name,
                    'impact_type': sentiment
                })

        return stocks

    def _extract_plates(self, text: str, sentiment: str) -> List[Dict[str, Any]]:
        """提取相关板块"""
        plates = []
        found_plates = set()

        for plate_name, keywords in self.PLATE_KEYWORDS.items():
            for kw in keywords:
                if kw in text and plate_name not in found_plates:
                    found_plates.add(plate_name)
                    plates.append({
                        'plate_code': plate_name,
                        'plate_name': plate_name,
                        'impact_type': sentiment
                    })
                    break

        return self.normalizer.normalize_plates(plates)

    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词"""
        keywords = []

        for kw in self.POSITIVE_KEYWORDS:
            if kw in text and kw not in keywords:
                keywords.append(kw)

        for kw in self.NEGATIVE_KEYWORDS:
            if kw in text and kw not in keywords:
                keywords.append(kw)

        return keywords[:10]
