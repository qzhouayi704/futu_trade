#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
个股消息面搜索服务

通过 Gemini + Google Search grounding 搜索股票近期新闻，
提取催化剂和风险因素。实测耗时约 7 秒。
"""

import json
import logging
import asyncio
from typing import Optional

logger = logging.getLogger("stock_news_search")

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False


class StockNewsSearchService:
    """Gemini 联网搜索消息面"""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash",
                 vertexai: bool = False, project: str = None, location: str = None):
        self.api_key = api_key
        self.model = model
        self.client = None

        if not GENAI_AVAILABLE:
            logger.warning("google.genai 未安装，消息面搜索不可用")
            return

        # 模式1（默认）: Vertex AI — 使用 ADC 认证，不传 api_key
        if vertexai and project:
            try:
                self.client = genai.Client(
                    vertexai=True,
                    project=project,
                    location=location or "us-central1",
                )
                logger.info(f"StockNewsSearch 初始化成功 (Vertex AI), model={model}, project={project}")
                return
            except Exception as e:
                logger.warning(f"Vertex AI 初始化失败，降级到标准模式: {e}")

        # 模式2（降级/备选）: 标准 API Key
        if api_key:
            try:
                self.client = genai.Client(api_key=api_key)
                logger.info(f"StockNewsSearch 初始化成功 (API Key), model={model}")
            except Exception as e:
                logger.error(f"StockNewsSearch 标准模式初始化也失败: {e}")

    def is_available(self) -> bool:
        return GENAI_AVAILABLE and self.client is not None

    async def search(self, stock_code: str, stock_name: str) -> dict:
        """
        搜索股票近期新闻

        Returns:
            {
                "news": [{"title", "date", "summary", "sentiment"}],
                "key_catalysts": [...],
                "risk_factors": [...],
                "overall_sentiment": "positive/negative/neutral"
            }
        """
        if not self.is_available():
            return self._empty_result("Gemini 不可用")

        prompt = (
            f'请搜索港股 {stock_code}（{stock_name}）最近3天的重要新闻和市场消息。'
            f'用JSON返回（只返回JSON，不要其他文字）：'
            f'{{"news":[{{"title":"标题","date":"日期","summary":"一句话摘要",'
            f'"sentiment":"positive/negative/neutral"}}],'
            f'"overall_sentiment":"总体情绪",'
            f'"key_catalysts":["催化剂1","催化剂2"],'
            f'"risk_factors":["风险1","风险2"]}}'
        )

        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, lambda: self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.2,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                )
            ))

            if not response or not response.text:
                return self._empty_result("Gemini 返回空响应")

            return self._parse_response(response.text)

        except Exception as e:
            logger.error(f"Gemini 搜索失败 {stock_code}: {e}")
            return self._empty_result(str(e))

    def _parse_response(self, text: str) -> dict:
        try:
            json_str = text
            if "```json" in text:
                json_str = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                json_str = text.split("```")[1].split("```")[0].strip()

            data = json.loads(json_str)
            return {
                "news": data.get("news", []),
                "key_catalysts": data.get("key_catalysts", []),
                "risk_factors": data.get("risk_factors", []),
                "overall_sentiment": data.get("overall_sentiment", "neutral"),
                "error": None,
            }
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"解析 Gemini 响应失败: {e}")
            return self._empty_result(f"解析失败: {e}")

    @staticmethod
    def _empty_result(error: Optional[str] = None) -> dict:
        return {
            "news": [],
            "key_catalysts": [],
            "risk_factors": [],
            "overall_sentiment": "neutral",
            "error": error,
        }
