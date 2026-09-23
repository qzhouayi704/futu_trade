"""Idempotent paper commands; all mutations happen within the store transaction."""

from datetime import datetime
import hashlib
from typing import Callable

from ...domain.planning.codec import encode
from ...domain.planning.models import EntrySetup, PaperAccount, PaperBook
from ...ports.paper_account import PaperAccountStore
from .paper_engine import PaperEngine


class PaperTradingService:
    def __init__(self, store: PaperAccountStore) -> None:
        self._store = store
        PaperEngine.assert_invariants(store.read())

    def submit(self, event_id: str, setup: EntrySetup, when: datetime) -> str:
        return self._apply(event_id, ("plan", setup, when),
                           lambda account: encode(PaperEngine.submit(account, setup, when)))

    def on_book(self, book: PaperBook) -> str:
        return self._apply(book.event_id, ("book", book),
                           lambda account: encode(PaperEngine.on_book(account, book)))

    def advance(self, event_id: str, when: datetime) -> str:
        def operation(account: PaperAccount) -> str:
            PaperEngine.advance(account, when)
            return encode("CLOCK_ADVANCED")
        return self._apply(event_id, ("clock", when), operation)

    def cancel_entry(self, event_id: str, plan_id: str, when: datetime) -> str:
        def operation(account: PaperAccount) -> str:
            PaperEngine.cancel_entry(account, plan_id, when)
            return encode("ENTRY_CANCELLED")
        return self._apply(event_id, ("cancel_entry", plan_id, when), operation)

    def snapshot(self) -> PaperAccount:
        return self._store.read()

    def _apply(self, event_id: str, content: object,
               operation: Callable[[PaperAccount], str]) -> str:
        fingerprint = hashlib.sha256(encode(content).encode("utf-8")).hexdigest()

        def checked(account: PaperAccount) -> str:
            result = operation(account)
            PaperEngine.assert_invariants(account)
            return result

        return self._store.apply(event_id, fingerprint, checked)
