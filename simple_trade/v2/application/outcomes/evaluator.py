"""Pure incremental MFE/MAE and rotation-control evaluation."""

from datetime import time

from ...domain.market import QuoteSnapshot
from ...domain.outcomes import OutcomeRecord


class OutcomeEvaluator:
    CLOSE_CUTOFF = time(15, 55)

    def apply_quote(self, outcome: OutcomeRecord, quote: QuoteSnapshot) -> OutcomeRecord:
        if quote.exchange_time < outcome.signal_time:
            return outcome
        if quote.stock_code == outcome.control_stock_code:
            control_return = self._return_pct(quote.last_price, outcome.control_signal_price)
            return outcome.evolve(
                hold_control_return_pct=control_return,
                evaluated_at=quote.exchange_time,
            )
        if quote.stock_code != outcome.stock_code or quote.last_price <= 0:
            return outcome

        # Quote high/low cover the whole trading day and may predate the signal.
        # Only post-signal observations are valid for incremental MFE/MAE.
        high_return = self._return_pct(quote.last_price, outcome.signal_price)
        low_return = high_return
        current_return = self._return_pct(quote.last_price, outcome.signal_price)
        elapsed = max(0, int((quote.exchange_time - outcome.signal_time).total_seconds()))
        signal_day = outcome.signal_time.date()
        quote_day = quote.exchange_time.date()
        is_rotation = outcome.control_stock_code is not None

        updates = {
            "mfe_pct": max(outcome.mfe_pct, high_return),
            "mae_pct": min(outcome.mae_pct, low_return),
            "last_price": quote.last_price,
            "evaluated_at": quote.exchange_time,
            "rotation_return_pct": current_return if is_rotation else None,
        }
        if high_return > outcome.mfe_pct:
            updates["time_to_peak_seconds"] = elapsed
        for threshold, field in (
            (1.5, "time_to_1_5_seconds"),
            (3.0, "time_to_3_seconds"),
            (5.0, "time_to_5_seconds"),
        ):
            if getattr(outcome, field) is None and high_return >= threshold:
                updates[field] = elapsed
        if quote_day == signal_day and quote.exchange_time.timetz().replace(tzinfo=None) >= self.CLOSE_CUTOFF:
            updates["close_return_pct"] = current_return
        elif quote_day > signal_day:
            if outcome.close_return_pct is None and outcome.last_price is not None:
                updates["close_return_pct"] = self._return_pct(
                    outcome.last_price, outcome.signal_price
                )
            updates["next_day_return_pct"] = current_return
        return outcome.evolve(**updates)

    @staticmethod
    def _return_pct(price: float, basis: float | None) -> float:
        if basis is None or basis <= 0:
            return 0.0
        return round((price / basis - 1.0) * 100.0, 6)
