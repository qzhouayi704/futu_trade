#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
富途新闻 API 获取器
通过 HTTP 请求从富途新闻 API 获取新闻数据，替代 Playwright 浏览器爬虫
"""

import hashlib
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from .news_crawler import RawNewsItem

# httpx 可能未安装，使用 try/except 包裹
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class FutuNewsFetcher:
    """富途新闻 API 获取器

    通过 httpx 异步请求富途新闻 API 端点获取 JSON 数据，
    并转换为与 NewsCrawler 相同的 RawNewsItem 数据结构。
    """

    base_url: str = "https://news.futunn.com"
    timeout: int = 30
    _headers: Dict[str, str] = field(default_factory=lambda: {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://news.futunn.com/",
    })

    def is_available(self) -> bool:
        """检查 httpx 是否可导入"""
        return HTTPX_AVAILABLE

    async def fetch_news(self, max_items: int = 50) -> List[RawNewsItem]:
        """获取新闻列表，返回 RawNewsItem 列表

        Args:
            max_items: 最大获取条数，默认 50

        Returns:
            RawNewsItem 列表
        """
        if not self.is_available():
            logger.error("httpx 未安装，无法使用富途新闻 API")
            return []

        url = f"{self.base_url}/news-site-api/main/list"
        params = {
            "page": 1,
            "page_size": min(max_items, 50),
            "market": "hk",
        }

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                headers=self._headers,
            ) as client:
                logger.info("正在从富途新闻 API 获取新闻: %s", url)
                response = await client.get(url, params=params)
                response.raise_for_status()

                data = response.json()
                return self._parse_response(data, max_items)

        except httpx.TimeoutException:
            logger.warning("富途新闻 API 请求超时 (timeout=%ds)", self.timeout)
            return []
        except httpx.HTTPStatusError as e:
            logger.error("富途新闻 API 返回错误状态码: %s", e.response.status_code)
            return []
        except httpx.RequestError as e:
            logger.error("富途新闻 API 请求失败: %s", e)
            return []
        except Exception as e:
            logger.error("富途新闻 API 未知错误: %s", e)
            return []

    def _parse_response(
        self, data: Dict[str, Any], max_items: int
    ) -> List[RawNewsItem]:
        """解析富途新闻 API 响应 JSON

        Args:
            data: API 返回的 JSON 数据
            max_items: 最大返回条数

        Returns:
            RawNewsItem 列表
        """
        items: List[RawNewsItem] = []

        # 尝试从常见的 JSON 结构中提取新闻列表
        news_list = self._extract_news_list(data)
        if not news_list:
            logger.warning("富途新闻 API 响应中未找到新闻列表")
            return []

        for raw in news_list[:max_items]:
            try:
                item = self._convert_to_raw_news_item(raw)
                if item:
                    items.append(item)
            except Exception as e:
                logger.warning("解析单条新闻失败，跳过: %s", e)
                continue

        logger.info("从富途新闻 API 获取到 %d 条新闻", len(items))
        return items

    def _extract_news_list(self, data: Dict[str, Any]) -> List[Dict]:
        """从 API 响应中提取新闻列表

        富途 API 响应结构可能为:
        - {"data": {"list": [...]}}
        - {"data": {"items": [...]}}
        - {"data": [...]}
        - {"list": [...]}
        """
        if not isinstance(data, dict):
            return []

        # 优先尝试 data.list
        inner = data.get("data", data)
        if isinstance(inner, dict):
            for key in ("list", "items", "news"):
                result = inner.get(key)
                if isinstance(result, list):
                    return result
        elif isinstance(inner, list):
            return inner

        return []

    def _convert_to_raw_news_item(
        self, raw: Dict[str, Any]
    ) -> Optional[RawNewsItem]:
        """将单条富途新闻 JSON 转换为 RawNewsItem

        Args:
            raw: 单条新闻的 JSON 字典

        Returns:
            RawNewsItem 或 None（如果缺少必要字段）
        """
        title = str(raw.get("title", "")).strip()
        if not title:
            return None

        news_url = str(raw.get("url", raw.get("news_url", ""))).strip()
        news_id = self._generate_news_id(title, news_url)

        summary = str(raw.get("summary", raw.get("brief", ""))).strip()
        source = str(raw.get("source", raw.get("src", "富途牛牛"))).strip()
        publish_time = str(
            raw.get("publish_time", raw.get("create_time", ""))
        ).strip()
        image_url = str(raw.get("image_url", raw.get("img", ""))).strip()
        is_pinned = bool(raw.get("is_top", raw.get("is_pinned", False)))

        return RawNewsItem(
            news_id=news_id,
            title=title,
            summary=summary,
            source=source,
            publish_time=publish_time,
            news_url=news_url,
            image_url=image_url,
            is_pinned=is_pinned,
        )

    @staticmethod
    def _generate_news_id(title: str, url: str) -> str:
        """生成新闻唯一 ID（与 NewsCrawler._generate_news_id 逻辑一致）"""
        content = f"{title}_{url}"
        return hashlib.md5(content.encode()).hexdigest()[:16]
