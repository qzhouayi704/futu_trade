#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量重新分析新闻（使用 Gemini）- 独立版本

使用方法:
    python scripts/reanalyze_news_standalone.py --limit 10 --dry-run
    python scripts/reanalyze_news_standalone.py --batch-size 10 --delay 10

注意：需要先安装 google-genai 包
    pip install google-genai
"""

import asyncio
import argparse
import json
import logging
import sqlite3
import sys
import io
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

# 设置 Windows 控制台编码
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 尝试导入 google.genai
try:
    from google import genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    print("错误: google.genai 未安装")
    print("请运行: pip install google-genai")
    exit(1)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class GeminiAnalysisResult:
    """Gemini 分析结果"""
    sentiment: str
    sentiment_score: float
    related_stocks: List[Dict[str, Any]] = field(default_factory=list)
    related_plates: List[Dict[str, Any]] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    summary: str = ""
    confidence: float = 0.0


class GeminiNewsAnalyzer:
    """Gemini 新闻分析器（内联版本）"""

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash-exp", timeout: int = 30):
        self.logger = logging.getLogger(__name__)
        self.api_key = api_key
        self.model_name = model
        self.timeout = timeout
        self.client = None

        if not GEMINI_AVAILABLE:
            self.logger.error("google.genai 未安装")
            return

        try:
            self.client = genai.Client(api_key=api_key)
            self.logger.info(f"Gemini 分析器初始化成功，模型: {model}")
        except Exception as e:
            self.logger.error(f"Gemini 分析器初始化失败: {e}")

    def is_available(self) -> bool:
        return GEMINI_AVAILABLE and self.client is not None

    async def analyze(self, title: str, content: str = "") -> Optional[GeminiAnalysisResult]:
        if not self.is_available():
            return None

        try:
            prompt = self._build_prompt(title, content)
            response = await self._call_gemini_api(prompt)

            if not response:
                return None

            result = self._parse_response(response)
            return result

        except Exception as e:
            self.logger.error(f"Gemini 分析失败: {e}")
            return None

    async def analyze_batch(self, news_list: List[Dict[str, Any]]) -> List[Optional[GeminiAnalysisResult]]:
        """批量分析多条新闻"""
        if not self.is_available():
            return [None] * len(news_list)

        try:
            prompt = self._build_batch_prompt(news_list)
            response = await self._call_gemini_api(prompt)

            if not response:
                return [None] * len(news_list)

            results = self._parse_batch_response(response, len(news_list))
            return results

        except Exception as e:
            self.logger.error(f"Gemini 批量分析失败: {e}")
            return [None] * len(news_list)

    def _build_prompt(self, title: str, content: str) -> str:
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
6. related_stocks: 提取新闻中提到的股票
7. related_plates: 提取相关的行业板块

注意：只返回 JSON 格式，不要添加任何其他文字
"""
        return prompt

    def _build_batch_prompt(self, news_list: List[Dict[str, Any]]) -> str:
        """构建批量分析的 prompt"""
        news_items = []
        for i, news in enumerate(news_list, 1):
            text = f"{news['title']}\n{news.get('summary', '')}" if news.get('summary') else news['title']
            news_items.append(f"新闻{i}：\n{text}")

        news_text = "\n\n".join(news_items)

        prompt = f"""你是一个专业的金融新闻分析师。请分析以下 {len(news_list)} 条新闻，为每条新闻提取关键信息。

{news_text}

请按照以下 JSON 数组格式返回分析结果（只返回 JSON，不要其他文字）：

[
  {{
    "news_index": 1,
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
  }},
  ... (为每条新闻返回一个对象)
]

分析要求：
1. news_index: 新闻序号（1到{len(news_list)}）
2. sentiment: 判断新闻对市场的整体影响（利好positive/利空negative/中性neutral）
3. sentiment_score: 情感强度，-1.0（极度利空）到 1.0（极度利好）
4. confidence: 分析的置信度，0.0-1.0
5. summary: 用一句话概括新闻核心内容
6. keywords: 提取3-5个关键词
7. related_stocks: 提取新闻中提到的股票（如果没有则返回空数组）
8. related_plates: 提取相关的行业板块（如果没有则返回空数组）

注意：
- 必须为所有 {len(news_list)} 条新闻都返回分析结果
- 只返回 JSON 数组格式，不要添加任何其他文字
- 确保 news_index 从 1 到 {len(news_list)} 依次对应
"""
        return prompt

    async def _call_gemini_api(self, prompt: str) -> Optional[str]:
        try:
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
                return None

            return response.text.strip()

        except Exception as e:
            self.logger.error(f"调用 Gemini API 失败: {e}")
            return None

    def _parse_response(self, response: str) -> GeminiAnalysisResult:
        try:
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0].strip()

            data = json.loads(json_str)

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

        except Exception as e:
            self.logger.error(f"解析 Gemini 响应失败: {e}")
            return GeminiAnalysisResult(
                sentiment="neutral",
                sentiment_score=0.0,
                confidence=0.0
            )

    def _parse_batch_response(self, response: str, expected_count: int) -> List[Optional[GeminiAnalysisResult]]:
        """解析批量分析的响应"""
        try:
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0].strip()

            data_list = json.loads(json_str)

            if not isinstance(data_list, list):
                self.logger.error("批量响应不是数组格式")
                return [None] * expected_count

            # 创建结果列表，按 news_index 排序
            results = [None] * expected_count
            for data in data_list:
                news_index = data.get("news_index", 0)
                if 1 <= news_index <= expected_count:
                    results[news_index - 1] = GeminiAnalysisResult(
                        sentiment=data.get("sentiment", "neutral"),
                        sentiment_score=float(data.get("sentiment_score", 0.0)),
                        confidence=float(data.get("confidence", 0.0)),
                        summary=data.get("summary", ""),
                        keywords=data.get("keywords", []),
                        related_stocks=data.get("related_stocks", []),
                        related_plates=data.get("related_plates", [])
                    )

            return results

        except Exception as e:
            self.logger.error(f"解析批量 Gemini 响应失败: {e}")
            return [None] * expected_count


