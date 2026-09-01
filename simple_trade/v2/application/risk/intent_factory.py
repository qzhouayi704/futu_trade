"""Build reviewable intents from actionable decision events."""

from ...domain.decisions import DecisionEvent
from ...domain.enums import DecisionAction, EventType, IntentType, OrderSide, RuntimeMode
from ...domain.orders import OrderLeg, TradeIntent
from ...domain.risk import RiskContext, RiskLimits


class IntentFactory:
    def __init__(self, mode: RuntimeMode, limits: RiskLimits) -> None:
        self._mode = mode
        self._limits = limits

    def build(self, event: DecisionEvent, context: RiskContext) -> TradeIntent | None:
        if event.event_type is EventType.BUY_CONFIRMED:
            return self._buy(event, context)
        if event.event_type is EventType.EXIT_RISK_CONFIRMED:
            return self._sell(event)
        if event.event_type is EventType.ROTATION_PROPOSED:
            return self._rotate(event)
        if event.event_type is EventType.POSITION_EFFICIENCY_CHANGED:
            decision = event.payload.get("decision") or {}
            if decision.get("action") == DecisionAction.PROTECT_PROFIT.value:
                return self._sell(event)
        return None

    def _buy(self, event: DecisionEvent, context: RiskContext) -> TradeIntent | None:
        feature = event.payload.get("feature_snapshot") or {}
        quote = feature.get("quote") or {}
        price = self._positive(quote.get("last_price"))
        lot = self._integer(quote.get("lot_size"))
        if price <= 0 or lot <= 0:
            return None
        account = context.account
        budget = min(
            account.available_funds * (1 - self._limits.min_cash_reserve_ratio),
            account.total_assets * self._limits.max_single_position_ratio,
        )
        quantity = int(max(0.0, budget) / price / lot) * lot
        quantity = max(lot, quantity)
        return TradeIntent(
            source_event_id=event.event_id,
            intent_type=IntentType.BUY,
            created_at=event.exchange_time,
            mode=self._mode,
            buy_leg=OrderLeg(
                stock_code=event.stock_code,
                side=OrderSide.BUY,
                quantity=quantity,
                reference_price=price,
                lot_size=lot,
            ),
        )

    def _sell(self, event: DecisionEvent) -> TradeIntent | None:
        position = event.payload.get("position") or {}
        quantity = self._integer(position.get("sellable_quantity"))
        price = self._positive(position.get("current_price"))
        lot = self._integer(position.get("lot_size")) or None
        if quantity <= 0 or price <= 0:
            return None
        return TradeIntent(
            source_event_id=event.event_id,
            intent_type=IntentType.SELL,
            created_at=event.exchange_time,
            mode=self._mode,
            sell_leg=OrderLeg(
                stock_code=event.stock_code,
                side=OrderSide.SELL,
                quantity=quantity,
                reference_price=price,
                lot_size=lot,
            ),
        )

    def _rotate(self, event: DecisionEvent) -> TradeIntent | None:
        rotation = event.payload.get("rotation") or {}
        position = event.payload.get("position") or {}
        sell_qty = self._integer(rotation.get("sellable_quantity"))
        buy_qty = self._integer(rotation.get("estimated_buy_quantity"))
        sell_price = self._positive(position.get("current_price"))
        buy_price = self._positive(rotation.get("estimated_buy_price"))
        buy_lot = self._integer(rotation.get("buy_lot_size"))
        if not buy_price:
            buy_price = self._positive(rotation.get("buy_price"))
        if min(sell_qty, buy_qty, sell_price, buy_price, buy_lot) <= 0:
            return None
        return TradeIntent(
            source_event_id=event.event_id,
            intent_type=IntentType.ROTATE,
            created_at=event.exchange_time,
            mode=self._mode,
            sell_leg=OrderLeg(
                stock_code=event.stock_code,
                side=OrderSide.SELL,
                quantity=sell_qty,
                reference_price=sell_price,
                lot_size=self._integer(position.get("lot_size")) or None,
            ),
            buy_leg=OrderLeg(
                stock_code=str(rotation.get("buy_stock_code") or ""),
                side=OrderSide.BUY,
                quantity=buy_qty,
                reference_price=buy_price,
                lot_size=buy_lot,
            ),
        )

    @staticmethod
    def _integer(value) -> int:
        try:
            return max(0, int(float(value or 0)))
        except (TypeError, ValueError, OverflowError):
            return 0

    @staticmethod
    def _positive(value) -> float:
        try:
            return max(0.0, float(value or 0))
        except (TypeError, ValueError, OverflowError):
            return 0.0
