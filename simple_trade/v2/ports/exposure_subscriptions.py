"""Market-data protection for existing risk; never an order execution interface."""

from typing import Protocol


class ExposureSubscriptionPort(Protocol):
    def protect_exposure(self, stock_codes: tuple[str, ...]) -> None:
        """Replace only this owner's protection, without network or disk I/O."""
        ...

    def subscribe_exposure(self, stock_code: str) -> bool:
        """Ensure QUOTE/TICKER coverage and verify the resulting subscription state."""
        ...
