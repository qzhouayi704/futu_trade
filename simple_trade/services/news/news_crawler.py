#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新闻抓取服务
使用 Playwright 抓取富途新闻页面
"""

import sys
import asyncio
import logging
import hashlib
import concurrent.futures
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime

try:
    from playwright.async_api import async_playwright, Browser, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False


@dataclass
class RawNewsItem:
    """原始新闻数据"""
    news_id: str
    title: str
    summary: str
    source: str
    publish_time: str
    news_url: str
    image_url: str = ""
    is_pinned: bool = False


class NewsCrawler:
    """新闻抓取器"""

    NEWS_URL = "https://news.futunn.com/hk/main"
    TIMEOUT = 60000  # 增加到 60 秒
    WAIT_TIMEOUT = 10000  # 等待特定元素的超时时间

    def __init__(self, debug: bool = False):
        self.logger = logging.getLogger(__name__)
        self.debug = debug  # 调试模式：显示浏览器窗口

    def is_available(self) -> bool:
        """检查依赖是否可用"""
        return PLAYWRIGHT_AVAILABLE and BS4_AVAILABLE

    async def crawl_news(self, max_items: int = 50) -> List[RawNewsItem]:
        """抓取新闻列表"""
        if not self.is_available():
            self.logger.error("Playwright 或 BeautifulSoup 未安装")
            return []

        # Windows 平台需要在单独线程中运行 Playwright
        # 因为 uvicorn 使用的 SelectorEventLoop 不支持子进程
        if sys.platform == 'win32':
            return await self._crawl_news_in_thread(max_items)
        else:
            return await self._crawl_news_impl(max_items)

    def _run_playwright_sync(self, max_items: int) -> List[RawNewsItem]:
        """在新的事件循环中同步运行 Playwright（供线程池使用）"""
        # 创建新的 ProactorEventLoop（支持子进程）
        if sys.platform == 'win32':
            loop = asyncio.ProactorEventLoop()
        else:
            loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self._crawl_news_impl(max_items))
        finally:
            loop.close()

    async def _crawl_news_in_thread(self, max_items: int) -> List[RawNewsItem]:
        """在线程池中运行 Playwright"""
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            return await loop.run_in_executor(
                executor,
                self._run_playwright_sync,
                max_items
            )

    async def _crawl_news_impl(self, max_items: int) -> List[RawNewsItem]:
        """实际的 Playwright 抓取实现"""
        news_items = []

        async with async_playwright() as p:
            # 调试模式下显示浏览器窗口
            browser = await p.chromium.launch(headless=not self.debug)
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/120.0.0.0 Safari/537.36'
            )

            # 调试模式下不拦截资源，以便查看完整页面
            if not self.debug:
                async def route_handler(route):
                    resource_type = route.request.resource_type
                    if resource_type in ['image', 'stylesheet', 'font', 'media']:
                        await route.abort()
                    else:
                        await route.continue_()
                await context.route('**/*', route_handler)

            page = await context.new_page()

            try:
                # 第一阶段：基本页面加载
                self.logger.info(f"正在访问: {self.NEWS_URL}")
                await page.goto(self.NEWS_URL, timeout=self.TIMEOUT, wait_until='domcontentloaded')
                self.logger.info("页面基本内容已加载")

                # 第二阶段：等待新闻内容出现（而不是等待所有网络请求完成）
                try:
                    # 尝试等待新闻列表容器出现
                    await page.wait_for_selector('div[class*="news"], article, .news-list', timeout=self.WAIT_TIMEOUT)
                    self.logger.info("新闻内容已加载")
                except Exception as e:
                    self.logger.warning(f"等待新闻容器超时，尝试继续: {e}")

                # 给动态内容一点时间渲染
                await asyncio.sleep(2)

                # 第三阶段：点击"显示更多"按钮并滚动页面加载更多内容
                self.logger.info(f"开始加载更多新闻（目标: {max_items} 条）")
                await self._load_more_news(page, max_items)

                # 获取页面HTML
                html_content = await page.content()

                # 调试模式下保存HTML到文件
                if self.debug:
                    import os
                    debug_file = os.path.join('logs', 'news_page_debug.html')
                    os.makedirs('logs', exist_ok=True)
                    with open(debug_file, 'w', encoding='utf-8') as f:
                        f.write(html_content)
                    self.logger.info(f"调试模式：HTML已保存到 {debug_file}")

                news_items = self._parse_news_html(html_content, max_items)

                self.logger.info(f"成功抓取 {len(news_items)} 条新闻")

            except Exception as e:
                error_msg = str(e)
                error_type = type(e).__name__

                # 识别常见错误类型并提供友好提示
                if "Timeout" in error_msg:
                    friendly_msg = "网络超时：无法在规定时间内加载富途新闻页面，请检查网络连接或稍后重试"
                elif "net::ERR" in error_msg or "NetworkError" in error_type:
                    friendly_msg = "网络错误：无法连接到富途新闻网站，请检查网络连接"
                elif "Target closed" in error_msg:
                    friendly_msg = "浏览器异常关闭，请重试"
                else:
                    friendly_msg = f"抓取失败：{error_msg}"

                self.logger.error(f"抓取新闻失败 [{error_type}]: {error_msg}")

                # 返回详细错误信息
                raise Exception(friendly_msg)
            finally:
                await browser.close()

        return news_items

    async def crawl_news_with_retry(
        self,
        max_items: int = 50,
        max_retries: int = 3
    ) -> List[RawNewsItem]:
        """带重试的新闻抓取"""
        last_error = None

        for attempt in range(max_retries):
            try:
                self.logger.info(f"开始抓取新闻 (尝试 {attempt + 1}/{max_retries})")
                result = await self.crawl_news(max_items)

                if result:
                    self.logger.info(f"抓取成功: {len(result)} 条新闻")
                    return result
                else:
                    self.logger.warning(f"抓取结果为空 (尝试 {attempt + 1}/{max_retries})")

            except Exception as e:
                last_error = e
                self.logger.warning(f"抓取失败 (尝试 {attempt + 1}/{max_retries}): {e}")

                if attempt < max_retries - 1:
                    # 指数退避
                    wait_time = 2 ** attempt
                    self.logger.info(f"等待 {wait_time} 秒后重试...")
                    await asyncio.sleep(wait_time)

        # 所有重试都失败
        if last_error:
            raise last_error
        else:
            raise Exception("抓取失败：未获取到任何新闻内容")

    async def _load_more_news(self, page, target_count: int):
        """加载更多新闻（点击"加载更多"按钮并滚动）

        Args:
            page: Playwright页面对象
            target_count: 目标新闻数量
        """
        # 先检查当前页面的链接数量
        initial_link_count = await page.evaluate('document.querySelectorAll("a[href]").length')
        self.logger.info(f"初始页面有 {initial_link_count} 个链接")

        # 尝试点击"加载更多"按钮
        try:
            # 使用精确的选择器（根据实际页面结构）
            load_more_selectors = [
                'button.btn-type_primary.btn-share_rect',  # 精确匹配class
                'button:has-text("加載更多")',  # 繁体中文
                'button:has-text("加载更多")',  # 简体中文
            ]

            button_clicked = False
            for selector in load_more_selectors:
                try:
                    # 等待按钮出现
                    button = await page.wait_for_selector(selector, timeout=3000, state='visible')
                    if button:
                        self.logger.info(f"找到'加载更多'按钮（选择器: {selector}）")

                        # 滚动到按钮位置
                        await button.scroll_into_view_if_needed()
                        await asyncio.sleep(0.5)

                        # 点击按钮
                        await button.click()
                        button_clicked = True
                        self.logger.info("已点击'加载更多'按钮，等待内容加载...")

                        # 等待新内容开始加载
                        await asyncio.sleep(2)

                        # 检查链接数量是否增加
                        new_link_count = await page.evaluate('document.querySelectorAll("a[href]").length')
                        self.logger.info(f"点击后页面有 {new_link_count} 个链接（+{new_link_count - initial_link_count}）")
                        break
                except Exception as e:
                    self.logger.debug(f"尝试选择器 '{selector}' 失败: {e}")
                    continue

            if not button_clicked:
                self.logger.warning("未找到'加载更多'按钮，直接尝试滚动")

        except Exception as e:
            self.logger.warning(f"点击'加载更多'按钮过程出错: {e}")

        # 点击按钮后，进行滚动以加载更多内容
        self.logger.info("开始滚动页面以加载更多内容")
        await self._scroll_to_load_more(page, target_count)

    async def _scroll_to_load_more(self, page, target_count: int):
        """滚动页面以加载更多内容

        Args:
            page: Playwright页面对象
            target_count: 目标新闻数量
        """
        # 先检查当前页面的链接数量
        initial_link_count = await page.evaluate('document.querySelectorAll("a[href]").length')
        self.logger.info(f"滚动前页面有 {initial_link_count} 个链接")

        # 如果初始链接数量已经足够，可能不需要滚动
        if initial_link_count > target_count * 2:
            self.logger.info(f"初始链接数量充足（{initial_link_count} > {target_count * 2}），尝试少量滚动")
            max_scrolls = 3  # 只滚动3次
        else:
            max_scrolls = 10  # 最多滚动10次

        scroll_pause = 1.5  # 每次滚动后等待1.5秒
        no_change_count = 0  # 连续无变化次数

        for i in range(max_scrolls):
            # 获取当前页面高度和链接数
            prev_height = await page.evaluate('document.body.scrollHeight')
            prev_link_count = await page.evaluate('document.querySelectorAll("a[href]").length')

            # 滚动到页面底部
            await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            self.logger.info(f"第 {i+1} 次滚动，等待新内容加载...")

            # 等待新内容加载
            await asyncio.sleep(scroll_pause)

            # 获取新的页面高度和链接数
            new_height = await page.evaluate('document.body.scrollHeight')
            new_link_count = await page.evaluate('document.querySelectorAll("a[href]").length')

            # 检查是否有新内容加载
            if new_height == prev_height and new_link_count == prev_link_count:
                no_change_count += 1
                self.logger.info(f"页面高度和链接数未变化（连续 {no_change_count} 次）")

                # 连续2次无变化，认为已到达底部
                if no_change_count >= 2:
                    self.logger.info(f"连续无变化，确认已到达页面底部")
                    break
            else:
                no_change_count = 0  # 重置计数器
                self.logger.info(f"当前页面有 {new_link_count} 个链接（+{new_link_count - prev_link_count}）")

            # 如果链接数量足够多，可以停止滚动
            if new_link_count > target_count * 3:  # 预留一些余量
                self.logger.info(f"链接数量充足（{new_link_count} > {target_count * 3}），停止滚动")
                break

        final_link_count = await page.evaluate('document.querySelectorAll("a[href]").length')
        self.logger.info(f"滚动完成，共滚动 {min(i+1, max_scrolls)} 次，最终有 {final_link_count} 个链接")

    def _parse_news_html(
        self, html: str, max_items: int
    ) -> List[RawNewsItem]:
        """解析新闻HTML"""
        soup = BeautifulSoup(html, 'lxml')
        news_items = []

        self.logger.info(f"开始解析HTML，页面长度: {len(html)} 字符")

        # 尝试多种选择器匹配新闻卡片
        selectors = [
            'div[class*="news-item"]',
            'div[class*="article-item"]',
            'a[class*="news-card"]',
            'div[class*="card"]',
            'article',
        ]

        cards = []
        for selector in selectors:
            raw_cards = soup.select(selector)
            self.logger.info(f"选择器 '{selector}' 找到 {len(raw_cards)} 个原始元素")
            # 过滤隐藏元素
            cards = [c for c in raw_cards if not self._is_hidden(c)]
            if cards:
                self.logger.info(
                    f"✓ 使用选择器 '{selector}' 找到 {len(raw_cards)} 个元素，"
                    f"过滤后 {len(cards)} 个可见"
                )
                break
            else:
                self.logger.debug(f"✗ 选择器 '{selector}' 未找到可见元素")

        if not cards:
            self.logger.warning("所有主选择器都未找到元素，尝试备用方案...")
            # 备用方案：查找所有包含标题的链接
            raw_cards = soup.find_all('a', href=True)
            self.logger.info(f"找到 {len(raw_cards)} 个链接元素")
            cards = [
                c for c in raw_cards
                if c.get_text(strip=True)
                and len(c.get_text(strip=True)) > 10
                and not self._is_hidden(c)
            ]
            self.logger.info(f"备用方案过滤后找到 {len(cards)} 个有效链接")

        for card in cards[:max_items]:
            try:
                news_item = self._extract_news_from_element(card)
                if news_item and news_item.title:
                    news_items.append(news_item)
                    self.logger.debug(f"成功解析新闻: {news_item.title[:30]}...")
                else:
                    self.logger.debug(f"跳过无效新闻项: {card.get_text(strip=True)[:50]}")
            except Exception as e:
                self.logger.debug(f"解析新闻卡片失败: {e}")
                continue

        self.logger.info(f"HTML解析完成，成功提取 {len(news_items)} 条新闻")
        return news_items

    def _is_hidden(self, element) -> bool:
        """检查元素是否隐藏"""
        classes = element.get('class', [])
        if isinstance(classes, list):
            classes = ' '.join(classes)
        # 检查常见的隐藏类名
        hidden_patterns = ['dn', 'hidden', 'hide', 'invisible', 'display-none']
        return any(p in classes.lower() for p in hidden_patterns)

    def _extract_news_from_element(self, element) -> Optional[RawNewsItem]:
        """从HTML元素提取新闻数据"""
        # 提取标题
        title = ""
        title_selectors = ['h2', 'h3', '.title', '[class*="title"]', 'a']
        for sel in title_selectors:
            title_elem = element.select_one(sel) if hasattr(element, 'select_one') else None
            if title_elem:
                title = title_elem.get_text(strip=True)
                break
        if not title:
            title = element.get_text(strip=True)[:200]

        if not title or len(title) < 5:
            return None

        # 提取链接
        news_url = ""
        if element.name == 'a':
            news_url = element.get('href', '')
        else:
            link = element.select_one('a[href]')
            if link:
                news_url = link.get('href', '')

        if news_url and not news_url.startswith('http'):
            news_url = f"https://news.futunn.com{news_url}"

        # 生成唯一ID
        news_id = self._generate_news_id(title, news_url)

        # 提取来源
        source = ""
        source_selectors = ['.source', '[class*="source"]', '[class*="author"]']
        for sel in source_selectors:
            source_elem = element.select_one(sel)
            if source_elem:
                source = source_elem.get_text(strip=True)
                break
        if not source:
            source = "富途资讯"

        # 提取时间
        publish_time = ""
        time_selectors = ['time', '.time', '[class*="time"]', '[class*="date"]']
        for sel in time_selectors:
            time_elem = element.select_one(sel)
            if time_elem:
                publish_time = time_elem.get_text(strip=True)
                break

        # 提取图片
        image_url = ""
        img = element.select_one('img')
        if img:
            image_url = img.get('src', '') or img.get('data-src', '')

        # 检查是否置顶
        is_pinned = '置顶' in element.get_text() or '置頂' in element.get_text()

        return RawNewsItem(
            news_id=news_id,
            title=title,
            summary="",
            source=source,
            publish_time=publish_time,
            news_url=news_url,
            image_url=image_url,
            is_pinned=is_pinned
        )

    def _generate_news_id(self, title: str, url: str) -> str:
        """生成新闻唯一ID"""
        content = f"{title}_{url}"
        return hashlib.md5(content.encode()).hexdigest()[:16]

    def crawl_sync(self, max_items: int = 50) -> List[RawNewsItem]:
        """同步方式抓取新闻（带重试）"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self.crawl_news_with_retry(max_items, max_retries=3))
            loop.close()
            return result
        except Exception as e:
            self.logger.error(f"同步抓取失败: {e}")
            raise  # 重新抛出异常，让上层处理
