"""Sampled best-book evidence, explicitly separate from exchange trade timestamps."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import json
import os
from pathlib import Path

from .planning.models import hk_stock_code, integer, positive
from .serialization import require_aware


@dataclass(frozen=True, slots=True)
class BookCaptureConfig:
    path: Path
    max_stocks: int = 8
    sample_interval_seconds: float = 0.5
    queue_capacity: int = 2048
    batch_size: int = 128
    max_records: int = 1000000
    max_bytes: int = 268435456
    min_free_bytes: int = 268435456
    refresh_seconds: float = 30
    io_timeout_seconds: float = 8

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))
        if not self.path.is_absolute():
            raise ValueError("book archive path must be absolute")
        for key in ("max_stocks", "queue_capacity", "batch_size", "max_records", "max_bytes", "min_free_bytes"):
            if type(getattr(self, key)) is not int or getattr(self, key) <= 0:
                raise ValueError(f"{key} must be a positive integer")
        if self.max_stocks > 20 or self.max_bytes < 65536:
            raise ValueError("capture capacity outside safe bounds")
        if (not 0.1 <= self.sample_interval_seconds <= 60
                or not 0.01 <= self.refresh_seconds <= 300
                or not 0.01 <= self.io_timeout_seconds <= 30):
            raise ValueError("invalid capture timing")

    @classmethod
    def from_env(cls) -> "BookCaptureConfig | None":
        value = os.getenv("V2_BOOK_CAPTURE_PATH", "").strip()
        config_path = os.getenv("V2_BOOK_CAPTURE_CONFIG", "").strip()
        if config_path:
            config = cls.from_file(Path(config_path))
            if value and (not Path(value).is_absolute() or Path(value).resolve() != config.path.resolve()):
                raise ValueError("capture path environment conflicts with config file")
            return config
        return cls(path=Path(value)) if value else None

    @classmethod
    def from_file(cls, path: Path) -> "BookCaptureConfig":
        path = Path(path)
        if not path.is_absolute() or path.stat().st_size > 262144:
            raise ValueError("capture config must be an absolute file of at most 256 KiB")
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if payload.pop("schema_version", None) != 1:
            raise ValueError("unsupported capture configuration")
        return cls(**payload)


@dataclass(frozen=True, slots=True, kw_only=True)
class CapturedBook:
    session_id: str
    sequence: int
    connection_id: str
    stock_code: str
    received_at: datetime
    bid_time: datetime | None
    ask_time: datetime | None
    bid: Decimal | None
    ask: Decimal | None
    bid_size: int
    ask_size: int
    reasons: tuple[str, ...] = ()
    loss_count: int = 0
    timestamp_basis: str = "FUTU_SERVER_RECEIPT"

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", hk_stock_code(self.stock_code))
        require_aware(self.received_at, "received_at")
        for key in ("bid_time", "ask_time"):
            if getattr(self, key) is not None:
                require_aware(getattr(self, key), key)
        for key in ("bid", "ask"):
            if getattr(self, key) is not None:
                positive(getattr(self, key), key)
        if not self.session_id or not self.connection_id or self.sequence < 1:
            raise ValueError("capture identity is required")
        integer(self.sequence, "sequence")
        for key in ("bid_size", "ask_size", "loss_count"):
            integer(getattr(self, key), key, minimum=0)
        if self.timestamp_basis != "FUTU_SERVER_RECEIPT":
            raise ValueError("capture timestamp basis must describe the server feed")

    @property
    def event_id(self) -> str:
        return f"capture:{self.session_id}:{self.sequence}"


@dataclass(frozen=True, slots=True)
class CaptureStats:
    running: bool
    session_id: str
    target_codes: tuple[str, ...]
    subscribed_codes: tuple[str, ...]
    pending_codes: tuple[str, ...]
    received: int
    sampled_out: int
    dropped: int
    invalid: int
    persisted: int
    queue_size: int
    subscription_failures: int
    connection_changes: int
    last_received_at: datetime | None
    error: str | None
