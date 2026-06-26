#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ticker 推送处理器

注册到 OpenQuoteContext，接收富途推送的实时逐笔成交数据。
将推送数据写入 ticker_df_cache 并喂给 MomentumEngine。
"""

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from futu import TickerHandlerBase, RET_OK
    FUTU_AVAILABLE = True
except ImportError:
    FUTU_AVAILABLE = False
    TickerHandlerBase = object
    RET_OK = None


class TickerPushHandler(TickerHandlerBase if FUTU_AVAILABLE else object):
    """逐笔成交推送回调处理器

    功能:
    1. 接收富途推送的 ticker 数据
    2. 写入 TickerDataFrameCache（供 TickerService 使用）
    3. 喂给 MomentumEngine（实时信号检测）
    """

    def __init__(self):
        if FUTU_AVAILABLE:
            super().__init__()
        self._container = None
        self._tick_count = 0
        self._last_log_time = 0
        self._stocks_seen = set()

    def set_container(self, container):
        """设置服务容器（延迟注入）"""
        self._container = container

    def on_recv_rsp(self, rsp_pb):
        """富途SDK回调入口"""
        if not FUTU_AVAILABLE:
            return
        try:
            ret_code, data = super().on_recv_rsp(rsp_pb)
            if ret_code != RET_OK or data is None or data.empty:
                return ret_code, data
            self._handle_ticker_push(data)
            return ret_code, data
        except Exception as e:
            logger.error(f"[TickerPush] on_recv_rsp异常: {e}")
            return RET_OK, None

    def _handle_ticker_push(self, df):
        """处理推送的ticker DataFrame"""
        if df is None or df.empty:
            return

        try:
            stock_code = df['code'].iloc[0] if 'code' in df.columns else None
            if not stock_code:
                return

            self._tick_count += len(df)
            self._stocks_seen.add(stock_code)

            # 1. 更新 TickerDataFrameCache
            self._update_cache(stock_code, df)

            # 2. 喂给 MomentumEngine
            self._feed_momentum(stock_code, df)

            # 2b. 喂给逐笔主力资金累加器（推送驱动，全天累计+滚动窗口；flag OFF 时零开销）
            self._feed_capital_accumulator(stock_code, df)

            # 3. 落库到 ticker_data 表（供资金流时间线等查询）
            self._persist_to_db(stock_code, df)

            # 定期日志
            now = time.time()
            if now - self._last_log_time > 300:  # 每5分钟
                logger.info(
                    f"[TickerPush] 已接收 {self._tick_count} 条推送, "
                    f"覆盖 {len(self._stocks_seen)} 只股票"
                )
                self._last_log_time = now

        except Exception as e:
            logger.error(f"[TickerPush] 处理推送失败: {e}")

    def _update_cache(self, stock_code: str, df):
        """更新 DataFrame 缓存"""
        if not self._container:
            return
        try:
            cache = getattr(self._container, 'ticker_df_cache', None)
            if cache:
                cache.set(stock_code, df)
        except Exception as e:
            logger.debug(f"[TickerPush] 更新缓存失败: {e}")

    def _feed_momentum(self, stock_code: str, df):
        """将推送数据喂给动量引擎"""
        if not self._container:
            return
        try:
            engine = getattr(self._container, 'momentum_engine', None)
            if not engine:
                return

            for _, row in df.iterrows():
                ticker_data = {
                    'price': row.get('price', 0),
                    'volume': row.get('volume', 0),
                    'turnover': row.get('turnover', 0),
                    'ticker_direction': row.get('ticker_direction', 'NEUTRAL'),
                    'timestamp': int(time.time() * 1000),
                }
                if ticker_data['price'] and ticker_data['volume']:
                    engine.on_ticker(stock_code, ticker_data)
        except Exception as e:
            logger.debug(f"[TickerPush] 喂动量引擎失败: {e}")

    def _feed_capital_accumulator(self, stock_code: str, df):
        """将推送逐笔喂给逐笔主力资金累加器（按成交额分级累加主力净流入）。"""
        if not self._container:
            return
        try:
            acc = getattr(self._container, 'tick_capital_accumulator', None)
            if not acc or not getattr(acc, 'enabled', False):
                return
            for _, row in df.iterrows():
                price = float(row.get('price', 0) or 0)
                volume = int(row.get('volume', 0) or 0)
                if price <= 0 or volume <= 0:
                    continue
                turnover = float(row.get('turnover', 0) or 0) or price * volume
                try:
                    seq = int(row.get('sequence', 0) or 0)
                except (TypeError, ValueError):
                    seq = 0
                # 传逐笔序号去重：断线补发/订阅缓存回放不重复累加主力净流入
                acc.on_tick(stock_code, turnover,
                            row.get('ticker_direction', 'NEUTRAL'),
                            sequence=seq or None)
        except Exception as e:
            logger.debug(f"[TickerPush] 喂逐笔资金累加器失败: {e}")

    def _persist_to_db(self, stock_code: str, df):
        """将推送的逐笔数据异步写入 ticker_data 表"""
        if not self._container:
            return
        try:
            db = getattr(self._container, 'db_manager', None)
            if not db:
                return

            from datetime import datetime as _dt
            from ..database.queries.ticker_queries import TickerQueries

            today_str = _dt.now().strftime('%Y-%m-%d')
            rows = []
            for _, row in df.iterrows():
                price = float(row.get('price', 0) or 0)
                volume = int(row.get('volume', 0) or 0)
                turnover = float(row.get('turnover', 0) or 0)
                direction = str(row.get('ticker_direction', 'NEUTRAL'))

                # 方向映射: 富途推送的方向字段转换
                if direction in ('BUY', 'BULL'):
                    direction = 'BUY'
                elif direction in ('SELL', 'BEAR'):
                    direction = 'SELL'
                else:
                    direction = 'NEUTRAL'

                if price <= 0 or volume <= 0:
                    continue

                ts_ms = int(time.time() * 1000)   # 本地接收时刻（不是成交时刻）
                if not turnover:
                    turnover = price * volume

                # 富途逐笔序号（去重唯一键）+ 真实成交时间字符串。
                # sequence 缺失/为 0 时存 NULL：NULL 互不相等，不会让无序号的逐笔互相误撞。
                try:
                    seq = int(row.get('sequence', 0) or 0)
                except (TypeError, ValueError):
                    seq = 0
                sequence = seq if seq > 0 else None
                trade_time = row.get('time') or None

                rows.append((stock_code, price, volume, turnover, direction,
                             ts_ms, today_str, sequence, trade_time))

            if rows:
                queries = TickerQueries(db.conn_manager)
                queries.insert_ticker_batch(rows)
        except Exception as e:
            logger.debug(f"[TickerPush] 落库失败: {e}")

