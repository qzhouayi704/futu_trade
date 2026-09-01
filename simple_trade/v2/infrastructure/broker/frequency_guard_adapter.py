"""Timezone-safe adapter around the existing trade frequency guard."""

from datetime import datetime
from zoneinfo import ZoneInfo


class FrequencyGuardAdapter:
    def __init__(self, guard) -> None:
        self._guard = guard

    def can_buy(self, stock_code: str, when: datetime) -> tuple[bool, str]:
        local = self._local_naive(when)
        return self._guard.can_buy(stock_code, current_time=local)

    def can_sell(self, stock_code: str, when: datetime) -> tuple[bool, str]:
        local = self._local_naive(when)
        return self._guard.can_sell(stock_code, current_time=local)

    @staticmethod
    def _local_naive(when: datetime) -> datetime:
        return when.astimezone(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
