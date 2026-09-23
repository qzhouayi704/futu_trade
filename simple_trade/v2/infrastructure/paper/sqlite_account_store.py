"""One atomic state/reservation/fill/event transaction per paper command."""

from contextlib import closing
from pathlib import Path
import sqlite3
from typing import Callable

from ...domain.planning.codec import decode_account, encode_account
from ...domain.planning.models import PaperAccount, PaperPolicy


class SqlitePaperAccountStore:
    APPLICATION_ID = 0x50325031

    def __init__(self, path: Path, account_id: str, policy: PaperPolicy) -> None:
        self.path = Path(path)
        initial = PaperAccount(account_id=account_id, policy=policy, cash=policy.initial_cash)
        self._account_id = account_id
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            app_id = connection.execute("PRAGMA application_id").fetchone()[0]
            tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if app_id != self.APPLICATION_ID and (app_id != 0 or tables):
                raise ValueError("refusing to use a non-paper database")
            connection.execute(f"PRAGMA application_id={self.APPLICATION_ID}")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS paper_account "
                "(account_id TEXT PRIMARY KEY, state_json TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS paper_commands "
                "(event_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result_json TEXT NOT NULL)"
            )
            row = connection.execute("SELECT account_id, state_json FROM paper_account").fetchone()
            if row is not None:
                account = decode_account(row[1])
                if row[0] != account_id or account.policy != policy:
                    raise ValueError("paper account identity/policy is immutable; use a new ledger")
            else:
                connection.execute("INSERT INTO paper_account VALUES (?, ?)",
                                   (account_id, encode_account(initial)))

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.path), timeout=3.0)

    def read(self) -> PaperAccount:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT state_json FROM paper_account WHERE account_id=?",
                                     (self._account_id,)).fetchone()
            if row is None:
                raise RuntimeError("paper account missing")
            return decode_account(row[0])

    def apply(self, event_id: str, fingerprint: str,
              operation: Callable[[PaperAccount], str]) -> str:
        if not event_id or not fingerprint:
            raise ValueError("paper command identity is required")
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT fingerprint, result_json FROM paper_commands WHERE event_id=?", (event_id,)
            ).fetchone()
            if existing is not None:
                if existing[0] != fingerprint:
                    raise ValueError("paper command id reused with different content")
                return existing[1]
            row = connection.execute("SELECT state_json FROM paper_account WHERE account_id=?",
                                     (self._account_id,)).fetchone()
            if row is None:
                raise RuntimeError("paper account missing")
            account = decode_account(row[0])
            result = operation(account)
            connection.execute("UPDATE paper_account SET state_json=? WHERE account_id=?",
                               (encode_account(account), self._account_id))
            connection.execute("INSERT INTO paper_commands VALUES (?, ?, ?)",
                               (event_id, fingerprint, result))
            return result
