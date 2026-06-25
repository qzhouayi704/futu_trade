#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐笔分钟归档器

原始 ticker_data 体积巨大（~68万行/交易日，占库 90%+），故只滚动保留 7 天
（见 db_manager._auto_cleanup_old_data）。但盘中信号回测（择时/狙击/动量）都把逐笔
**聚合成分钟**来用，分钟级数据比原始逐笔小 5~7 倍，可长期保留。

本归档器在收盘后（及启动追赶）把每股每分钟聚合（价/高/低/主买额/主卖额/量）写入
`ticker_minute` 表，供长周期回测使用——活盘的 ticker_data 仍维持 7 天精简、不受影响。

幂等：过去日只归档一次（已归档则跳过）；当日只在收盘后(>16:10)归档，避免盘中反复写。
"""

import asyncio
import logging
from datetime import datetime

logger = logging.getLogger("ticker_minute_archiver")

# ticker_minute 自身保留天数由 db_manager._auto_cleanup_old_data 控制(180天)。
_LOOP_INTERVAL_SEC = 3600  # 每小时巡检一次(幂等，只补缺失日 + 收盘后归档当日)


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

    # ---------- 归档 ----------

    @staticmethod
    def _archive_date(conn, D: str) -> int:
        """重算并写入某交易日的分钟聚合（先删后插，保证幂等/可补全）。返回写入行数。"""
        conn.execute("DELETE FROM ticker_minute WHERE trade_date = ?", (D,))
        cur = conn.execute(
            """
            INSERT INTO ticker_minute
                (stock_code, trade_date, minute, price, high, low, buy_amt, sell_amt, volume)
            SELECT stock_code, ?,
                   substr(datetime(timestamp/1000, 'unixepoch', '+8 hours'), 12, 5) AS m,
                   AVG(price), MAX(price), MIN(price),
                   SUM(CASE WHEN direction='BUY'  THEN turnover ELSE 0 END),
                   SUM(CASE WHEN direction='SELL' THEN turnover ELSE 0 END),
                   SUM(volume)
            FROM ticker_data
            WHERE trade_date = ?
            GROUP BY stock_code, m
            HAVING m BETWEEN '09:15' AND '16:10'
            """,
            (D, D),
        )
        return cur.rowcount or 0

    def _archive_capital_minute(self, conn, D: str) -> int:
        """重算并写入某交易日的「大单口径」分钟归档(每股门槛过滤)。先删后插，幂等。返回行数。

        门槛按每股取 BaselineService.get_capital_tiers(冷启动有回退);写临时表后一条 JOIN 大查询，
        不逐股慢查询。direction 用 'BUY'/'SELL'(与 _archive_date 一致)。
        """
        bs = getattr(self._container, 'baseline_service', None)
        if bs is None:
            return 0
        codes = [r[0] for r in conn.execute(
            "SELECT DISTINCT stock_code FROM ticker_data WHERE trade_date=?", (D,)).fetchall() if r[0]]
        if not codes:
            return 0
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
        conn.execute("DELETE FROM capital_flow_minute WHERE trade_date = ?", (D,))
        cur = conn.execute(
            """
            INSERT INTO capital_flow_minute
                (stock_code, trade_date, minute, big_buy_amt, big_sell_amt,
                 super_buy_amt, super_sell_amt, big_buy_count, big_sell_count, big_order_threshold)
            SELECT t.stock_code, ?,
                   substr(datetime(t.timestamp/1000, 'unixepoch', '+8 hours'), 12, 5) AS m,
                   SUM(CASE WHEN t.direction='BUY'  THEN t.turnover ELSE 0 END),
                   SUM(CASE WHEN t.direction='SELL' THEN t.turnover ELSE 0 END),
                   SUM(CASE WHEN t.direction='BUY'  AND t.turnover>=thr.sup THEN t.turnover ELSE 0 END),
                   SUM(CASE WHEN t.direction='SELL' AND t.turnover>=thr.sup THEN t.turnover ELSE 0 END),
                   SUM(CASE WHEN t.direction='BUY'  THEN 1 ELSE 0 END),
                   SUM(CASE WHEN t.direction='SELL' THEN 1 ELSE 0 END),
                   thr.large
            FROM ticker_data t JOIN _cf_thr thr ON t.stock_code = thr.stock_code
            WHERE t.trade_date = ? AND t.turnover >= thr.large
            GROUP BY t.stock_code, m
            HAVING m BETWEEN '09:15' AND '16:10'
            """,
            (D, D),
        )
        conn.execute("DROP TABLE IF EXISTS _cf_thr")
        return cur.rowcount or 0

    def archive_present(self) -> dict:
        """把 ticker_data 里现存的、尚未归档的交易日补进 ticker_minute + capital_flow_minute。

        过去日：已归档则跳过；当日：仅收盘后(>16:10)归档。两表各自维护已归档日集合。
        返回 ticker_minute 的 {date: rows}。
        """
        db = getattr(self._container, 'db_manager', None)
        if not db:
            return {}
        out = {}
        try:
            hhmm = datetime.now().strftime("%H:%M")  # 服务器=CST=HK
            today = datetime.now().strftime("%Y-%m-%d")
            with db.get_connection() as conn:
                self._ensure_table(conn)
                src_dates = [r[0] for r in conn.execute(
                    "SELECT DISTINCT trade_date FROM ticker_data ORDER BY trade_date").fetchall() if r[0]]
                done = {r[0] for r in conn.execute(
                    "SELECT DISTINCT trade_date FROM ticker_minute").fetchall()}
                done_cf = {r[0] for r in conn.execute(
                    "SELECT DISTINCT trade_date FROM capital_flow_minute").fetchall()}
                out_cf = {}
                for D in src_dates:
                    is_today = (D == today)
                    if is_today and hhmm <= "16:10":
                        continue  # 当日盘中不归档(数据还在长)
                    if is_today or D not in done:
                        out[D] = self._archive_date(conn, D)
                    if is_today or D not in done_cf:
                        out_cf[D] = self._archive_capital_minute(conn, D)
                conn.commit()
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
