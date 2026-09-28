"""Explicit local enable, journal-first transitions, deterministic recovery."""
from dataclasses import asdict
from datetime import datetime
import logging
from typing import Callable

from ..protocol import FrozenProtocol, from_payload, source_hashes
from .models import Config, Event, Journal, Track, local
from .store import SQLiteJournal
from .tracker import Selection, select, transition


def verify_frozen(protocol: FrozenProtocol) -> None:
    from_payload(asdict(protocol))
    current = {s.path: s.sha256 for s in source_hashes()}
    changed = [s.path for s in protocol.sources if current.get(s.path) != s.sha256]
    if len(protocol.sources) != len(current) or {s.path for s in protocol.sources} != set(current) or changed:
        raise ValueError(f'frozen sources changed or incomplete: {changed}')


class Collector:
    def __init__(self, config: Config, protocol: FrozenProtocol,
                 journal_factory: Callable[[Config, FrozenProtocol], Journal] = SQLiteJournal):
        self.protocol = protocol
        self.dataset_kind = config.dataset_kind
        self.tracks: tuple[Track, ...] = ()
        self.last_received: datetime | None = None
        self.journal: Journal | None = None
        if config.enabled:
            verify_frozen(protocol)
            self.journal = journal_factory(config, protocol)
            try:
                for event in self.journal.events():
                    self.tracks = transition(self.tracks, event, protocol)
                    self.last_received = event.received_at
            except BaseException:
                self.journal.close()
                raise

    def observe(self, event: Event) -> bool:
        if self.journal is None:
            return False
        if (self.dataset_kind == 'ARCHIVE_DIAGNOSTIC') != event.source.startswith('ARCHIVE_DIAGNOSTIC'):
            raise ValueError('diagnostic and live/synthetic sources must remain in separate journals')
        next_tracks = transition(self.tracks, event, self.protocol)
        try:
            accepted = self.journal.append(event)
        except Exception:
            logging.getLogger(__name__).exception('Research observation rejected; memory remains at committed state')
            raise
        if accepted:
            self.tracks = next_tracks
            self.last_received = event.received_at
        return accepted

    def selection(self, when: datetime, protected_codes: tuple[str, ...], capacity: int) -> Selection:
        if self.last_received is not None and local(when) < self.last_received:
            raise ValueError('selection uses current committed state, not a historical snapshot')
        return select(self.tracks, when, protected_codes, capacity)

    def events(self) -> tuple[Event, ...]:
        return self.journal.events() if self.journal is not None else ()

    def close(self) -> None:
        if self.journal is not None:
            self.journal.close()
