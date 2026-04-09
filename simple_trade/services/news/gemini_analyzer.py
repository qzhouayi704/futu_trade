#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini AI 新闻分析服务
使用 Google Gemini API 进行新闻情感分析和信息提取
"""

import json
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

try:
    from google import genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False


@dataclass
class GeminiAnalysisResult:
    """Gemini 分析结果"""
    sentiment: str  # positive, negative, neutral
    sentiment_score: float  # -1.0 到 1.0
    related_stocks: List[Dict[str, Any]] = field(default_factory=list)
    related_plates: List[Dict[str, Any]] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    summary: str = ""
    confidence: float = 0.0


class GeminiNewsAnalyzer:
    """Gemini 新闻分析器"""

    def __init__(self, api_key: str, model: str = "gemini-3-flash-preview", timeout: int = 30):
        """
        初始化 Gemini 分析器

        Args:
            api_key: Gemini API Key
            model: 模型名称
            timeout: 超时时间（秒）
        """
        self.logger = logging.getLogger(__name__)
        self.api_key = api_key
        self.model_name = model
        self.timeout = timeout
        self.client = None

        if not GEMINI_AVAILABLE:
            self.logger.error("google.genai 未安装，无法使用 Gemini 分析")
            return

        try:
            self.client = genai.Client(api_key=api_key)
            self.logger.info(f"Gemini 分析器初始化成功，模型: {model}")
        except Exception as e:
            self.logger.error(f"Gemini 分析器初始化失败: {e}")

    def is_available(self) -> bool:
        """检查 Gemini 是否可用"""
        return GEMINI_AVAILABLE and self.client is not None

    async def analyze(self, title: str, content: str = "") -> Optional[GeminiAnalysisResult]:
        """
        分析新闻内容

        Args:
            title: 新闻标题
            content: 新闻内容

        Returns:
            GeminiAnalysisResult 或 None（失败时）
        """
        if not self.is_available():
            self.logger.warning("Gemini 不可用，跳过分析")
            return None

        try:
            # 构建提示词
            prompt = self._build_prompt(title, content)

            # 调用 Gemini API
            self.logger.debug(f"调用 Gemini API 分析新闻: {title[:50]}...")
            response = await self._call_gemini_api(prompt)

            if not response:
                return None

            # 解析响应
            result = self._parse_response(response)
            self.logger.info(f"Gemini 分析完成: {title[:50]}... -> {result.sentiment}")

            return result

        except Exception as e:
            self.logger.error(f"Gemini 分析失败: {e}", exc_info=True)
            return None

    def _build_prompt(self, title: str, content: str) -> str:
        """构建分析提示词"""
        text = f"{title}\n{content}" if content else title

        prompt = f"""你是一个专业的金融新闻分析师。请分析以下新闻，提取关键信息。

新闻内容：
{text}

请按照以下 JSON 格式返回分析结果（只返回 JSON，不要其他文字）：

{{
  "sentiment": "positive/negative/neutral",
  "sentiment_score": -1.0到1.0之间的数值,
  "confidence": 0.0到1.0之间的置信度,
  "summary": "一句话总结新闻要点",
  "keywords": ["关键词1", "关键词2", ...],
  "related_stocks": [
    {{
      "stock_code": "股票代码（如HK.00700）",
      "stock_name": "股票名称",
      "impact_type": "positive/negative/neutral",
      "reason": "影响原因"
    }}
  ],
  "related_plates": [
    {{
      "plate_code": "板块代码",
      "plate_name": "板块名称",
      "impact_type": "positive/negative/neutral",
      "reason": "影响原因"
    }}
  ]
}}

分析要求：
1. sentiment: 判断新闻对市场的整体影响（利好positive/利空negative/中性neutral）
2. sentiment_score: 情感强度，-1.0（极度利空）到 1.0（极度利好）
3. confidence: 分析的置信度，0.0-1.0
4. summary: 用一句话概括新闻核心内容
5. keywords: 提取3-5个关键词
6. related_stocks: 提取新闻中提到的股票，包括股票代码、名称、影响类型和原因
   - 股票代码格式：港股用 HK.xxxxx，美股用 US.xxxx，A股用 xxxxxx.SH 或 xxxxxx.SZ
   - 如果新闻中只提到公司名称，请尝试匹配对应的股票代码
7. related_plates: 提取相关的行业板块，包括板块名称、影响类型和原因
   - 常见板块：科技、新能源、医药、金融、消费、房地产、互联网、芯片、电动车等

