"""时间端口，支持实时与确定性回放替换。"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from ..domain.serialization import require_aware


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


@dataclass(slots=True)
class VirtualClock:
    current: datetime

    def __post_init__(self) -> None:
        require_aware(self.current, "current")

    def now(self) -> datetime:
        return self.current

    def set(self, value: datetime) -> None:
        require_aware(value, "value")
        if value < self.current:
            raise ValueError("VirtualClock 不能倒退")
        self.current = value

    def advance(self, delta: timedelta) -> datetime:
        if delta < timedelta(0):
            raise ValueError("VirtualClock 不能倒退")
        self.current += delta
        return self.current
