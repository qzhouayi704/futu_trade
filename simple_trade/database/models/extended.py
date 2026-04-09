#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
扩展数据库模型
包含：Kline5MinDataModel, TradeSignalModel, PlateMatchLogModel, NewsModel
"""

from typing import Optional, List


class Kline5MinDataModel:
    """5分钟K线数据模型（用于日内交易回测）"""

    def __init__(
        self,
        kline_id: Optional[int] = None,
        stock_code: str = "",
        time_key: str = "",
        open_price: float = 0.0,
        close_price: float = 0.0,
        high_price: float = 0.0,
        low_price: float = 0.0,
        volume: int = 0,
        turnover: float = 0.0,
        turnover_rate: Optional[float] = None,
        created_at: Optional[str] = None
    ):
        self.id = kline_id
        self.stock_code = stock_code
        self.time_key = time_key
        self.open_price = open_price
        self.close_price = close_price
        self.high_price = high_price
        self.low_price = low_price
        self.volume = volume
        self.turnover = turnover
        self.turnover_rate = turnover_rate
        self.created_at = created_at

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'id': self.id,
            'stock_code': self.stock_code,
            'time_key': self.time_key,
            'open_price': self.open_price,
            'close_price': self.close_price,
            'high_price': self.high_price,
            'low_price': self.low_price,
            'volume': self.volume,
            'turnover': self.turnover,
            'turnover_rate': self.turnover_rate,
            'created_at': self.created_at
        }

    @classmethod
    def from_row(cls, row: tuple) -> 'Kline5MinDataModel':
        """从数据库行创建模型"""
        return cls(
            kline_id=row[0],
            stock_code=row[1],
            time_key=row[2],
            open_price=row[3] if len(row) > 3 else 0.0,
            close_price=row[4] if len(row) > 4 else 0.0,
            high_price=row[5] if len(row) > 5 else 0.0,
            low_price=row[6] if len(row) > 6 else 0.0,
            volume=row[7] if len(row) > 7 else 0,
            turnover=row[8] if len(row) > 8 else 0.0,
            turnover_rate=row[9] if len(row) > 9 else None,
            created_at=row[10] if len(row) > 10 else None
        )


class TradeSignalModel:
    """交易信号模型"""

    def __init__(
        self,
        signal_id: Optional[int] = None,
        stock_id: int = 0,
        signal_type: str = "",
        signal_price: float = 0.0,
        target_price: Optional[float] = None,
        stop_loss_price: Optional[float] = None,
        condition_text: str = "",
        strategy_id: Optional[str] = None,
        strategy_name: Optional[str] = None,
        is_executed: bool = False,
        executed_time: Optional[str] = None,
        created_at: Optional[str] = None
    ):
        self.id = signal_id
        self.stock_id = stock_id
        self.signal_type = signal_type
        self.signal_price = signal_price
        self.target_price = target_price
        self.stop_loss_price = stop_loss_price
        self.condition_text = condition_text
        self.strategy_id = strategy_id
        self.strategy_name = strategy_name
        self.is_executed = is_executed
        self.executed_time = executed_time
        self.created_at = created_at

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'id': self.id,
            'stock_id': self.stock_id,
            'signal_type': self.signal_type,
            'signal_price': self.signal_price,
            'target_price': self.target_price,
            'stop_loss_price': self.stop_loss_price,
            'condition_text': self.condition_text,
            'strategy_id': self.strategy_id,
            'strategy_name': self.strategy_name,
            'is_executed': self.is_executed,
            'executed_time': self.executed_time,
            'created_at': self.created_at
        }


class PlateMatchLogModel:
    """板块匹配日志模型"""

    def __init__(
        self,
        log_id: Optional[int] = None,
        plate_code: str = "",
        plate_name: str = "",
        matched: bool = False,
        category: str = "",
        match_score: int = 0,
        matched_keyword: str = "",
        match_type: str = "",
        created_at: Optional[str] = None
    ):
        self.id = log_id
        self.plate_code = plate_code
        self.plate_name = plate_name
        self.matched = matched
        self.category = category
        self.match_score = match_score
        self.matched_keyword = matched_keyword
        self.match_type = match_type
        self.created_at = created_at

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'id': self.id,
            'plate_code': self.plate_code,
            'plate_name': self.plate_name,
            'matched': self.matched,
            'category': self.category,
            'match_score': self.match_score,
            'matched_keyword': self.matched_keyword,
            'match_type': self.match_type,
            'created_at': self.created_at
        }


class NewsModel:
    """新闻模型"""

    def __init__(
        self,
        news_id: Optional[int] = None,
        external_id: str = "",
        title: str = "",
        summary: str = "",
        source: str = "",
        publish_time: Optional[str] = None,
        news_url: str = "",
        image_url: str = "",
        sentiment: str = "neutral",
        sentiment_score: float = 0.0,
        is_pinned: bool = False,
        created_at: Optional[str] = None,
        related_stocks: Optional[List[dict]] = None,
        related_plates: Optional[List[dict]] = None
    ):
        self.id = news_id
        self.news_id = external_id
        self.title = title
        self.summary = summary
        self.source = source
        self.publish_time = publish_time
        self.news_url = news_url
        self.image_url = image_url
        self.sentiment = sentiment
        self.sentiment_score = sentiment_score
        self.is_pinned = is_pinned
        self.created_at = created_at
        self.related_stocks = related_stocks or []
        self.related_plates = related_plates or []

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'id': self.id,
            'news_id': self.news_id,
            'title': self.title,
            'summary': self.summary,
            'source': self.source,
            'publish_time': self.publish_time,
            'news_url': self.news_url,
            'image_url': self.image_url,
            'sentiment': self.sentiment,
            'sentiment_score': self.sentiment_score,
            'is_pinned': self.is_pinned,
            'created_at': self.created_at,
            'related_stocks': self.related_stocks,
            'related_plates': self.related_plates
        }

    @classmethod
    def from_row(cls, row: tuple) -> 'NewsModel':
        """从数据库行创建模型"""
        return cls(
            news_id=row[0],
            external_id=row[1],
            title=row[2],
            summary=row[3] if len(row) > 3 else "",
            source=row[4] if len(row) > 4 else "",
            publish_time=row[5] if len(row) > 5 else None,
            news_url=row[6] if len(row) > 6 else "",
            image_url=row[7] if len(row) > 7 else "",
            sentiment=row[8] if len(row) > 8 else "neutral",
            sentiment_score=row[9] if len(row) > 9 else 0.0,
            is_pinned=bool(row[10]) if len(row) > 10 else False,
            created_at=row[11] if len(row) > 11 else None
        )
