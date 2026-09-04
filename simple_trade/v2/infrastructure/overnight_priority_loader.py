"""从 V2 决策事件中只读恢复前一交易日优先观察池。"""

import asyncio
from datetime import date, datetime, timedelta
import json
from typing import Protocol

from ..domain.candidates import OvernightPriority


class OvernightPriorityDatabasePort(Protocol):
    def execute_query(self, query: str, params: tuple | None = None) -> list: ...


class OvernightPriorityLoader:
    SOURCE = "v2.candidate-coordinator"
    MIN_SCORE = 65.0
    MAX_DAILY_PERCENTILE = 0.70
    MAX_EXTENSION_ATR = 1.75
    MIN_MEMORY_SCORE = 65.0
    MIN_MARKET_BREADTH = 0.40
    MIN_BUY_EVENTS = 3
    MAX_ITEMS = 30
    ENGAGED_STATES = {"SETUP", "WATCHING", "CONFIRMED"}
    POSITIVE_MEMORY_STATES = {"ABSORBING", "REVERSING", "ACCUMULATING"}
    LATE_OUTFLOW_REASONS = {
        "LARGE_OUTFLOW_OFFSETS_INFLOW",
        "CAPITAL_MEMORY_TURNED_DISTRIBUTING",
    }

    def __init__(self, db: OvernightPriorityDatabasePort) -> None:
        self._db = db

    async def load(self, as_of: datetime) -> tuple[OvernightPriority, ...]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of 必须包含时区")
        target_date = as_of.date().isoformat()
        date_rows = await asyncio.to_thread(
            self._db.execute_query,
            "SELECT exchange_time FROM v2_decision_events "
            "WHERE source=? AND exchange_time<? "
            "ORDER BY exchange_time DESC LIMIT 1",
            (self.SOURCE, target_date),
        )
        source_date = (
            str(date_rows[0][0])[:10] if date_rows and date_rows[0][0] else ""
        )
        if not source_date:
            return ()
        if (date.fromisoformat(target_date) - date.fromisoformat(source_date)).days > 7:
            return ()
        rows = await asyncio.to_thread(
            self._db.execute_query,
            "SELECT stock_code, exchange_time, new_state, reason_code, payload_json "
            "FROM v2_decision_events WHERE source=? AND exchange_time>=? "
            "AND exchange_time<? ORDER BY stock_code, exchange_time, id",
            (
                self.SOURCE,
                source_date,
                (date.fromisoformat(source_date) + timedelta(days=1)).isoformat(),
            ),
        )
        return self._build(rows, source_date)

    @classmethod
    def _build(cls, rows: list, source_date: str) -> tuple[OvernightPriority, ...]:
        engaged: set[str] = set()
        qualified: dict[str, OvernightPriority] = {}
        qualified_at: dict[str, datetime] = {}
        late_outflow_at: dict[str, datetime] = {}
        latest_memory: dict[str, tuple[datetime, str, float]] = {}

        for row in rows:
            code = str(row[0] or "").strip().upper()
            if not code:
                continue
            try:
                observed_at = datetime.fromisoformat(str(row[1]))
            except (TypeError, ValueError):
                continue
            if str(row[2] or "") in cls.ENGAGED_STATES:
                engaged.add(code)
            reason = str(row[3] or "")
            if reason in cls.LATE_OUTFLOW_REASONS:
                late_outflow_at[code] = observed_at
            try:
                payload = json.loads(row[4] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            feature = payload.get("feature_snapshot") or {}
            memory = feature.get("capital_memory") or {}
            memory_state = str(memory.get("state") or "")
            day_main_net = cls._number(memory.get("day_main_net"))
            if memory:
                latest_memory[code] = (observed_at, memory_state, day_main_net)
            item = cls._priority(code, observed_at, reason, payload)
            if item is None:
                continue
            previous = qualified.get(code)
            if previous is None or (item.score, item.source_time) > (
                previous.score,
                previous.source_time,
            ):
                qualified[code] = item
                qualified_at[code] = observed_at

        accepted = []
        for code, item in qualified.items():
            if code not in engaged:
                continue
            outflow_at = late_outflow_at.get(code)
            if outflow_at is not None and outflow_at > qualified_at[code]:
                continue
            latest = latest_memory.get(code)
            if latest is not None and (
                latest[1] == "DISTRIBUTING" or latest[2] <= 0
            ):
                continue
            accepted.append(item)
        accepted.sort(
            key=lambda item: (
                item.score,
                item.capital_memory_score,
                item.independent_buy_events,
                item.day_main_net,
            ),
            reverse=True,
        )
        return tuple(accepted[: cls.MAX_ITEMS])

    @classmethod
    def _priority(
        cls,
        code: str,
        observed_at: datetime,
        reason: str,
        payload: dict,
    ) -> OvernightPriority | None:
        score = payload.get("candidate_score") or {}
        feature = payload.get("feature_snapshot") or {}
        quote = feature.get("quote") or {}
        position = feature.get("price_position") or {}
        memory = feature.get("capital_memory") or {}
        market = feature.get("market_context") or {}
        activity = feature.get("activity") or {}
        liquidity = feature.get("liquidity") or {}
        windows = feature.get("tick_windows") or ()

        total_score = cls._number(score.get("total"))
        percentile = cls._number(position.get("daily_percentile"), default=1.0)
        atr_percent = cls._number(position.get("atr_percent"))
        distance_to_ma20 = cls._number(position.get("distance_to_ma20"))
        extension_atr = (
            distance_to_ma20 / atr_percent if atr_percent > 0 else float("inf")
        )
        memory_score = cls._number(memory.get("score"))
        day_main_net = cls._number(memory.get("day_main_net"))
        decayed_main_net = cls._number(memory.get("decayed_main_net"))
        buy_events = max(
            [int(cls._number(memory.get("recent_15m_buy_events")))]
            + [int(cls._number(item.get("independent_buy_events"))) for item in windows]
        )
        reference_price = cls._number(quote.get("last_price"))
        if not (
            total_score >= cls.MIN_SCORE
            and percentile <= cls.MAX_DAILY_PERCENTILE
            and extension_atr <= cls.MAX_EXTENSION_ATR
            and memory.get("state") in cls.POSITIVE_MEMORY_STATES
            and memory_score >= cls.MIN_MEMORY_SCORE
            and day_main_net > 0
            and decayed_main_net > 0
            and buy_events >= cls.MIN_BUY_EVENTS
            and cls._number(market.get("market_breadth")) >= cls.MIN_MARKET_BREADTH
            and int(cls._number(market.get("market_sample_size"))) >= 20
            and activity.get("is_active") is True
            and cls._number(liquidity.get("score")) >= 30
            and reference_price > 0
        ):
            return None
        return OvernightPriority(
            stock_code=code,
            source_date=observed_at.date().isoformat(),
            source_time=observed_at,
            score=round(total_score, 4),
            reference_price=reference_price,
            daily_percentile=percentile,
            atr_percent=atr_percent,
            capital_memory_score=round(memory_score, 4),
            day_main_net=day_main_net,
            independent_buy_events=buy_events,
            source_reason=reason or "PREVIOUS_DAY_CAPITAL_SETUP",
        )

    @staticmethod
    def _number(value, *, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError):
            return default