注意：
- 只返回 JSON 格式，不要添加任何其他文字
- 如果某个字段无法确定，可以留空或使用默认值
- 股票代码要准确，如果不确定就不要填写
"""
        return prompt

    async def _call_gemini_api(self, prompt: str) -> Optional[str]:
        """调用 Gemini API"""
        try:
            # 使用新的 google.genai API（同步调用，在 executor 中运行）
            import asyncio
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt
                )
            )

            if not response or not response.text:
                self.logger.warning("Gemini API 返回空响应")
                return None

            return response.text.strip()

        except Exception as e:
            self.logger.error(f"调用 Gemini API 失败: {e}")
            return None

    async def analyze_batch(self, news_list: list) -> list:
        """
        批量分析多条新闻（一次 API 请求）

        Args:
            news_list: [{'id': int, 'title': str, 'summary': str}, ...]

        Returns:
            [{'id': int, 'result': GeminiAnalysisResult}, ...]
        """
        if not self.is_available() or not news_list:
            return []

        try:
            prompt = self._build_batch_prompt(news_list)
            self.logger.info(f"批量分析 {len(news_list)} 条新闻...")
            response = await self._call_gemini_api(prompt)

            if not response:
                return []

            return self._parse_batch_response(response, news_list)
        except Exception as e:
            self.logger.error(f"批量分析失败: {e}", exc_info=True)
            return []

    def _build_batch_prompt(self, news_list: list) -> str:
        """构建批量分析提示词"""
        news_block = ""
        for i, news in enumerate(news_list):
            title = news.get('title', '')
            summary = news.get('summary', '') or ''
            text = f"{title}\n{summary}" if summary else title
            news_block += f"--- 新闻 {i + 1} (ID: {news['id']}) ---\n{text}\n\n"

        return f"""你是一个专业的金融新闻分析师。请批量分析以下 {len(news_list)} 条新闻。

{news_block}

请按照以下 JSON 格式返回分析结果（只返回 JSON 数组，不要其他文字）：

[
  {{
    "news_id": 新闻ID,
    "sentiment": "positive/negative/neutral",
    "sentiment_score": -1.0到1.0之间的数值,
    "confidence": 0.0到1.0之间的置信度,
    "summary": "一句话总结",
    "keywords": ["关键词1", "关键词2"],
    "related_stocks": [
      {{
        "stock_code": "股票代码（如HK.00700）",
        "stock_name": "股票名称",
        "impact_type": "positive/negative/neutral",
        "reason": "影响原因"
      }}
    ],
    "related_plates": [
      {{
        "plate_code": "板块代码",
        "plate_name": "板块名称",
        "impact_type": "positive/negative/neutral",
        "reason": "影响原因"
      }}
    ]
  }}
]

