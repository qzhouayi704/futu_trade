#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐笔分钟归档器

原始 ticker_data 体积巨大（~68万行/交易日，占库 90%+），故只滚动保留 7 天
（见 db_manager._auto_cleanup_old_data）。但盘中信号回测（择时/狙击/动量）都把逐笔
**聚合成分钟**来用，分钟级数据比原始逐笔小 5~7 倍，可长期保留。

本归档器在收盘后（及启动追赶）把每股每分钟聚合（价/高/低/主买额/主卖额/量）写入
`ticker_minute` 表，供长周期回测使用——活盘的 ticker_data 仍维持 7 天精简、不受影响。

幂等：归档元数据记录聚合口径版本；版本升级时自动重算现存原始日。当日只在收盘后
(>16:10)归档，避免盘中反复写。
"""

import asyncio
import logging
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime

logger = logging.getLogger("ticker_minute_archiver")

# ticker_minute 自身保留天数由 db_manager._auto_cleanup_old_data 控制(180天)。
_LOOP_INTERVAL_SEC = 3600  # 每小时巡检一次(幂等，只补缺失日 + 收盘后归档当日)
_ARCHIVE_VERSION = 2       # v2: 按真实 trade_time 归档，并跨错误 trade_date 去重
_WRITE_TIMEOUT_SEC = 60


class TickerMinuteArchiver:
    """把 ticker_data 聚合成分钟级 ticker_minute，供长周期回测。"""

    def __init__(self, container):
        self._container = container
        self._task = None
        self._running = False

    # ---------- 表 ----------

    @staticmethod
    def _ensure_table(conn):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ticker_minute (
                stock_code TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                minute TEXT NOT NULL,        -- HH:MM (HK)
                price REAL,                  -- 当分钟逐笔均价
                high REAL,
                low REAL,
                buy_amt REAL,                -- 主买成交额(direction=BUY)
                sell_amt REAL,               -- 主卖成交额(direction=SELL)
                volume REAL,
                PRIMARY KEY (stock_code, trade_date, minute)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tm_date ON ticker_minute(trade_date)")
        # 大单口径分钟归档（按每股门槛过滤，供多日·精确大单口径回测/标定，突破逐笔 7 天限制）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS capital_flow_minute (
                stock_code TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                minute TEXT NOT NULL,            -- HH:MM (HK)
                big_buy_amt REAL,                -- 大单(含超大,≥门槛)主买额
                big_sell_amt REAL,               -- 大单主卖额
                super_buy_amt REAL,              -- 超大单(≥超大门槛)主买额
                super_sell_amt REAL,             -- 超大单主卖额
                big_buy_count INTEGER,           -- 大单买入笔数
                big_sell_count INTEGER,          -- 大单卖出笔数
                big_order_threshold REAL,        -- 当时该股大单门槛(可溯源)
                PRIMARY KEY (stock_code, trade_date, minute)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cfm_date ON capital_flow_minute(trade_date)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ticker_minute_archive_meta (
                trade_date TEXT PRIMARY KEY,
                ticker_version INTEGER NOT NULL DEFAULT 0,
                capital_version INTEGER NOT NULL DEFAULT 0,
                ticker_source_max_id INTEGER NOT NULL DEFAULT 0,
                capital_source_max_id INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT
            )
        """)
        columns = {
            row[1] for row in conn.execute(
                "PRAGMA table_info(ticker_minute_archive_meta)"
            ).fetchall()
        }
        if "ticker_source_max_id" not in columns:
            conn.execute(
                "ALTER TABLE ticker_minute_archive_meta "
                "ADD COLUMN ticker_source_max_id INTEGER NOT NULL DEFAULT 0"
            )
        if "capital_source_max_id" not in columns:
            conn.execute(
                "ALTER TABLE ticker_minute_archive_meta "
                "ADD COLUMN capital_source_max_id INTEGER NOT NULL DEFAULT 0"
            )

    # ---------- 归档 ----------

    @staticmethod
    def _aggregate_date(conn, D: str) -> list[tuple]:
        """只读计算分钟聚合，不在耗时窗口查询期间持有主库写锁。"""
        return conn.execute(
            """
            WITH ranked AS (
                SELECT id, stock_code, price, volume, turnover, direction,
                       CASE WHEN datetime(trade_time) IS NOT NULL
                            THEN substr(replace(trade_time, 'T', ' '), 12, 5)
                            ELSE substr(datetime(timestamp/1000, 'unixepoch', '+8 hours'), 12, 5)
                       END AS m,
                       ROW_NUMBER() OVER (
                           PARTITION BY stock_code,
                               CASE WHEN datetime(trade_time) IS NOT NULL
                                    THEN trade_time ELSE 'legacy:' || id END,
                               price, volume, direction
                           ORDER BY CASE WHEN trade_date = ? THEN 0 ELSE 1 END, id
                       ) AS rn
                FROM ticker_data
                WHERE date(trade_time) = ?
                   OR (date(trade_time) IS NULL AND trade_date = ?)
            )
            SELECT stock_code, ?, m,
                   AVG(price), MAX(price), MIN(price),
                   SUM(CASE WHEN direction='BUY'  THEN turnover ELSE 0 END),
                   SUM(CASE WHEN direction='SELL' THEN turnover ELSE 0 END),
                   SUM(volume)
            FROM ranked
            WHERE rn = 1
            GROUP BY stock_code, m
            HAVING m BETWEEN '09:15' AND '16:10'
            """,
            (D, D, D, D),
        ).fetchall()

    @staticmethod
    def _replace_ticker_rows(conn, D: str, rows: list[tuple]) -> int:
        """用已经聚合好的结果短事务替换指定日期。"""
        conn.execute("DELETE FROM ticker_minute WHERE trade_date = ?", (D,))
        if rows:
            conn.executemany(
                "INSERT INTO ticker_minute "
                "(stock_code, trade_date, minute, price, high, low, "
                "buy_amt, sell_amt, volume) VALUES (?,?,?,?,?,?,?,?,?)",
                rows,
            )
        return len(rows)

    @staticmethod
    def _archive_date(conn, D: str) -> int:
        """同步兼容入口；生产调度会把聚合与短写事务分开。"""
        rows = TickerMinuteArchiver._aggregate_date(conn, D)
        return TickerMinuteArchiver._replace_ticker_rows(conn, D, rows)

    def _aggregate_capital_minute(self, conn, D: str) -> list[tuple]:
        """只读计算某交易日的「大单口径」分钟聚合。

        门槛按每股取 BaselineService.get_capital_tiers(冷启动有回退);写临时表后一条 JOIN 大查询，
        不逐股慢查询。direction 用 'BUY'/'SELL'(与 _archive_date 一致)。
        """
        bs = getattr(self._container, 'baseline_service', None)
        if bs is None:
            return []
        codes = [r[0] for r in conn.execute(
            "SELECT DISTINCT stock_code FROM ticker_data "
            "WHERE date(trade_time)=? OR (date(trade_time) IS NULL AND trade_date=?)",
            (D, D)).fetchall() if r[0]]
        if not codes:
            return []
        conn.execute("DROP TABLE IF EXISTS _cf_thr")
        conn.execute("CREATE TEMP TABLE _cf_thr (stock_code TEXT PRIMARY KEY, large REAL, sup REAL)")
        for code in codes:
            try:
                large, sup, _scale = bs.get_capital_tiers(code)
            except Exception:
                continue
            if large and large > 0:
                conn.execute("INSERT OR REPLACE INTO _cf_thr VALUES (?,?,?)",
                             (code, float(large), float(sup or large)))
        rows = conn.execute(
            """
            WITH ranked AS (
                SELECT t.id, t.stock_code, t.price, t.volume, t.turnover, t.direction,
                       CASE WHEN datetime(t.trade_time) IS NOT NULL
                            THEN substr(replace(t.trade_time, 'T', ' '), 12, 5)
                            ELSE substr(datetime(t.timestamp/1000, 'unixepoch', '+8 hours'), 12, 5)
                       END AS m,
                       ROW_NUMBER() OVER (
                           PARTITION BY t.stock_code,
                               CASE WHEN datetime(t.trade_time) IS NOT NULL
                                    THEN t.trade_time ELSE 'legacy:' || t.id END,
                               t.price, t.volume, t.direction
                           ORDER BY CASE WHEN t.trade_date = ? THEN 0 ELSE 1 END, t.id
                       ) AS rn
                FROM ticker_data t
                WHERE date(t.trade_time) = ?
                   OR (date(t.trade_time) IS NULL AND t.trade_date = ?)
            )
            SELECT t.stock_code, ?, t.m,
                   SUM(CASE WHEN t.direction='BUY'  THEN t.turnover ELSE 0 END),
                   SUM(CASE WHEN t.direction='SELL' THEN t.turnover ELSE 0 END),
                   SUM(CASE WHEN t.direction='BUY'  AND t.turnover>=thr.sup THEN t.turnover ELSE 0 END),
                   SUM(CASE WHEN t.direction='SELL' AND t.turnover>=thr.sup THEN t.turnover ELSE 0 END),
                   SUM(CASE WHEN t.direction='BUY'  THEN 1 ELSE 0 END),
                   SUM(CASE WHEN t.direction='SELL' THEN 1 ELSE 0 END),
                   thr.large
            FROM ranked t JOIN _cf_thr thr ON t.stock_code = thr.stock_code
            WHERE t.rn = 1 AND t.turnover >= thr.large
            GROUP BY t.stock_code, t.m
            HAVING t.m BETWEEN '09:15' AND '16:10'
            """,
            (D, D, D, D),
        ).fetchall()
        conn.execute("DROP TABLE IF EXISTS _cf_thr")
        conn.commit()  # 结束 TEMP 表事务；未写入主库。
        return rows

    @staticmethod
    def _replace_capital_rows(conn, D: str, rows: list[tuple]) -> int:
        """用已经聚合好的大单结果短事务替换指定日期。"""
        conn.execute("DELETE FROM capital_flow_minute WHERE trade_date = ?", (D,))
        if rows:
            conn.executemany(
                "INSERT INTO capital_flow_minute "
                "(stock_code, trade_date, minute, big_buy_amt, big_sell_amt, "
                "super_buy_amt, super_sell_amt, big_buy_count, big_sell_count, "
                "big_order_threshold) VALUES (?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
        return len(rows)

    def _archive_capital_minute(self, conn, D: str) -> int:
        """同步兼容入口；生产调度会把聚合与短写事务分开。"""
        rows = self._aggregate_capital_minute(conn, D)
        return self._replace_capital_rows(conn, D, rows)

    @staticmethod
    def _write_transaction(db, operation):
        """在 DatabaseManager 事务内执行短写；保留轻量测试替身兼容。"""
        transaction = getattr(db, "transaction", None)
        if callable(transaction):
            with transaction() as cursor:
                return operation(cursor)

        with db.get_connection() as conn:
            try:
                result = operation(conn)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def _run_serialized_write(self, db, operation, label: str):
        """把归档替换放入全局写队列，超时只取消排队任务，绝不并发直写。"""
        write_queue = getattr(db, "write_queue", None)
        if write_queue is None or not write_queue.is_running:
            return self._write_transaction(db, operation)

        future = write_queue.submit(self._write_transaction, db, operation)
        try:
            return future.result(timeout=_WRITE_TIMEOUT_SEC)
        except FutureTimeoutError:
            cancelled = future.cancel()
            logger.warning(
                "%s 等待写队列超时: cancelled=%s pending=%s",
                label, cancelled, write_queue.pending_count,
            )
            raise

    def _ensure_archive_tables(self, db):
        self._run_serialized_write(
            db,
            lambda conn: self._ensure_table(conn),
            "分钟归档建表",
        )

    def _persist_ticker_archive(
        self, db, D: str, rows: list[tuple], source_max_id: int,
    ) -> int:
        def _persist(conn):
            written = self._replace_ticker_rows(conn, D, rows)
            conn.execute(
                "INSERT OR IGNORE INTO ticker_minute_archive_meta "
                "(trade_date, ticker_version, capital_version, "
                "ticker_source_max_id, capital_source_max_id) VALUES (?,0,0,0,0)",
                (D,),
            )
            conn.execute(
                "UPDATE ticker_minute_archive_meta SET ticker_version=?, "
                "ticker_source_max_id=?, updated_at=? WHERE trade_date=?",
                (_ARCHIVE_VERSION, source_max_id, datetime.now().isoformat(), D),
            )
            return written

        return self._run_serialized_write(db, _persist, f"ticker_minute[{D}]")

    def _persist_capital_archive(
        self, db, D: str, rows: list[tuple], source_max_id: int,
    ) -> int:
        def _persist(conn):
            written = self._replace_capital_rows(conn, D, rows)
            conn.execute(
                "INSERT OR IGNORE INTO ticker_minute_archive_meta "
                "(trade_date, ticker_version, capital_version, "
                "ticker_source_max_id, capital_source_max_id) VALUES (?,0,0,0,0)",
                (D,),
            )
            conn.execute(
                "UPDATE ticker_minute_archive_meta SET capital_version=?, "
                "capital_source_max_id=?, updated_at=? WHERE trade_date=?",
                (_ARCHIVE_VERSION, source_max_id, datetime.now().isoformat(), D),
            )
            return written

        return self._run_serialized_write(db, _persist, f"capital_flow_minute[{D}]")

    def _persist_legacy_watermarks(
        self,
        db,
        D: str,
        source_max_id: int,
        ticker: bool,
        capital: bool,
    ) -> None:
        assignments = []
        params = []
        if ticker:
            assignments.append("ticker_source_max_id=?")
            params.append(source_max_id)
        if capital:
            assignments.append("capital_source_max_id=?")
            params.append(source_max_id)
        if not assignments:
            return
        assignments.append("updated_at=?")
        params.extend((datetime.now().isoformat(), D))

        def _persist(conn):
            conn.execute(
                f"UPDATE ticker_minute_archive_meta SET {', '.join(assignments)} "
                "WHERE trade_date=?",
                tuple(params),
            )

        self._run_serialized_write(db, _persist, f"archive_watermark[{D}]")

    def archive_present(self) -> dict:
        """把 ticker_data 里现存的、尚未归档的交易日补进 ticker_minute + capital_flow_minute。

        过去日：已按当前版本归档则跳过；当日：仅收盘后(>16:10)归档。
        返回 ticker_minute 的 {date: rows}。
        """
        db = getattr(self._container, 'db_manager', None)
        if not db:
            return {}
        out = {}
        try:
            hhmm = datetime.now().strftime("%H:%M")  # 服务器=CST=HK
            today = datetime.now().strftime("%Y-%m-%d")
            self._ensure_archive_tables(db)
            with db.get_connection() as conn:
                source_rows = conn.execute(
                    "SELECT actual_date, MAX(id) FROM ("
                    " SELECT id, CASE WHEN date(trade_time) IS NOT NULL THEN date(trade_time)"
                    "                 ELSE trade_date END AS actual_date FROM ticker_data"
                    ") WHERE actual_date IS NOT NULL GROUP BY actual_date ORDER BY actual_date"
                ).fetchall()
                source_dates = [(r[0], int(r[1] or 0)) for r in source_rows if r[0]]
                done = {r[0] for r in conn.execute(
                    "SELECT DISTINCT trade_date FROM ticker_minute").fetchall()}
                done_cf = {r[0] for r in conn.execute(
                    "SELECT DISTINCT trade_date FROM capital_flow_minute").fetchall()}
                versions = {r[0]: tuple(int(v or 0) for v in r[1:]) for r in conn.execute(
                    "SELECT trade_date, ticker_version, capital_version, "
                    "ticker_source_max_id, capital_source_max_id "
                    "FROM ticker_minute_archive_meta").fetchall()}

            out_cf = {}
            baseline_enabled = getattr(self._container, 'baseline_service', None) is not None
            for D, source_max_id in source_dates:
                try:
                    is_today = (D == today)
                    if is_today and hhmm <= "16:10":
                        continue  # 当日盘中不归档(数据还在长)
                    ticker_ver, capital_ver, ticker_source, capital_source = versions.get(
                        D, (0, 0, 0, 0)
                    )

                    # 部署新增水位列时，历史交易日已经按当前版本完成且不会再增长，
                    # 只补水位，避免无意义地重扫 7 天逐笔数据。
                    legacy_ticker = (
                        not is_today and D in done
                        and ticker_ver >= _ARCHIVE_VERSION and ticker_source == 0
                    )
                    legacy_capital = (
                        not is_today and D in done_cf
                        and capital_ver >= _ARCHIVE_VERSION and capital_source == 0
                    )
                    if legacy_ticker or (baseline_enabled and legacy_capital):
                        self._persist_legacy_watermarks(
                            db, D, source_max_id, legacy_ticker,
                            baseline_enabled and legacy_capital,
                        )
                        if legacy_ticker:
                            ticker_source = source_max_id
                        if legacy_capital:
                            capital_source = source_max_id

                    need_ticker = (
                        D not in done or ticker_ver < _ARCHIVE_VERSION
                        or ticker_source != source_max_id
                    )
                    if need_ticker:
                        with db.get_connection() as conn:
                            ticker_rows = self._aggregate_date(conn, D)
                        out[D] = self._persist_ticker_archive(
                            db, D, ticker_rows, source_max_id,
                        )

                    need_capital = baseline_enabled and (
                        D not in done_cf or capital_ver < _ARCHIVE_VERSION
                        or capital_source != source_max_id
                    )
                    if need_capital:
                        with db.get_connection() as conn:
                            capital_rows = self._aggregate_capital_minute(conn, D)
                        out_cf[D] = self._persist_capital_archive(
                            db, D, capital_rows, source_max_id,
                        )
                except Exception as e:  # 单日失败不阻断其他待归档日期
                    logger.warning(f"分钟归档 {D} 失败: {e}")
            if out:
                logger.info("ticker_minute 归档完成: " +
                            ", ".join(f"{d}={n}" for d, n in out.items()))
            if out_cf:
                logger.info("capital_flow_minute 归档完成: " +
                            ", ".join(f"{d}={n}" for d, n in out_cf.items()))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"分钟归档失败: {e}")
        return out

    # ---------- 生命周期 ----------

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("TickerMinuteArchiver 已启动")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self):
        # 启动先追赶一次（把现存 7 天补进归档），之后每小时巡检
        while self._running:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self.archive_present)
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                logger.warning(f"ticker_minute 巡检异常: {e}")
            await asyncio.sleep(_LOOP_INTERVAL_SEC)