class SimpleNewsQueries:
    """简化的新闻查询类"""

    def __init__(self, db_path):
        self.db_path = db_path

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def get_all_news_for_reanalysis(self, limit=None):
        conn = self.get_connection()
        cursor = conn.cursor()

        sql = '''
            SELECT id, news_id, title, summary
            FROM news
            ORDER BY publish_time DESC
        '''
        if limit:
            sql += f' LIMIT {limit}'

        cursor.execute(sql)
        rows = cursor.fetchall()
        conn.close()

        return [
            {'id': row[0], 'news_id': row[1], 'title': row[2], 'summary': row[3]}
            for row in rows
        ]

    def update_news_analysis(self, news_id, sentiment, sentiment_score):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE news SET sentiment = ?, sentiment_score = ? WHERE id = ?',
            (sentiment, sentiment_score, news_id)
        )
        conn.commit()
        conn.close()

    def delete_news_stocks(self, news_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM news_stocks WHERE news_id = ?', (news_id,))
        conn.commit()
        conn.close()

    def delete_news_plates(self, news_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM news_plates WHERE news_id = ?', (news_id,))
        conn.commit()
        conn.close()

    def save_news_stock(self, news_id, stock_data):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT OR REPLACE INTO news_stocks (news_id, stock_code, stock_name, impact_type) VALUES (?, ?, ?, ?)',
            (news_id, stock_data.get('stock_code'), stock_data.get('stock_name'), stock_data.get('impact_type'))
        )
        conn.commit()
        conn.close()

    def save_news_plate(self, news_id, plate_data):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT OR REPLACE INTO news_plates (news_id, plate_code, plate_name, impact_type) VALUES (?, ?, ?, ?)',
            (news_id, plate_data.get('plate_code'), plate_data.get('plate_name'), plate_data.get('impact_type'))
        )
        conn.commit()
        conn.close()


