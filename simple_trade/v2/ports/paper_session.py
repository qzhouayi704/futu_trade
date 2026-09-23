"""Local experiment storage and committed market input boundaries."""

from typing import Protocol

from .paper_account import PaperAccountStore


class PaperSessionStore(PaperAccountStore, Protocol):
    def begin_run(self, run_id: str, configuration: str) -> None: ...

    def finish_run(self, run_id: str, error: str | None) -> None: ...
