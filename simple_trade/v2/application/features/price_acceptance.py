"""Intraday VWAP tape and confirmation-price acceptance feature."""

from dataclasses import dataclass
from datetime import datetime
import threading

from ...domain.enums import DataQuality
from ...domain.features import PriceAcceptance
from ...domain.market import TickTrade
from .quality import clamp


@dataclass(frozen=True, slots=True)
class PriceTapeSnapshot:
    as_of: datetime
    vwap: float | None
    confirmation_price: float | None
    peak_since_confirmation: float | None
    sample_count: int
    quality: DataQuality


@dataclass(slots=True)
class _TapeState:
    trade_date: object
    turnover: float = 0.0
    volume: int = 0
    confirmation_price: float | None = None
    peak_since_confirmation: float | None = None
    sample_count: int = 0
    quality: DataQuality = DataQuality.GOOD
    as_of: datetime | None = None


class PriceTape:
    def __init__(self) -> None:
        self._states: dict[str, _TapeState] = {}
        self._lock = threading.RLock()

    def on_tick(self, tick: TickTrade) -> None:
        with self._lock:
            state = self._state_for(tick.stock_code, tick.exchange_time)
            state.turnover += tick.turnover or tick.price * tick.volume
            state.volume += tick.volume
            state.sample_count += 1
            state.as_of = tick.exchange_time
            if tick.quality is DataQuality.INVALID:
                state.quality = DataQuality.INVALID
            elif tick.quality is DataQuality.DEGRADED and state.quality is DataQuality.GOOD:
                state.quality = DataQuality.DEGRADED
            if state.confirmation_price is not None:
                state.peak_since_confirmation = max(
                    state.peak_since_confirmation or tick.price,
                    tick.price,
                )

    def confirm(self, stock_code: str, price: float, as_of: datetime) -> None:
        if price <= 0:
            raise ValueError("confirmation price must be positive")
        with self._lock:
            state = self._state_for(stock_code, as_of)
            state.confirmation_price = price
            state.peak_since_confirmation = price
            state.as_of = as_of

    def observe_price(self, stock_code: str, price: float, as_of: datetime) -> None:
        if price <= 0:
            return
        with self._lock:
            state = self._states.get(stock_code)
            if state is None or state.trade_date != as_of.date():
                return
            if state.confirmation_price is not None:
                state.peak_since_confirmation = max(
                    state.peak_since_confirmation or price,
                    price,
                )
            state.as_of = as_of

    def snapshot(self, stock_code: str, as_of: datetime) -> PriceTapeSnapshot:
        with self._lock:
            state = self._states.get(stock_code)
            if state is None or state.trade_date != as_of.date():
                return PriceTapeSnapshot(
                    as_of=as_of,
                    vwap=None,
                    confirmation_price=None,
                    peak_since_confirmation=None,
                    sample_count=0,
                    quality=DataQuality.INVALID,
                )
            vwap = state.turnover / state.volume if state.volume > 0 else None
            quality = state.quality if vwap is not None else DataQuality.INVALID
            return PriceTapeSnapshot(
                as_of=as_of,
                vwap=vwap,
                confirmation_price=state.confirmation_price,
                peak_since_confirmation=state.peak_since_confirmation,
                sample_count=state.sample_count,
                quality=quality,
            )

    def _state_for(self, stock_code: str, as_of: datetime) -> _TapeState:
        state = self._states.get(stock_code)
        if state is None or state.trade_date != as_of.date():
            state = _TapeState(trade_date=as_of.date())
            self._states[stock_code] = state
        return state


class PriceAcceptanceFeature:
    def calculate(
        self,
        *,
        as_of: datetime,
        current_price: float,
        tape: PriceTapeSnapshot,
    ) -> PriceAcceptance:
        reasons: list[str] = []
        confirmation = tape.confirmation_price
        vwap = tape.vwap
        peak = tape.peak_since_confirmation
        confirmation_return = (
            (current_price / confirmation - 1.0) * 100.0
            if confirmation and current_price > 0
            else None
        )
        vwap_distance = (
            (current_price / vwap - 1.0) * 100.0 if vwap and current_price > 0 else None
        )
        drawdown = (
            (current_price / peak - 1.0) * 100.0 if peak and current_price > 0 else None
        )
        if confirmation is None:
            reasons.append("CONFIRMATION_PRICE_MISSING")
        if vwap is None:
            reasons.append("VWAP_MISSING")
        if peak is None:
            reasons.append("CONFIRMATION_PEAK_MISSING")

        confirmation_basis = confirmation_return if confirmation_return is not None else -2.0
        vwap_basis = vwap_distance if vwap_distance is not None else -2.0
        drawdown_basis = drawdown if drawdown is not None else -4.0
        confirmation_score = clamp((confirmation_basis + 1.0) / 2.0 * 100.0)
        vwap_score = clamp((vwap_basis + 0.3) / 1.3 * 100.0)
        drawdown_score = clamp((drawdown_basis + 3.0) / 2.5 * 100.0)
        score = round(
            confirmation_score * 0.40 + vwap_score * 0.35 + drawdown_score * 0.25,
            4,
        )
        accepted = bool(
            confirmation_return is not None
            and vwap_distance is not None
            and drawdown is not None
            and confirmation_return >= 0.0
            and vwap_distance >= -0.3
            and drawdown >= -1.0
        )
        quality = tape.quality
        if reasons:
            quality = DataQuality.INVALID if len(reasons) == 3 else DataQuality.DEGRADED
        return PriceAcceptance(
            as_of=as_of,
            score=score,
            confirmation_price=confirmation,
            current_price=current_price,
            vwap=vwap,
            return_from_confirmation_pct=(
                round(confirmation_return, 6) if confirmation_return is not None else None
            ),
            distance_to_vwap_pct=(
                round(vwap_distance, 6) if vwap_distance is not None else None
            ),
            drawdown_from_peak_pct=(round(drawdown, 6) if drawdown is not None else None),
            accepted=accepted,
            quality=quality,
            reason_codes=tuple(reasons),
        )
