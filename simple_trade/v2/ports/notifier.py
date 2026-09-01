"""统一通知端口。"""

from typing import Protocol

from ..domain.decisions import NotificationEvent
from ..domain.enums import NotificationDeliveryResult


class NotifierPort(Protocol):
    async def send(
        self, event: NotificationEvent, *, attempt: int
    ) -> NotificationDeliveryResult: ...
