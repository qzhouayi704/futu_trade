#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新闻服务协调器
协调抓取、分析、存储等子服务
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from .news_crawler import NewsCrawler
from .news_analyzer import NewsAnalyzer
from .futu_news_fetcher import FutuNewsFetcher
from ...database.queries.news_queries import NewsQueries


class NewsService:
    """新闻服务"""

    def __init__(self, db_manager, config: Optional[Dict[str, Any]] = None, debug: bool = False):
        self.db_manager = db_manager
        self.logger = logging.getLogger(__name__)
        self.config = config or {}

        # 初始化子服务
        self.fetcher = FutuNewsFetcher()
        self.crawler = NewsCrawler(debug=debug)
        self.analyzer = NewsAnalyzer(db_manager, config=self.config)
        self.queries = NewsQueries(db_manager)

        # 状态
        self._is_crawling = False
        self._last_crawl_time: Optional[datetime] = None

    async def crawl_and_analyze(self, max_items: int = 50) -> Dict[str, Any]:
        """抓取并分析新闻（异步方法）"""
        if self._is_crawling:
            return {'success': False, 'message': '正在抓取中，请稍后'}

        self._is_crawling = True
        self.logger.info(f"开始抓取新闻，目标数量: {max_items}")

        result = {
            'success': False,
            'crawled_count': 0,
            'analyzed_count': 0,
            'new_count': 0,
            'source': '',
            'errors': []
        }

        try:
            # 优先使用富途 API
            raw_news = []
            source = 'futu_api'

            if self.fetcher.is_available():
                try:
                    raw_news = await self.fetcher.fetch_news(max_items)
                    if raw_news:
                        self.logger.info(f"富途 API 获取到 {len(raw_news)} 条新闻")
                except Exception as e:
                    self.logger.warning(f"富途 API 获取失败: {e}")

            # 回退到 Playwright
            if not raw_news:
                source = 'playwright'
                if self.crawler.is_available():
                    self.logger.info("回退到 Playwright 抓取新闻...")
                    raw_news = await self.crawler.crawl_news_with_retry(max_items, max_retries=3)
                else:
                    self.logger.warning("所有数据源均不可用")
                    return {
                        'success': False,
                        'message': '所有数据源均不可用',
                        **result
                    }

            result['source'] = source
            result['crawled_count'] = len(raw_news)
            self.logger.info(f"抓取完成（{source}），获取到 {len(raw_news)} 条原始新闻")

            if not raw_news:
                return {
                    'success': False,
                    'message': '未能抓取到任何新闻，可能是网络问题或页面结构变化',
                    **result
                }

            # 解析和分析
            self.logger.info("开始分析新闻内容...")
            for idx, item in enumerate(raw_news, 1):
                try:
                    # 检查是否已存在
                    if self.queries.news_exists(item.news_id):
                        self.logger.debug(f"[{idx}/{len(raw_news)}] 新闻已存在: {item.title[:30]}...")
                        continue

                    self.logger.debug(f"[{idx}/{len(raw_news)}] 分析新闻: {item.title[:30]}...")

                    # 分析新闻（异步调用）
                    analysis = await self.analyzer.analyze(item.title, item.summary)

                    # 保存新闻
                    news_data = {
                        'news_id': item.news_id,
                        'title': item.title,
                        'summary': item.summary,
                        'source': item.source,
                        'publish_time': item.publish_time,
                        'news_url': item.news_url,
                        'image_url': item.image_url,
                        'sentiment': analysis.sentiment,
                        'sentiment_score': analysis.sentiment_score,
                        'is_pinned': item.is_pinned
                    }

                    news_db_id = self.queries.save_news(news_data)
                    if not news_db_id:
                        self.logger.warning(f"保存新闻失败: {item.title[:30]}...")
                        continue

                    # 保存关联的股票
                    for stock in analysis.related_stocks:
                        self.queries.save_news_stock(news_db_id, stock)

                    # 保存关联的板块
                    for plate in analysis.related_plates:
                        self.queries.save_news_plate(news_db_id, plate)

                    result['new_count'] += 1
                    result['analyzed_count'] += 1
                    self.logger.info(f"[{idx}/{len(raw_news)}] 新增新闻: {item.title[:30]}...")

                except Exception as e:
                    error_msg = f"处理新闻失败: {str(e)}"
                    self.logger.error(error_msg)
                    result['errors'].append(error_msg)

            result['success'] = True
            self._last_crawl_time = datetime.now()

            self.logger.info(f"抓取分析完成 - 抓取: {result['crawled_count']}, 新增: {result['new_count']}")

        except Exception as e:
            error_msg = str(e)
            self.logger.error(f"抓取分析失败: {e}", exc_info=True)

            # 返回详细的错误信息
            result['message'] = error_msg
            result['error_type'] = type(e).__name__
            result['success'] = False
        finally:
            self._is_crawling = False

        return result

    def get_latest_news(self, limit: int = 20, hours: int = 0) -> List[Dict[str, Any]]:
        """获取最新新闻"""
        return self.queries.get_latest_news(limit, hours)

    def get_news_by_stock(self, stock_code: str, limit: int = 10) -> List[Dict]:
        """获取股票相关新闻"""
        return self.queries.get_news_by_stock(stock_code, limit)

    def get_news_by_sentiment(self, sentiment: str, limit: int = 20) -> List[Dict]:
        """按情感获取新闻"""
        return self.queries.get_news_by_sentiment(sentiment, limit)

    def get_hot_stocks_from_news(
        self, hours: int = 24, limit: int = 10
    ) -> List[Dict]:
        """从新闻中获取热门股票"""
        return self.queries.get_hot_stocks_from_news(hours, limit)

    def get_hot_plates_from_news(
        self, hours: int = 24, limit: int = 10
    ) -> List[Dict]:
        """从新闻中获取热门板块"""
        return self.queries.get_hot_plates_from_news(hours, limit)

    def get_investment_suggestions(self, limit: int = 5, hours: int = 24) -> Dict[str, Any]:
        """获取投资建议"""
        hot_stocks = self.queries.get_hot_stocks_from_news(hours=hours, limit=20)

        bullish = []
        bearish = []

        for stock in hot_stocks:
            if stock['positive_count'] > stock['negative_count']:
                bullish.append({
                    **stock,
                    'reason': self._generate_reason(stock, 'positive')
                })
            elif stock['negative_count'] > stock['positive_count']:
                bearish.append({
                    **stock,
                    'reason': self._generate_reason(stock, 'negative')
                })

        return {
            'bullish': bullish[:limit],
            'bearish': bearish[:limit],
            'generated_at': datetime.now().isoformat()
        }

    def _generate_reason(self, stock: Dict, sentiment: str) -> str:
        """生成投资建议原因"""
        if sentiment == 'positive':
            return f"近24小时有{stock['positive_count']}条利好新闻"
        else:
            return f"近24小时有{stock['negative_count']}条利空新闻"

    def get_status(self) -> Dict[str, Any]:
        """获取服务状态"""
        return {
            'is_crawling': self._is_crawling,
            'last_crawl_time': self._last_crawl_time.isoformat() if self._last_crawl_time else None,
            'futu_api_available': self.fetcher.is_available(),
            'crawler_available': self.crawler.is_available(),
            'gemini_available': (
                self.analyzer.gemini_analyzer is not None
                and self.analyzer.gemini_analyzer.is_available()
            )
        }

    async def reanalyze_news(self, limit: int = 50, batch_size: int = 50) -> Dict[str, Any]:
        """重新分析缺少关联数据的新闻（支持批量 Gemini 请求）

        Args:
            limit: 最大处理数量
            batch_size: 每批发送给 Gemini 的新闻数量
        """
        if self._is_crawling:
            return {'success': False, 'message': '正在抓取/分析中，请稍后'}

        self._is_crawling = True
        result = {'success': False, 'total': 0, 'skipped': 0, 'analyzed': 0, 'errors': []}

        try:
            all_news = self.queries.get_all_news_for_reanalysis(limit=limit)
            result['total'] = len(all_news)

            # 过滤出需要分析的新闻（无关联数据且未被 Gemini 分析过的）
            pending = []
            for news in all_news:
                news_id = news['id']
                has_stocks = bool(self.queries._get_news_stocks(news_id))
                has_plates = bool(self.queries._get_news_plates(news_id))
                if has_stocks or has_plates:
                    result['skipped'] += 1
                    continue
                pending.append(news)

            self.logger.info(f"待分析: {len(pending)} 条, 已跳过: {result['skipped']} 条")

            # 分批处理
            for i in range(0, len(pending), batch_size):
                batch = pending[i:i + batch_size]
                self.logger.info(f"处理批次 {i // batch_size + 1}, 共 {len(batch)} 条")

                try:
                    batch_results = await self.analyzer.analyze_batch(batch)

                    # 保存结果
                    for item in batch_results:
                        news_id = item['id']
                        analysis = item['result']
                        try:
                            self.queries.update_news_analysis(
                                news_id, analysis.sentiment, analysis.sentiment_score
                            )
                            for stock in analysis.related_stocks:
                                self.queries.save_news_stock(news_id, stock)
                            for plate in analysis.related_plates:
                                self.queries.save_news_plate(news_id, plate)
                            result['analyzed'] += 1
                        except Exception as e:
                            result['errors'].append(f"id={news_id}: {str(e)}")

                except Exception as e:
                    error_msg = f"批次 {i // batch_size + 1} 失败: {str(e)}"
                    self.logger.error(error_msg)
                    result['errors'].append(error_msg)

            result['success'] = True
        except Exception as e:
            result['message'] = str(e)
        finally:
            self._is_crawling = False

        return result
