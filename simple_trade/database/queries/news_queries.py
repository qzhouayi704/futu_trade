#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新闻数据库查询服务
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta


class NewsQueries:
    """新闻数据库查询服务"""

    def __init__(self, db_manager):
        self.db = db_manager
        self.logger = logging.getLogger(__name__)

    def save_news(self, news_data: Dict[str, Any]) -> Optional[int]:
        """保存新闻"""
        sql = '''
            INSERT OR REPLACE INTO news
            (news_id, title, summary, source, publish_time, news_url,
             image_url, sentiment, sentiment_score, is_pinned)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        '''
        params = (
            news_data.get('news_id'),
            news_data.get('title'),
            news_data.get('summary'),
            news_data.get('source'),
            news_data.get('publish_time'),
            news_data.get('news_url'),
            news_data.get('image_url'),
            news_data.get('sentiment', 'neutral'),
            news_data.get('sentiment_score', 0.0),
            news_data.get('is_pinned', False)
        )
        try:
            self.db.execute_insert(sql, params)
            # 获取插入的ID
            result = self.db.execute_query(
                "SELECT id FROM news WHERE news_id = ?",
                (news_data.get('news_id'),)
            )
            return result[0][0] if result else None
        except Exception as e:
            self.logger.error(f"保存新闻失败: {e}")
            return None

    def save_news_stock(self, news_db_id: int, stock_data: Dict[str, Any]) -> bool:
        """保存新闻-股票关联"""
        sql = '''
            INSERT OR REPLACE INTO news_stocks
            (news_id, stock_code, stock_name, impact_type)
            VALUES (?, ?, ?, ?)
        '''
        params = (
            news_db_id,
            stock_data.get('stock_code'),
            stock_data.get('stock_name'),
            stock_data.get('impact_type')
        )
        try:
            self.db.execute_insert(sql, params)
            return True
        except Exception as e:
            self.logger.error(f"保存新闻-股票关联失败: {e}")
            return False

    def save_news_plate(self, news_db_id: int, plate_data: Dict[str, Any]) -> bool:
        """保存新闻-板块关联"""
        sql = '''
            INSERT OR REPLACE INTO news_plates
            (news_id, plate_code, plate_name, impact_type)
            VALUES (?, ?, ?, ?)
        '''
        params = (
            news_db_id,
            plate_data.get('plate_code'),
            plate_data.get('plate_name'),
            plate_data.get('impact_type')
        )
        try:
            self.db.execute_insert(sql, params)
            return True
        except Exception as e:
            self.logger.error(f"保存新闻-板块关联失败: {e}")
            return False

    def news_exists(self, news_id: str) -> bool:
        """检查新闻是否已存在"""
        result = self.db.execute_query(
            "SELECT 1 FROM news WHERE news_id = ?",
            (news_id,)
        )
        return len(result) > 0

    def get_latest_news(self, limit: int = 20, hours: int = 0) -> List[Dict[str, Any]]:
        """获取最新新闻（支持时间过滤）"""
        sql = '''
            SELECT id, news_id, title, summary, source, publish_time,
                   news_url, image_url, sentiment, sentiment_score,
                   is_pinned, created_at
            FROM news
        '''

        # 添加时间过滤条件（使用 created_at 而非 publish_time，因为 publish_time 仅存储 HH:MM 格式）
        params = []
        if hours > 0:
            cutoff_time = datetime.now() - timedelta(hours=hours)
            sql += " WHERE created_at >= ?"
            params.append(cutoff_time.isoformat())

        sql += '''
            ORDER BY is_pinned DESC, publish_time DESC
            LIMIT ?
        '''
        params.append(limit)

        rows = self.db.execute_query(sql, tuple(params))
        news_list = []
        for row in rows:
            news = self._row_to_dict(row)
            news['related_stocks'] = self._get_news_stocks(row[0])
            news['related_plates'] = self._get_news_plates(row[0])
            news_list.append(news)
        return news_list

    def get_news_by_sentiment(
        self, sentiment: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """按情感类型获取新闻"""
        sql = '''
            SELECT id, news_id, title, summary, source, publish_time,
                   news_url, image_url, sentiment, sentiment_score,
                   is_pinned, created_at
            FROM news
            WHERE sentiment = ?
            ORDER BY publish_time DESC
            LIMIT ?
        '''
        rows = self.db.execute_query(sql, (sentiment, limit))
        news_list = []
        for row in rows:
            news = self._row_to_dict(row)
            news['related_stocks'] = self._get_news_stocks(row[0])
            news_list.append(news)
        return news_list

    def get_news_by_stock(
        self, stock_code: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """获取股票相关新闻"""
        sql = '''
            SELECT n.id, n.news_id, n.title, n.summary, n.source,
                   n.publish_time, n.news_url, n.image_url, n.sentiment,
                   n.sentiment_score, n.is_pinned, n.created_at
            FROM news n
            JOIN news_stocks ns ON n.id = ns.news_id
            WHERE ns.stock_code = ?
            ORDER BY n.publish_time DESC
            LIMIT ?
        '''
        rows = self.db.execute_query(sql, (stock_code, limit))
        return [self._row_to_dict(row) for row in rows]

    def get_hot_stocks_from_news(
        self, hours: int = 24, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """获取新闻中的热门股票"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        sql = '''
            SELECT ns.stock_code, ns.stock_name,
                   COUNT(*) as mention_count,
                   SUM(CASE WHEN ns.impact_type = 'positive' THEN 1 ELSE 0 END) as positive_count,
                   SUM(CASE WHEN ns.impact_type = 'negative' THEN 1 ELSE 0 END) as negative_count
            FROM news_stocks ns
            JOIN news n ON ns.news_id = n.id
            WHERE n.created_at >= ?
            GROUP BY ns.stock_code, ns.stock_name
            ORDER BY mention_count DESC
            LIMIT ?
        '''
        rows = self.db.execute_query(sql, (cutoff_time.isoformat(), limit))
        return [
            {
                'stock_code': row[0],
                'stock_name': row[1],
                'mention_count': row[2],
                'positive_count': row[3],
                'negative_count': row[4],
                'sentiment_score': (row[3] - row[4]) / row[2] if row[2] > 0 else 0
            }
            for row in rows
        ]

    def get_hot_plates_from_news(
        self, hours: int = 24, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """获取新闻中的热门板块"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        sql = '''
            SELECT MIN(np.plate_code) as plate_code, np.plate_name,
                   COUNT(*) as mention_count,
                   SUM(CASE WHEN np.impact_type = 'positive' THEN 1 ELSE 0 END) as positive_count,
                   SUM(CASE WHEN np.impact_type = 'negative' THEN 1 ELSE 0 END) as negative_count
            FROM news_plates np
            JOIN news n ON np.news_id = n.id
            WHERE n.created_at >= ?
            GROUP BY np.plate_name
            ORDER BY mention_count DESC
            LIMIT ?
        '''
        rows = self.db.execute_query(sql, (cutoff_time.isoformat(), limit))
        return [
            {
                'plate_code': row[0],
                'plate_name': row[1],
                'mention_count': row[2],
                'positive_count': row[3],
                'negative_count': row[4]
            }
            for row in rows
        ]

    def _get_news_stocks(self, news_db_id: int) -> List[Dict[str, Any]]:
        """获取新闻关联的股票"""
        sql = '''
            SELECT stock_code, stock_name, impact_type
            FROM news_stocks WHERE news_id = ?
        '''
        rows = self.db.execute_query(sql, (news_db_id,))
        return [
            {'stock_code': r[0], 'stock_name': r[1], 'impact_type': r[2]}
            for r in rows
        ]

    def _get_news_plates(self, news_db_id: int) -> List[Dict[str, Any]]:
        """获取新闻关联的板块"""
        sql = '''
            SELECT plate_code, plate_name, impact_type
            FROM news_plates WHERE news_id = ?
        '''
        rows = self.db.execute_query(sql, (news_db_id,))
        return [
            {'plate_code': r[0], 'plate_name': r[1], 'impact_type': r[2]}
            for r in rows
        ]

    def _row_to_dict(self, row: tuple) -> Dict[str, Any]:
        """将数据库行转换为字典"""
        return {
            'id': row[0],
            'news_id': row[1],
            'title': row[2],
            'summary': row[3],
            'source': row[4],
            'publish_time': row[5],
            'news_url': row[6],
            'image_url': row[7],
            'sentiment': row[8],
            'sentiment_score': row[9],
            'is_pinned': bool(row[10]),
            'created_at': row[11]
        }

    def update_news_analysis(self, news_db_id: int, sentiment: str, sentiment_score: float) -> bool:
        """更新新闻分析结果"""
        sql = '''
            UPDATE news
            SET sentiment = ?, sentiment_score = ?
            WHERE id = ?
        '''
        try:
            self.db.execute_update(sql, (sentiment, sentiment_score, news_db_id))
            return True
        except Exception as e:
            self.logger.error(f"更新新闻分析失败: {e}")
            return False

    def delete_news_stocks(self, news_db_id: int) -> bool:
        """删除新闻的股票关联"""
        sql = 'DELETE FROM news_stocks WHERE news_id = ?'
        try:
            self.db.execute_update(sql, (news_db_id,))
            return True
        except Exception as e:
            self.logger.error(f"删除新闻股票关联失败: {e}")
            return False

    def delete_news_plates(self, news_db_id: int) -> bool:
        """删除新闻的板块关联"""
        sql = 'DELETE FROM news_plates WHERE news_id = ?'
        try:
            self.db.execute_update(sql, (news_db_id,))
            return True
        except Exception as e:
            self.logger.error(f"删除新闻板块关联失败: {e}")
            return False

    def get_all_news_for_reanalysis(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """获取所有需要重新分析的新闻"""
        sql = '''
            SELECT id, news_id, title, summary
            FROM news
            ORDER BY id DESC
        '''
        if limit:
            sql += f' LIMIT {limit}'

        rows = self.db.execute_query(sql)
        return [
            {
                'id': row[0],
                'news_id': row[1],
                'title': row[2],
                'summary': row[3]
            }
            for row in rows
        ]
