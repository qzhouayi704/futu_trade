#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ticker 推送处理器

注册到 OpenQuoteContext，接收富途推送的实时逐笔成交数据。
将推送数据写入 ticker_df_cache 并喂给 MomentumEngine。
"""

import logging
import threading
import time
from typing import Optional

from ..utils.trade_time import (
    futu_trade_date,
    futu_trade_timestamp,
    normalize_futu_trade_time,
)

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

    # 落库攒批参数：SDK 推送线程绝不做磁盘 I/O，只进内存缓冲；
    # 由独立 flusher 线程周期(或攒满被唤醒)经 DatabaseWriteQueue 批量落库
    _DB_FLUSH_INTERVAL = 3.0     # flusher 空闲唤醒周期（秒）
    _DB_FLUSH_MAX_ROWS = 1000    # 缓冲到量立即唤醒 flusher
    _DB_BUFFER_HARD_CAP = 50000  # DB 长时间不可写时的内存保护上限（丢最旧）

    def __init__(self):
        if FUTU_AVAILABLE:
            super().__init__()
        self._container = None
        self._tick_count = 0
        self._last_log_time = 0
        self._stocks_seen = set()
        # 逐笔落库攒批缓冲（见类常量注释）
        self._db_buffer: list = []
        self._db_buffer_lock = threading.Lock()
        self._db_flush_event = threading.Event()
        self._db_flusher: Optional[threading.Thread] = None
        self._db_write_fail_log_time = 0.0

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

            from ..utils.market_helper import MarketTimeHelper
            market = MarketTimeHelper.get_market_from_code(stock_code)
            market_day = MarketTimeHelper.get_market_today(market)

            for _, row in df.iterrows():
                trade_time = normalize_futu_trade_time(row.get('time'))
                trade_day = futu_trade_date(trade_time)
                if trade_day is not None and trade_day != market_day:
                    continue
                trade_ts = futu_trade_timestamp(trade_time, market)
                ticker_data = {
                    'price': row.get('price', 0),
                    'volume': row.get('volume', 0),
                    'turnover': row.get('turnover', 0),
                    'ticker_direction': row.get('ticker_direction', 'NEUTRAL'),
                    'timestamp': int((trade_ts or time.time()) * 1000),
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
            # 交易时段守卫：非本市场交易时段(周末/盘后/节假日/凌晨美股段)的推送不计入
            # 当日主力资金累计——否则富途休市残留/回放推送会污染累加器,使看板/信号流在
            # 非交易日凭散单冒出"主力流入"等假数据。
            from ..utils.market_helper import MarketTimeHelper
            market = MarketTimeHelper.get_market_from_code(stock_code)
            if not MarketTimeHelper.is_market_trading(market):
                return
            market_day = MarketTimeHelper.get_market_today(market)
            for _, row in df.iterrows():
                trade_time = normalize_futu_trade_time(row.get('time'))
                trade_day = futu_trade_date(trade_time)
                if trade_day is not None and trade_day != market_day:
                    continue
                price = float(row.get('price', 0) or 0)
                volume = int(row.get('volume', 0) or 0)
                if price <= 0 or volume <= 0:
                    continue
                turnover = float(row.get('turnover', 0) or 0) or price * volume
                # 传业务键字段去重：同一笔成交(成交时间,价,量,向)只计一次，挡补发/回放
                acc.on_tick(stock_code, turnover,
                            row.get('ticker_direction', 'NEUTRAL'),
                            now=futu_trade_timestamp(trade_time, market),
                            trade_time=trade_time, price=price, volume=volume)
        except Exception as e:
            logger.debug(f"[TickerPush] 喂逐笔资金累加器失败: {e}")

    def _persist_to_db(self, stock_code: str, df):
        """将推送的逐笔数据攒批落库到 ticker_data 表

        本方法运行在富途 SDK 推送线程上，只做行构造 + 内存缓冲（无磁盘 I/O），
        实际写库由 `_db_flush_loop` flusher 线程经 DatabaseWriteQueue 串行执行。
        """
        if not self._container:
            return
        try:
            from ..utils.market_helper import MarketTimeHelper

            market = MarketTimeHelper.get_market_from_code(stock_code)
            fallback_day = MarketTimeHelper.get_market_today(market)
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
                trade_time = normalize_futu_trade_time(row.get('time'))
                trade_date = futu_trade_date(trade_time) or fallback_day

                rows.append((stock_code, price, volume, turnover, direction,
                             ts_ms, trade_date, sequence, trade_time))

            if rows:
                self._enqueue_rows(rows)
        except Exception as e:
            logger.debug(f"[TickerPush] 逐笔行构造失败: {e}")

    # ---------- 落库攒批（SDK 线程只 append，flusher 线程写库） ----------

    def _enqueue_rows(self, rows: list):
        """SDK 推送线程入口：入内存缓冲并按需唤醒 flusher，绝不做磁盘 I/O。"""
        dropped = 0
        with self._db_buffer_lock:
            overflow = len(self._db_buffer) + len(rows) - self._DB_BUFFER_HARD_CAP
            if overflow > 0:
                dropped = min(overflow, len(self._db_buffer))
                del self._db_buffer[:dropped]
            self._db_buffer.extend(rows)
            buffered = len(self._db_buffer)
        if dropped:
            self._warn_throttled(
                f"[TickerPush] 落库缓冲超过 {self._DB_BUFFER_HARD_CAP} 条，"
                f"已丢弃最旧 {dropped} 条（DB 可能长时间不可写）"
            )
        self._ensure_flusher()
        if buffered >= self._DB_FLUSH_MAX_ROWS:
            self._db_flush_event.set()

    def _ensure_flusher(self):
        """懒启动 flusher 守护线程（幂等）。"""
        if self._db_flusher is not None and self._db_flusher.is_alive():
            return
        with self._db_buffer_lock:
            if self._db_flusher is not None and self._db_flusher.is_alive():
                return
            self._db_flusher = threading.Thread(
                target=self._db_flush_loop, name="ticker-db-flusher", daemon=True
            )
            self._db_flusher.start()

    def _db_flush_loop(self):
        """flusher 线程主循环：周期或被唤醒时批量落库。"""
        while True:
            self._db_flush_event.wait(timeout=self._DB_FLUSH_INTERVAL)
            self._db_flush_event.clear()
            try:
                self._flush_db_buffer()
            except Exception as e:
                self._warn_throttled(f"[TickerPush] flusher 异常: {e}")

    def _flush_db_buffer(self):
        """把缓冲中的逐笔批量写入 ticker_data（经写队列串行化）。

        失败时整批塞回缓冲等待下轮重试——ticker_data 唯一键 + INSERT OR IGNORE
        保证重试幂等；缓冲总量受 _DB_BUFFER_HARD_CAP 保护。
        """
        with self._db_buffer_lock:
            if not self._db_buffer:
                return
            rows, self._db_buffer = self._db_buffer, []

        db = getattr(self._container, 'db_manager', None) if self._container else None
        if not db:
            self._requeue_rows(rows)
            return

        from ..database.queries.ticker_queries import TickerQueries

        try:
            queries = TickerQueries(db.conn_manager)
            if db.write_queue.is_running:
                db.write_queue.submit(
                    queries.insert_ticker_batch, rows
                ).result(timeout=30.0)
            else:
                queries.insert_ticker_batch(rows)
        except Exception as e:
            self._requeue_rows(rows)
            self._warn_throttled(f"[TickerPush] 逐笔落库失败({len(rows)}条)，已回缓冲重试: {e}")

    def _requeue_rows(self, rows: list):
        """失败批次塞回缓冲头部（保持时间序），并执行内存上限保护。"""
        with self._db_buffer_lock:
            self._db_buffer[:0] = rows
            excess = len(self._db_buffer) - self._DB_BUFFER_HARD_CAP
            if excess > 0:
                del self._db_buffer[:excess]

    def _warn_throttled(self, msg: str):
        """落库类异常升为 warning，60s 内重复只降级 debug 防刷屏。"""
        now = time.time()
        if now - self._db_write_fail_log_time >= 60:
            self._db_write_fail_log_time = now
            logger.warning(msg)
        else:
            logger.debug(msg)

