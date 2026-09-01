"""Explicit fail-closed mode gate for future broker execution."""

from ...config.defaults import EXECUTION_CONFIRMATION_TOKEN
from ...domain.enums import RuntimeMode


class ExecutionModeGate:
    def __init__(self, *, enabled: bool, confirmation: str) -> None:
        self._enabled = enabled
        self._confirmed = confirmation == EXECUTION_CONFIRMATION_TOKEN

    def allows(self, mode: RuntimeMode) -> bool:
        return bool(
            mode in {RuntimeMode.SEMI, RuntimeMode.FULL}
            and self._enabled
            and self._confirmed
        )

    def require(self, mode: RuntimeMode) -> None:
        if not self.allows(mode):
            raise PermissionError(
                f"V2 execution blocked: mode={mode.value}, explicit gate not satisfied"
            )
