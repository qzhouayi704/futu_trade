"""Outcome persistence boundary."""

from typing import Protocol

from ..domain.outcomes import OutcomeRecord


class OutcomeStore(Protocol):
    async def upsert(self, outcome: OutcomeRecord) -> bool: ...

    async def load_active(self, strategy_version: str) -> tuple[OutcomeRecord, ...]: ...
