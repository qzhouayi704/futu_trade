#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
逐笔成交数据服务

获取和缓存富途 get_rt_ticker 逐笔成交数据，
供 TickerAnalyzer 等分析模块复用。
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from futu import RET_OK, SubType

logger = logging.getLogger(__name__)


# ==================== 数据结构 ====================


@dataclass
class TickerRecord:
    """单笔成交记录"""
    time: str           # 成交时间
    price: float        # 成交价
    volume: int         # 成交量
    turnover: float     # 成交额
    direction: str      # 成交方向：BUY / SELL / NEUTRAL


@dataclass
class TickerData:
    """逐笔成交数据包"""
    stock_code: str
    records: List[TickerRecord]
    total_count: int
    updated_at: datetime = field(default_factory=datetime.now)


# ==================== 服务 ====================


class TickerService:
    """逐笔成交数据服务

    提供逐笔成交数据的获取与缓存，
    基于富途 get_rt_ticker API。
    """

    CACHE_TTL = 15  # 15秒缓存（逐笔成交数据变化快）

    def __init__(self, futu_client, state_manager=None, subscription_manager=None, db_manager=None):
        self._futu_client = futu_client
        self._state_manager = state_manager
        self._subscription_manager = subscription_manager
        self._db_manager = db_manager
        self._cache: Dict[str, TickerData] = {}
        self._momentum_engine = None  # 动量引擎回调（延迟注入）

    def _ensure_subscribed(self, stock_code: str) -> bool:
        """确保股票已订阅 TICKER 类型，委托给 SubscriptionManager"""
        # 通过 SubscriptionManager 检查订阅状态
        if self._subscription_manager and stock_code in self._subscription_manager.ticker_subscribed_stocks:
            return True

        if not self._subscription_manager:
            logger.warning(f"SubscriptionManager 未注入，无法订阅 {stock_code}")
            return False

        try:
            result = self._subscription_manager.subscribe_multi_types(
                [stock_code], [SubType.TICKER]
            )
            if result.get('subscribed_count', 0) > 0:
                logger.debug(f"订阅逐笔成交成功: {stock_code}")
                return True
            else:
                logger.debug(f"订阅逐笔成交失败: {stock_code}")
                return False
        except Exception as e:
            logger.error(f"订阅逐笔成交异常: {stock_code}, {e}")
            return False


    async def get_ticker_data(
        self, stock_code: str, num: int = 500
    ) -> Optional[TickerData]:
        """获取逐笔成交数据（带缓存）

        Args:
            stock_code: 股票代码，如 'HK.00700'
            num: 获取的成交笔数，最多1000笔

        Returns:
            TickerData 或 None（失败时）
        """
        # 1. 检查自身缓存
        cached = self._cache.get(stock_code)
        if cached and (datetime.now() - cached.updated_at).total_seconds() < self.CACHE_TTL:
            return cached

        # 2. 检查 TickerDataFrameCache（DataFrame 共享缓存）
        if self._state_manager is not None:
            try:
                shared_df = self._state_manager.ticker_df_cache.get(stock_code)
                if shared_df is not None:
                    result = self._parse_ticker_data(stock_code, shared_df)
                    if result:
                        self._cache[stock_code] = result
                        return result
            except Exception as e:
                logger.debug(f"读取 ticker_df_cache 失败 {stock_code}: {e}")

        # 3. 非交易时段跳过 API 调用，避免拉取过期数据
        from ....utils.market_helper import MarketTimeHelper
        now_time = datetime.now().time()
        if not MarketTimeHelper._is_hk_trading_time(now_time):
            logger.debug(f"非港股交易时段，跳过逐笔API: {stock_code}")
            return await self._read_ticker_from_db(stock_code, num)

        # 4. 回退到原有 futu API 调用
        try:
            loop = asyncio.get_event_loop()

            # 尝试订阅（即使失败也继续尝试获取，可能已被其他服务订阅）
            await loop.run_in_executor(
                None, self._ensure_subscribed, stock_code
            )

            # 调用富途 API 获取逐笔成交
            ret, data = await loop.run_in_executor(
                None, lambda: self._futu_client.get_rt_ticker(stock_code, num=num)
            )

            if ret != RET_OK or data is None or data.empty:
                logger.debug(f"富途API获取逐笔成交数据失败或为空: {stock_code}，尝试从数据库回读")
                return await self._read_ticker_from_db(stock_code, num)

            result = self._parse_ticker_data(stock_code, data)
            if result:
                self._cache[stock_code] = result
            return result

        except Exception as e:
            logger.error(f"获取逐笔成交数据异常 {stock_code}: {e}")
            return await self._read_ticker_from_db(stock_code, num)


    async def _read_ticker_from_db(self, stock_code: str, num: int = 500) -> Optional[TickerData]:
        """当API无数据时，从数据库回读当天的逐笔数据"""
        if not self._db_manager:
            return None
        try:
            from ....database.queries.ticker_queries import TickerQueries
            queries = TickerQueries(self._db_manager.conn_manager)
            loop = asyncio.get_event_loop()
            
            # 从DB读取当天的最新数据
            trade_date = datetime.now().strftime("%Y-%m-%d")
            db_records = await loop.run_in_executor(
                None, lambda: queries.get_ticker_data(stock_code, trade_date, num)
            )
            
            if not db_records:
                return None
                
            # 转换为 TickerRecord 列表
            records: List[TickerRecord] = []
            for row in db_records:
                timestamp_ms = row.get('timestamp', 0)
                time_str = datetime.fromtimestamp(timestamp_ms / 1000).strftime('%Y-%m-%d %H:%M:%S') if timestamp_ms else ""
                
                records.append(TickerRecord(
                    time=time_str,
                    price=float(row.get('price', 0)),
                    volume=int(row.get('volume', 0)),
                    turnover=float(row.get('turnover', 0)),
                    direction=row.get('direction', 'NEUTRAL'),
                ))
            
            # DB返回是降序的(最新的在前)，为了和API返回(升序)保持一致，进行反转
            records.reverse()
            
            logger.debug(f"{stock_code} 从数据库回读了 {len(records)} 条当日逐笔数据")
            
            result = TickerData(
                stock_code=stock_code,
                records=records,
                total_count=len(records),
                updated_at=datetime.now(),
            )
            # 存入缓存
            self._cache[stock_code] = result
            return result
        except Exception as e:
            logger.warning(f"从数据库回读逐笔数据失败 {stock_code}: {e}")
            return None


    def _parse_ticker_data(self, stock_code: str, data) -> Optional[TickerData]:
        """解析富途返回的逐笔成交 DataFrame"""
        try:
            records: List[TickerRecord] = []
            for _, row in data.iterrows():
                # 尝试多个可能的字段名（容错处理）
                direction_raw = (
                    row.get('ticker_direction') or
                    row.get('direction') or
                    row.get('side') or
                    'NEUTRAL'
                )
                # 标准化方向值
                direction = self._normalize_direction(direction_raw)

                records.append(TickerRecord(
                    time=str(row.get('time', '')),
                    price=float(row.get('price', 0)),
                    volume=int(row.get('volume', 0)),
                    turnover=float(row.get('turnover', 0)),
                    direction=direction,
                ))

            # 数据质量检查
            buy_count = sum(1 for r in records if r.direction == 'BUY')
            sell_count = sum(1 for r in records if r.direction == 'SELL')
            neutral_count = sum(1 for r in records if r.direction == 'NEUTRAL')

            if sell_count == 0 and buy_count == 0 and neutral_count > 0:
                logger.warning(
                    f"{stock_code} 所有 {neutral_count} 条逐笔记录方向都是 NEUTRAL，"
                    f"可能字段名不匹配。请检查富途API返回的字段名。"
                )

            logger.debug(
                f"{stock_code} 逐笔成交方向统计: "
                f"BUY={buy_count}, SELL={sell_count}, NEUTRAL={neutral_count}"
            )

            result = TickerData(
                stock_code=stock_code,
                records=records,
                total_count=len(records),
                updated_at=datetime.now(),
            )
            self._persist_ticker_data(stock_code, records)
            self._feed_momentum_engine(stock_code, records)
            return result
        except Exception as e:
            logger.error(f"解析逐笔成交数据异常 {stock_code}: {e}")
            return None

    def _persist_ticker_data(self, stock_code: str, records: List[TickerRecord]) -> None:
        """将解析后的逐笔数据异步写入数据库（失败不影响主流程）"""
        if not self._db_manager or not records:
            return
        try:
            from ....database.queries.ticker_queries import TickerQueries
            rows = []
            for r in records:
                # 从逐笔记录的真实成交时间解析 trade_date 和 timestamp
                parsed = self._parse_ticker_time(r.time)
                if parsed is None:
                    continue
                real_ts_ms, real_date = parsed
                rows.append((
                    stock_code,
                    r.price,
                    r.volume,
                    r.turnover if r.turnover else r.price * r.volume,
                    r.direction,
                    real_ts_ms,
                    real_date,
                ))
            if rows:
                queries = TickerQueries(self._db_manager.conn_manager)
                queries.insert_ticker_batch(rows)
        except Exception as e:
            logger.warning(f"逐笔数据落库失败 {stock_code}: {e}")

    @staticmethod
    def _parse_ticker_time(time_str: str):
        """解析逐笔成交时间字符串，返回 (timestamp_ms, trade_date_str) 或 None"""
        if not time_str:
            return None
        try:
            dt = datetime.strptime(time_str[:19], '%Y-%m-%d %H:%M:%S')
            ts_ms = int(dt.timestamp() * 1000)
            trade_date = dt.strftime('%Y-%m-%d')
            return ts_ms, trade_date
        except (ValueError, TypeError):
            return None

    def _normalize_direction(self, direction_raw) -> str:
        """标准化成交方向值为 BUY/SELL/NEUTRAL"""
        if not direction_raw:
            return 'NEUTRAL'

        direction_str = str(direction_raw).upper().strip()

        # 处理常见的方向值格式
        if direction_str in ('BUY', 'B', '1', 'BID'):
            return 'BUY'
        elif direction_str in ('SELL', 'S', '2', 'ASK'):
            return 'SELL'
        else:
            return 'NEUTRAL'

    def _feed_momentum_engine(self, stock_code: str, records: List[TickerRecord]) -> None:
        """将逐笔数据喂给动量引擎（失败不影响主流程）"""
        try:
            if self._momentum_engine is None:
                # 延迟获取动量引擎（避免循环依赖）
                try:
                    from ....dependencies import get_container
                    container = get_container()
                    if container and hasattr(container, 'momentum_engine'):
                        self._momentum_engine = container.momentum_engine
                except Exception:
                    return

            if self._momentum_engine is None:
                return

            for r in records:
                parsed = self._parse_ticker_time(r.time)
                ts_ms = parsed[0] if parsed else int(datetime.now().timestamp() * 1000)
                self._momentum_engine.on_ticker(stock_code, {
                    'price': r.price,
                    'volume': r.volume,
                    'turnover': r.turnover,
                    'ticker_direction': r.direction,
                    'timestamp': ts_ms,
                })
        except Exception as e:
            logger.debug(f"动量引擎喂数据失败 {stock_code}: {e}")

    def clear_cache(self):
        """清除缓存"""
        self._cache.clear()
