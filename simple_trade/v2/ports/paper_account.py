"""Atomic isolated-account updates; no broker operations are exposed."""

from typing import Callable, Protocol

from ..domain.planning.models import PaperAccount


class PaperAccountStore(Protocol):
    def read(self) -> PaperAccount: ...

    def apply(
        self, event_id: str, fingerprint: str,
        operation: Callable[[PaperAccount], str],
    ) -> str: ...
