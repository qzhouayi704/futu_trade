"""Fail-closed account, position, order, and frequency risk checks."""

from datetime import datetime
from typing import Protocol

from ...domain.enums import DataQuality, IntentType, RiskResult
from ...domain.orders import RiskDecision, TradeIntent
from ...domain.risk import RiskContext, RiskLimits


class FrequencyGuardPort(Protocol):
    def can_buy(self, stock_code: str, when: datetime) -> tuple[bool, str]: ...

    def can_sell(self, stock_code: str, when: datetime) -> tuple[bool, str]: ...


class RiskEngine:
    def __init__(
        self,
        limits: RiskLimits,
        frequency_guard: FrequencyGuardPort | None,
    ) -> None:
        self._limits = limits
        self._frequency_guard = frequency_guard

    def evaluate(self, intent: TradeIntent, context: RiskContext) -> RiskDecision:
        reasons: list[str] = []
        if not context.market_trading:
            reasons.append("MARKET_NOT_TRADING")
        if self._frequency_guard is None:
            reasons.append("FREQUENCY_GUARD_UNAVAILABLE")

        positions = {item.stock_code: item for item in context.positions}
        active_codes = {item.stock_code for item in context.active_orders}
        legs = tuple(item for item in (intent.sell_leg, intent.buy_leg) if item is not None)
        for leg in legs:
            if leg.stock_code in active_codes:
                reasons.append(f"ACTIVE_ORDER_CONFLICT:{leg.stock_code}")
            if leg.reference_price is None or leg.reference_price <= 0:
                reasons.append(f"REFERENCE_PRICE_UNAVAILABLE:{leg.stock_code}")

        if intent.sell_leg is not None:
            self._check_sell(intent.sell_leg, positions, context.checked_at, reasons)
        if intent.buy_leg is not None:
            self._check_buy(intent, context, positions, reasons)

        result = RiskResult.REJECTED if reasons else RiskResult.APPROVED
        return RiskDecision(
            intent_id=intent.intent_id,
            result=result,
            checked_at=context.checked_at,
            reason_codes=tuple(reasons) if reasons else ("RISK_CHECKS_PASSED",),
        )

    def _check_sell(self, leg, positions, checked_at, reasons: list[str]) -> None:
        position = positions.get(leg.stock_code)
        if position is None:
            reasons.append(f"SELL_POSITION_NOT_FOUND:{leg.stock_code}")
            return
        if leg.quantity > position.sellable_quantity:
            reasons.append(f"SELLABLE_QUANTITY_EXCEEDED:{leg.stock_code}")
        if self._frequency_guard is not None:
            allowed, reason = self._frequency_guard.can_sell(leg.stock_code, checked_at)
            if not allowed:
                reasons.append(f"SELL_FREQUENCY_BLOCKED:{reason}")

    def _check_buy(self, intent, context, positions, reasons: list[str]) -> None:
        leg = intent.buy_leg
        if leg is None:
            return
        if leg.lot_size is None:
            reasons.append(f"LOT_SIZE_UNAVAILABLE:{leg.stock_code}")
        elif leg.quantity % leg.lot_size:
            reasons.append(f"BUY_NOT_BOARD_LOT:{leg.stock_code}")
        if (
            intent.intent_type is IntentType.BUY
            and leg.stock_code not in positions
            and len(positions) >= self._limits.max_positions
        ):
            reasons.append("MAX_POSITION_COUNT_REACHED")
        account = context.account
        if account.quality is not DataQuality.GOOD or account.total_assets <= 0:
            reasons.append("ACCOUNT_CAPACITY_UNAVAILABLE")
        elif leg.reference_price is not None:
            amount = leg.quantity * leg.reference_price
            spendable = account.available_funds * (1 - self._limits.min_cash_reserve_ratio)
            max_single = account.total_assets * self._limits.max_single_position_ratio
            if amount > spendable:
                reasons.append("AVAILABLE_FUNDS_INSUFFICIENT")
            if amount > max_single:
                reasons.append("MAX_SINGLE_POSITION_EXCEEDED")
        if self._frequency_guard is not None:
            allowed, reason = self._frequency_guard.can_buy(leg.stock_code, context.checked_at)
            if not allowed:
                reasons.append(f"BUY_FREQUENCY_BLOCKED:{reason}")
