"""Typed event, episode and research-policy contracts."""
from dataclasses import dataclass
from datetime import datetime

from ..models import Market, Opportunity


@dataclass(frozen=True)
class LegacyEvent:
    event_id: int
    code: str
    day: str
    when: datetime
    index: int
    stage: str
    direction: str
    large_inflow: bool
    price: float
    first_price: float
    sequence: int
    sector: str
    action: str
    buy_ratio: float
    window_net: float
    observe_only: bool


@dataclass
class Episode:
    first: LegacyEvent
    opportunity: Opportunity
    events: tuple[LegacyEvent, ...]
    # End of the active sequence, exclusive in completed-minute evidence time.
    end_index: int


@dataclass(frozen=True)
class Policy:
    route: str
    timing: str
    ratio: float = .55

    @property
    def key(self) -> str:
        return f'{self.route}:{self.timing}:{self.ratio:g}'


@dataclass
class Study:
    market: Market
    episodes: list[Episode]
    events: list[LegacyEvent]
    counts: dict[str, int]
    stages: dict[str, int]
    time_lags: list[float]


@dataclass(frozen=True)
class Fold:
    name: str
    train_end: int
    test_start: int
    test_end: int

    def train_days(self, sessions: int) -> list[int]:
        return list(range(self.train_end-sessions+2))

    def test_days(self, sessions: int) -> list[int]:
        return list(range(self.test_start, self.test_end-sessions+2))