async def reanalyze_news_batch(news_list, gemini_analyzer, news_queries, batch_size=10, delay=40.0, dry_run=False):
    total = len(news_list)
    success_count = 0
    failed_count = 0
    failed_ids = []

    print(f"\n{'=' * 80}")
    print(f"批量重新分析新闻（使用 Gemini）")
    print(f"{'=' * 80}")
    print(f"总新闻数: {total} 条")
    print(f"批次大小: {batch_size} 条/批")
    print(f"批次间隔: {delay} 秒")
    print(f"模式: {'试运行（不更新数据库）' if dry_run else '正式运行'}")
    print(f"{'=' * 80}\n")

    # 按批次处理
    num_batches = (total + batch_size - 1) // batch_size

    for batch_idx in range(num_batches):
        start_idx = batch_idx * batch_size
        end_idx = min(start_idx + batch_size, total)
        batch_news = news_list[start_idx:end_idx]

        print(f"\n批次 {batch_idx + 1}/{num_batches} (新闻 {start_idx + 1}-{end_idx})")
        print(f"{'=' * 80}")

        try:
            # 批量分析
            print(f"正在分析 {len(batch_news)} 条新闻...")
            results = await gemini_analyzer.analyze_batch(batch_news)

            # 处理每条新闻的结果
            for i, (news, analysis) in enumerate(zip(batch_news, results), start=start_idx + 1):
                try:
                    if not analysis:
                        print(f"[{i}/{total}] ✗ {news['title'][:40]}... - Gemini 分析返回空结果")
                        failed_count += 1
                        failed_ids.append(news['id'])
                        continue

                    print(f"[{i}/{total}] ✓ {news['title'][:40]}...")
                    print(f"         情感: {analysis.sentiment}, 分数: {analysis.sentiment_score:.2f}")
                    print(f"         相关股票: {len(analysis.related_stocks)} 个, 相关板块: {len(analysis.related_plates)} 个")

                    if not dry_run:
                        news_queries.update_news_analysis(news['id'], analysis.sentiment, analysis.sentiment_score)
                        news_queries.delete_news_stocks(news['id'])
                        news_queries.delete_news_plates(news['id'])

                        for stock in analysis.related_stocks:
                            news_queries.save_news_stock(news['id'], stock)

                        for plate in analysis.related_plates:
                            news_queries.save_news_plate(news['id'], plate)

                    success_count += 1

                except Exception as e:
                    print(f"[{i}/{total}] ✗ {news['title'][:40]}... - 处理失败: {str(e)}")
                    failed_count += 1
                    failed_ids.append(news['id'])
                    continue

        except Exception as e:
            print(f"批次分析失败: {str(e)}")
            # 批次失败时，标记该批次所有新闻为失败
            for news in batch_news:
                failed_count += 1
                failed_ids.append(news['id'])
            continue

        # 批次间延迟
        if batch_idx < num_batches - 1:
            print(f"\n批次完成，等待 {delay} 秒...\n")
            await asyncio.sleep(delay)

    print(f"\n{'=' * 80}")
    print(f"分析完成")
    print(f"{'=' * 80}")
    print(f"总计: {total} 条")
    print(f"成功: {success_count} 条")
    print(f"失败: {failed_count} 条")
    if failed_ids:
        print(f"失败ID: {failed_ids}")
    print(f"{'=' * 80}\n")


async def main():
    parser = argparse.ArgumentParser(description='批量重新分析新闻（使用 Gemini）')
    parser.add_argument('--limit', type=int, default=None, help='限制处理数量')
    parser.add_argument('--batch-size', type=int, default=10, help='批次大小（默认10条/批）')
    parser.add_argument('--delay', type=float, default=40.0, help='批次间隔（秒，默认40秒）')
    parser.add_argument('--dry-run', action='store_true', help='试运行模式')

    args = parser.parse_args()

    # 加载配置
    project_root = Path(__file__).parent.parent
    config_path = project_root / "simple_trade" / "config.json"
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    gemini_config = config.get('gemini', {})
    if not gemini_config or not gemini_config.get('enabled'):
        print("错误: Gemini 未启用")
        return

    db_path = project_root / config['database_path']
    news_queries = SimpleNewsQueries(str(db_path))

    gemini_analyzer = GeminiNewsAnalyzer(
        api_key=gemini_config['api_key'],
        model=gemini_config.get('model', 'gemini-2.0-flash-exp'),
        timeout=gemini_config.get('timeout', 30)
    )

    if not gemini_analyzer.is_available():
        print("错误: Gemini 分析器不可用")
        return

    print("正在加载新闻...")
    news_list = news_queries.get_all_news_for_reanalysis(limit=args.limit)
    print(f"加载完成，共 {len(news_list)} 条新闻\n")

    if not news_list:
        print("没有需要分析的新闻")
        return

    await reanalyze_news_batch(
        news_list,
        gemini_analyzer,
        news_queries,
        batch_size=args.batch_size,
        delay=args.delay,
        dry_run=args.dry_run
    )


if __name__ == "__main__":
    asyncio.run(main())
