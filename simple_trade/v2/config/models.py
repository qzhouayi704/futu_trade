"""V2 环境配置与规则版本。"""

from dataclasses import dataclass
import hashlib
import json
import os

from ...utils.env_helper import env_flag
from ..domain.enums import RuntimeMode
from .defaults import (
    DEFAULT_EVENT_BUS_CAPACITY,
    DEFAULT_EVENT_SCHEMA_VERSION,
    DEFAULT_NOTIFICATION_EXPIRY_SECONDS,
    DEFAULT_NOTIFICATION_MAX_ATTEMPTS,
    DEFAULT_RULESET_REVISION,
    DEFAULT_STRATEGY_NAME,
    DEFAULT_WRITE_TIMEOUT_SECONDS,
    EXECUTION_CONFIRMATION_TOKEN,
)


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = int(raw)
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} 必须在 {minimum} 到 {maximum} 之间")
    return value


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = float(raw)
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} 必须在 {minimum} 到 {maximum} 之间")
    return value


@dataclass(frozen=True, slots=True)
class V2Config:
    enabled: bool = False
    mode: RuntimeMode = RuntimeMode.SHADOW
    event_bus_capacity: int = DEFAULT_EVENT_BUS_CAPACITY
    event_schema_version: int = DEFAULT_EVENT_SCHEMA_VERSION
    write_timeout_seconds: float = DEFAULT_WRITE_TIMEOUT_SECONDS
    strategy_name: str = DEFAULT_STRATEGY_NAME
    ruleset_revision: str = DEFAULT_RULESET_REVISION
    max_positions: int = 5
    max_single_position_ratio: float = 0.30
    min_cash_reserve_ratio: float = 0.30
    notification_expiry_seconds: int = DEFAULT_NOTIFICATION_EXPIRY_SECONDS
    notification_max_attempts: int = DEFAULT_NOTIFICATION_MAX_ATTEMPTS
    execution_enabled: bool = False
    execution_confirmation: str = ""

    def __post_init__(self) -> None:
        if self.event_bus_capacity <= 0:
            raise ValueError("event_bus_capacity 必须大于 0")
        if self.event_schema_version < 1:
            raise ValueError("event_schema_version 必须大于 0")
        if self.write_timeout_seconds <= 0:
            raise ValueError("write_timeout_seconds 必须大于 0")
        if not self.strategy_name.strip() or not self.ruleset_revision.strip():
            raise ValueError("strategy_name 和 ruleset_revision 不能为空")
        if self.max_positions <= 0:
            raise ValueError("max_positions 必须大于 0")
        if not 0 < self.max_single_position_ratio <= 1:
            raise ValueError("max_single_position_ratio 必须在 (0, 1] 范围")
        if not 0 <= self.min_cash_reserve_ratio < 1:
            raise ValueError("min_cash_reserve_ratio 必须在 [0, 1) 范围")
        if self.notification_expiry_seconds <= 0 or self.notification_max_attempts <= 0:
            raise ValueError("notification expiry/attempts 必须大于 0")
        if self.execution_enabled and self.execution_confirmation != EXECUTION_CONFIRMATION_TOKEN:
            raise ValueError("V2 execution confirmation token 无效")

    @classmethod
    def from_env(cls) -> "V2Config":
        raw_mode = os.getenv("V2_MODE", RuntimeMode.SHADOW.value).strip().lower()
        try:
            mode = RuntimeMode(raw_mode)
        except ValueError as exc:
            allowed = ", ".join(item.value for item in RuntimeMode)
            raise ValueError(f"V2_MODE={raw_mode!r} 无效，可选值: {allowed}") from exc
        return cls(
            enabled=env_flag("V2_ENABLED", False),
            mode=mode,
            event_bus_capacity=_env_int(
                "V2_EVENT_BUS_CAPACITY",
                DEFAULT_EVENT_BUS_CAPACITY,
                100,
                1_000_000,
            ),
            event_schema_version=_env_int(
                "V2_EVENT_SCHEMA_VERSION",
                DEFAULT_EVENT_SCHEMA_VERSION,
                1,
                100,
            ),
            write_timeout_seconds=_env_float(
                "V2_WRITE_TIMEOUT_SECONDS",
                DEFAULT_WRITE_TIMEOUT_SECONDS,
                1.0,
                120.0,
            ),
            strategy_name=os.getenv("V2_STRATEGY_NAME", DEFAULT_STRATEGY_NAME).strip(),
            ruleset_revision=os.getenv("V2_RULESET_REVISION", DEFAULT_RULESET_REVISION).strip(),
            max_positions=_env_int("V2_MAX_POSITIONS", 5, 1, 100),
            max_single_position_ratio=_env_float(
                "V2_MAX_SINGLE_POSITION_RATIO", 0.30, 0.01, 1.0
            ),
            min_cash_reserve_ratio=_env_float(
                "V2_MIN_CASH_RESERVE_RATIO", 0.30, 0.0, 0.99
            ),
            notification_expiry_seconds=_env_int(
                "V2_NOTIFICATION_EXPIRY_SECONDS",
                DEFAULT_NOTIFICATION_EXPIRY_SECONDS,
                10,
                86_400,
            ),
            notification_max_attempts=_env_int(
                "V2_NOTIFICATION_MAX_ATTEMPTS",
                DEFAULT_NOTIFICATION_MAX_ATTEMPTS,
                1,
                10,
            ),
            execution_enabled=env_flag("V2_EXECUTION_ENABLED", False),
            execution_confirmation=os.getenv("V2_EXECUTION_CONFIRMATION", "").strip(),
        )

    @property
    def strategy_version(self) -> str:
        versioned = {
            "event_schema_version": self.event_schema_version,
            "ruleset_revision": self.ruleset_revision,
            "strategy_name": self.strategy_name,
            "max_positions": self.max_positions,
            "max_single_position_ratio": self.max_single_position_ratio,
            "min_cash_reserve_ratio": self.min_cash_reserve_ratio,
        }
        encoded = json.dumps(versioned, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return f"{self.strategy_name}-{hashlib.sha256(encoded).hexdigest()[:12]}"
