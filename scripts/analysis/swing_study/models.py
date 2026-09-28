"""Typed contracts between data, signals, execution and evaluation."""
from __future__ import annotations

from dataclasses import dataclass, field
import numpy as np

from scripts.analysis.minute_entry_study.models import Tape


@dataclass(frozen=True)
class Daily:
    day: str
    close: float
    high: float
    low: float
    turnover: float
    conflict: bool = False


@dataclass(frozen=True)
class Background:
    valid: bool
    atr: float
    low20: float
    high20: float
    ma5: float
    ma20: float
    low5: float
    prior_close: float
    mean_turnover: float
    stabilizing: bool


@dataclass
class StockPath:
    code: str
    mean: np.ndarray
    high: np.ndarray
    low: np.ndarray
    volume: np.ndarray
    buy: np.ndarray
    sell: np.ndarray
    backgrounds: list[Background]


@dataclass
class Opportunity:
    day_index: int
    theme: str
    sector: str
    tape: Tape
    background: Background
    recorded_position: float | None
    recorded_atr: float | None


@dataclass
class Market:
    days: list[str]
    paths: dict[str, StockPath]
    opportunities: list[Opportunity]
    sha256: str
    audit: dict[str, int]
    sectors: dict[str, int]


@dataclass(frozen=True)
class EntryRule:
    family: str
    ratio: float = .55
    position: float = .5
    volume_multiple: float = 1
    structure: bool = False

    @property
    def key(self) -> str:
        return f'{self.family}-b{self.ratio:g}-p{self.position:g}-v{self.volume_multiple:g}-s{int(self.structure)}'


@dataclass(frozen=True)
class ExitRule:
    sessions: int = 3
    atr_multiple: float = 1
    reward: float = 2
    protection: bool = False

    @property
    def key(self) -> str:
        return f'd{self.sessions}-a{self.atr_multiple:g}-r{self.reward:g}-p{int(self.protection)}'


@dataclass(frozen=True)
class Signal:
    code: str
    day: int
    index: int
    theme: str
    atr: float
    anchor: float
    gate: int


@dataclass(frozen=True)
class FillCosts:
    fee: float = .0015
    slippage: float = .0005
    adverse: bool = False
    ticket: float = 10000
    participation: float = .1


@dataclass(frozen=True)
class SwingTrade:
    code: str
    theme: str
    day: int
    signal: int
    entry: int
    trigger: int | None
    exit: int | None
    entry_price: float
    exit_price: float | None
    net: float | None
    reason: str
    gap_minutes: int
    missing_whole_days: int
    risk: float
    overnight_count: int
    mfe: float | None
    mae: float | None
    entry_vs_anchor: float
    signal_delay: int


@dataclass
class ReplayResult:
    trades: list[SwingTrade] = field(default_factory=list)
    signals: int = 0
    blocked_by_position: int = 0
    unfilled: int = 0
