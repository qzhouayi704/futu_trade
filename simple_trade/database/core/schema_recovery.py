"""Idempotent SQLite schema recovery helpers used during application startup."""

import logging
import sqlite3
from collections.abc import Iterable


TICKER_TARGET_UNIQUE = (
    "UNIQUE(stock_code, trade_date, trade_time, price, volume, direction)"
)


def migrate_ticker_data_schema(conn: sqlite3.Connection) -> bool:
    """Converge ticker_data to the business-key schema after any interrupted run."""
    cursor = conn.cursor()
    row = cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='ticker_data'"
    ).fetchone()
    if not row or not row[0]:
        return False

    target_signature = TICKER_TARGET_UNIQUE.replace(" ", "")
    if target_signature in row[0].replace(" ", ""):
        cursor.execute("DROP TABLE IF EXISTS ticker_data_new")
        conn.commit()
        return False

    columns = [item[1] for item in cursor.execute("PRAGMA table_info(ticker_data)")]
    select_sequence = "sequence" if "sequence" in columns else "NULL"
    select_trade_time = "trade_time" if "trade_time" in columns else "NULL"
    logging.info(
        "[迁移] ticker_data 重建表：换用业务键 "
        "(trade_time,price,volume,direction) 去重"
    )

    cursor.execute("PRAGMA foreign_keys = OFF")
    try:
        cursor.executescript(f"""
            DROP TABLE IF EXISTS ticker_data_new;
            CREATE TABLE ticker_data_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_code VARCHAR(20) NOT NULL,
                price DECIMAL(10,3) NOT NULL,
                volume INTEGER NOT NULL,
                turnover DECIMAL(15,2),
                direction VARCHAR(10) NOT NULL,
                timestamp BIGINT NOT NULL,
                trade_date TEXT NOT NULL,
                sequence BIGINT,
                trade_time TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                {TICKER_TARGET_UNIQUE}
            );
            INSERT OR IGNORE INTO ticker_data_new
                (id, stock_code, price, volume, turnover, direction,
                 timestamp, trade_date, sequence, trade_time, created_at)
            SELECT id, stock_code, price, volume, turnover, direction,
                   timestamp, trade_date, {select_sequence}, {select_trade_time}, created_at
            FROM ticker_data;
            DROP TABLE ticker_data;
            ALTER TABLE ticker_data_new RENAME TO ticker_data;
        """)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.execute("PRAGMA foreign_keys = ON")
    logging.info("[迁移] ticker_data 重建完成（业务键去重，旧行已保留）")
    return True


def create_indexes_best_effort(
    conn: sqlite3.Connection,
    index_statements: Iterable[str],
    *,
    lock_timeout_ms: int = 1000,
) -> dict[str, bool]:
    """Create indexes while bounding startup delay caused by a competing writer."""
    cursor = conn.cursor()
    previous_timeout = cursor.execute("PRAGMA busy_timeout").fetchone()[0]
    cursor.execute(f"PRAGMA busy_timeout = {int(lock_timeout_ms)}")
    results: dict[str, bool] = {}
    try:
        for statement in index_statements:
            name = index_name(statement)
            try:
                cursor.execute(statement)
                results[name] = True
            except sqlite3.OperationalError as error:
                results[name] = False
                if "locked" in str(error).lower() or "busy" in str(error).lower():
                    logging.warning(
                        "数据库正忙，启动索引创建已延期；下次启动自动重试: %s", name
                    )
                    break
                logging.warning("创建索引 %s 失败: %s", name, error)
            except Exception as error:
                results[name] = False
                logging.warning("创建索引 %s 失败: %s", name, error)
        conn.commit()
    finally:
        cursor.execute(f"PRAGMA busy_timeout = {int(previous_timeout)}")
    return results


def index_name(statement: str) -> str:
    if "idx_" not in statement:
        return "unknown"
    return f"idx_{statement.split('idx_', 1)[1].split(' ', 1)[0]}"
