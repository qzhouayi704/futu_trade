#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace

from simple_trade.database.models.business_tables import BusinessTables
from simple_trade.services.market_data.ticker_minute_archiver import (
    TickerMinuteArchiver,
    _ARCHIVE_VERSION,
)


class _Baseline:
    def get_capital_tiers(self, _code):
        return 100_000.0, 300_000.0, 100_000.0


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.execute(BusinessTables.TICKER_DATA_TABLE)
    TickerMinuteArchiver._ensure_table(conn)
    return conn


def _tick(conn, trade_date, trade_time, direction, turnover, row_id=None):
    values = (
        "HK.00001", 10.0, int(turnover / 10.0), turnover, direction,
        1_783_909_800_000, trade_date, row_id, trade_time,
    )
    conn.execute(
        "INSERT INTO ticker_data "
        "(stock_code,price,volume,turnover,direction,timestamp,trade_date,sequence,trade_time) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        values,
    )


def test_archive_uses_trade_time_and_dedups_wrong_date_replay():
    conn = _conn()
    try:
        # 同一真实成交被旧逻辑分别写在真实日和接收日，归档只能计一次。
        _tick(conn, "2026-07-10", "2026-07-10 10:05:00.100", "BUY", 500_000, 1)
        _tick(conn, "2026-07-13", "2026-07-10 10:05:00.100", "BUY", 500_000, 99)
        _tick(conn, "2026-07-10", "2026-07-10 10:05:30.200", "SELL", 200_000, 2)

        assert TickerMinuteArchiver._archive_date(conn, "2026-07-10") == 1
        row = conn.execute(
            "SELECT minute,buy_amt,sell_amt FROM ticker_minute "
            "WHERE stock_code='HK.00001' AND trade_date='2026-07-10'"
        ).fetchone()
        assert row == ("10:05", 500_000.0, 200_000.0)
        assert conn.execute(
            "SELECT COUNT(*) FROM ticker_minute WHERE trade_date='2026-07-13'"
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_capital_archive_uses_real_trade_minute_without_double_count():
    conn = _conn()
    try:
        _tick(conn, "2026-07-10", "2026-07-10 10:05:00.100", "BUY", 500_000, 1)
        _tick(conn, "2026-07-13", "2026-07-10 10:05:00.100", "BUY", 500_000, 99)
        archiver = TickerMinuteArchiver(SimpleNamespace(baseline_service=_Baseline()))
        assert archiver._archive_capital_minute(conn, "2026-07-10") == 1
        row = conn.execute(
            "SELECT minute,big_buy_amt,big_buy_count,super_buy_amt "
            "FROM capital_flow_minute WHERE trade_date='2026-07-10'"
        ).fetchone()
        assert row == ("10:05", 500_000.0, 1, 500_000.0)
    finally:
        conn.close()


def test_archive_meta_table_starts_unversioned():
    conn = _conn()
    try:
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(ticker_minute_archive_meta)"
        ).fetchall()}
        assert {"trade_date", "ticker_version", "capital_version", "updated_at"} <= cols
        assert _ARCHIVE_VERSION >= 2
    finally:
        conn.close()


def test_archive_present_rebuilds_existing_unversioned_archive(tmp_path):
    db_path = tmp_path / "archive.db"
    conn = sqlite3.connect(db_path)
    conn.execute(BusinessTables.TICKER_DATA_TABLE)
    TickerMinuteArchiver._ensure_table(conn)
    _tick(conn, "2020-01-02", "2020-01-02 10:05:00.100", "BUY", 500_000, 1)
    conn.execute(
        "INSERT INTO ticker_minute "
        "(stock_code,trade_date,minute,price,high,low,buy_amt,sell_amt,volume) "
        "VALUES ('HK.00001','2020-01-02','10:05',10,10,10,999,0,1)"
    )
    conn.commit()
    conn.close()

    class _DB:
        @contextmanager
        def get_connection(self):
            db_conn = sqlite3.connect(db_path)
            try:
                yield db_conn
            finally:
                db_conn.close()

    archiver = TickerMinuteArchiver(SimpleNamespace(
        db_manager=_DB(), baseline_service=None
    ))
    assert archiver.archive_present()["2020-01-02"] == 1

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute(
            "SELECT buy_amt FROM ticker_minute WHERE trade_date='2020-01-02'"
        ).fetchone()[0] == 500_000.0
        assert conn.execute(
            "SELECT ticker_version FROM ticker_minute_archive_meta "
            "WHERE trade_date='2020-01-02'"
        ).fetchone()[0] == _ARCHIVE_VERSION
    finally:
        conn.close()