分析要求：
1. 每条新闻独立分析，返回数组中的一个对象
2. sentiment: 判断新闻对市场的整体影响
3. 股票代码格式：港股 HK.xxxxx，美股 US.xxxx，A股 xxxxxx.SH 或 xxxxxx.SZ
4. 常见板块：科技、新能源、医药、金融、消费、房地产、互联网、芯片、电动车等
5. 只返回 JSON 数组，不要添加任何其他文字
"""

    def _parse_batch_response(self, response: str, news_list: list) -> list:
        """解析批量分析响应"""
        try:
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0].strip()

            data_list = json.loads(json_str)
            if not isinstance(data_list, list):
                self.logger.error("批量响应不是数组格式")
                return []

            # 构建 id → news 映射
            id_map = {n['id']: n for n in news_list}
            results = []

            for item in data_list:
                news_id = item.get('news_id')
                if news_id not in id_map:
                    continue

                result = GeminiAnalysisResult(
                    sentiment=item.get('sentiment', 'neutral'),
                    sentiment_score=float(item.get('sentiment_score', 0.0)),
                    confidence=float(item.get('confidence', 0.0)),
                    summary=item.get('summary', ''),
                    keywords=item.get('keywords', []),
                    related_stocks=item.get('related_stocks', []),
                    related_plates=item.get('related_plates', [])
                )
                results.append({'id': news_id, 'result': result})

            self.logger.info(f"批量解析成功: {len(results)}/{len(news_list)} 条")
            return results

        except json.JSONDecodeError as e:
            self.logger.error(f"解析批量响应失败: {e}\n响应: {response[:500]}")
            return []
        except Exception as e:
            self.logger.error(f"处理批量响应失败: {e}")
            return []

    def _parse_response(self, response: str) -> GeminiAnalysisResult:
        """解析 Gemini 响应"""
        try:
            # 尝试提取 JSON（可能包含在 markdown 代码块中）
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0].strip()

            data = json.loads(json_str)

            # 构建结果
            result = GeminiAnalysisResult(
                sentiment=data.get("sentiment", "neutral"),
                sentiment_score=float(data.get("sentiment_score", 0.0)),
                confidence=float(data.get("confidence", 0.0)),
                summary=data.get("summary", ""),
                keywords=data.get("keywords", []),
                related_stocks=data.get("related_stocks", []),
                related_plates=data.get("related_plates", [])
            )

            return result

        except json.JSONDecodeError as e:
            self.logger.error(f"解析 Gemini 响应失败: {e}\n响应内容: {response}")
            # 返回默认结果
            return GeminiAnalysisResult(
                sentiment="neutral",
                sentiment_score=0.0,
                confidence=0.0
            )
        except Exception as e:
            self.logger.error(f"处理 Gemini 响应失败: {e}")
            return GeminiAnalysisResult(
                sentiment="neutral",
                sentiment_score=0.0,
                confidence=0.0
            )
        async def analyze_batch(self, news_list: list) -> list:
            """
            批量分析多条新闻（一次 API 请求）

            Args:
                news_list: [{'id': int, 'title': str, 'summary': str}, ...]

            Returns:
                [{'id': int, 'result': GeminiAnalysisResult}, ...]
            """
            if not self.is_available() or not news_list:
                return []

            try:
                prompt = self._build_batch_prompt(news_list)
                self.logger.info(f"批量分析 {len(news_list)} 条新闻...")
                response = await self._call_gemini_api(prompt)

                if not response:
                    return []

                return self._parse_batch_response(response, news_list)
            except Exception as e:
                self.logger.error(f"批量分析失败: {e}", exc_info=True)
                return []

        def _build_batch_prompt(self, news_list: list) -> str:
            """构建批量分析提示词"""
            news_block = ""
            for i, news in enumerate(news_list):
                title = news.get('title', '')
                summary = news.get('summary', '') or ''
                text = f"{title}\n{summary}" if summary else title
                news_block += f"--- 新闻 {i + 1} (ID: {news['id']}) ---\n{text}\n\n"

            return f"""你是一个专业的金融新闻分析师。请批量分析以下 {len(news_list)} 条新闻。

    {news_block}

    请按照以下 JSON 格式返回分析结果（只返回 JSON 数组，不要其他文字）：

    [
      {{
        "news_id": 新闻ID（对应上面的ID）,
        "sentiment": "positive/negative/neutral",
        "sentiment_score": -1.0到1.0之间的数值,
        "confidence": 0.0到1.0之间的置信度,
        "summary": "一句话总结",
        "keywords": ["关键词1", "关键词2"],
        "related_stocks": [
          {{
            "stock_code": "股票代码（如HK.00700）",
            "stock_name": "股票名称",
            "impact_type": "positive/negative/neutral",
            "reason": "影响原因"
          }}
        ],
        "related_plates": [
          {{
            "plate_code": "板块代码",
            "plate_name": "板块名称",
            "impact_type": "positive/negative/neutral",
            "reason": "影响原因"
          }}
        ]
      }}
    ]

    分析要求：
    1. 每条新闻独立分析，返回数组中的一个对象
    2. sentiment: 判断新闻对市场的整体影响
    3. 股票代码格式：港股 HK.xxxxx，美股 US.xxxx，A股 xxxxxx.SH 或 xxxxxx.SZ
    4. 常见板块：科技、新能源、医药、金融、消费、房地产、互联网、芯片、电动车等
    5. 只返回 JSON 数组，不要添加任何其他文字
    """

        def _parse_batch_response(self, response: str, news_list: list) -> list:
            """解析批量分析响应"""
            try:
                json_str = response
                if "```json" in response:
                    json_str = response.split("```json")[1].split("```")[0].strip()
                elif "```" in response:
                    json_str = response.split("```")[1].split("```")[0].strip()

                data_list = json.loads(json_str)
                if not isinstance(data_list, list):
                    self.logger.error("批量响应不是数组格式")
                    return []

                # 构建 id → news 映射
                id_map = {n['id']: n for n in news_list}
                results = []

                for item in data_list:
                    news_id = item.get('news_id')
                    if news_id not in id_map:
                        continue

                    result = GeminiAnalysisResult(
                        sentiment=item.get('sentiment', 'neutral'),
                        sentiment_score=float(item.get('sentiment_score', 0.0)),
                        confidence=float(item.get('confidence', 0.0)),
                        summary=item.get('summary', ''),
                        keywords=item.get('keywords', []),
                        related_stocks=item.get('related_stocks', []),
                        related_plates=item.get('related_plates', [])
                    )
                    results.append({'id': news_id, 'result': result})

                self.logger.info(f"批量解析成功: {len(results)}/{len(news_list)} 条")
                return results

            except json.JSONDecodeError as e:
                self.logger.error(f"解析批量响应失败: {e}\n响应: {response[:500]}")
                return []
            except Exception as e:
                self.logger.error(f"处理批量响应失败: {e}")
                return []

