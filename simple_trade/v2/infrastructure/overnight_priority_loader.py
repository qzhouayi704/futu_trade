"""从有界事件日志重建三交易日跨日观察投影。"""

import asyncio
from datetime import date, datetime, timedelta
from dataclasses import replace
import json
from math import isfinite
from typing import Protocol

from ...utils.trade_time import market_datetime
from ..domain.candidates import OVERNIGHT_HARD_INVALIDATIONS, OvernightObservation, OvernightPriority, OvernightStatus
from .db_read import strict_reader


class OvernightPriorityDatabasePort(Protocol):
    def execute_query(self, query: str, params: tuple | None = None) -> list: ...


class TradingDayCalendarPort(Protocol):
    def known_trading_days(self, market: str, start: date, end: date, *, refresh: bool = True) -> tuple[str, ...] | None: ...


class CalendarUnavailableError(RuntimeError):
    pass


_EVIDENCE_PATHS = (
    "candidate_score.total", "feature_snapshot.quote.last_price",
    "feature_snapshot.price_position.daily_percentile", "feature_snapshot.price_position.atr_percent",
    "feature_snapshot.price_position.distance_to_ma20", "feature_snapshot.capital_memory.state",
    "feature_snapshot.capital_memory.score", "feature_snapshot.capital_memory.day_main_net",
    "feature_snapshot.capital_memory.decayed_main_net", "feature_snapshot.capital_memory.recent_15m_buy_events",
    "feature_snapshot.market_context.market_breadth", "feature_snapshot.market_context.market_sample_size",
    "feature_snapshot.activity", "feature_snapshot.liquidity.score",
)
_COMPACT_EVIDENCE = (
    "CASE WHEN json_valid(payload_json) THEN json_set('{}',"
    + ",".join(f"'$.{path}',json_extract(payload_json,'$.{path}')" for path in _EVIDENCE_PATHS)
    + ",'$.feature_snapshot.independent_buy_events',"
    "(SELECT MAX(json_extract(value,'$.independent_buy_events')) "
    "FROM json_each(payload_json,'$.feature_snapshot.tick_windows'))) ELSE '{}' END"
)


class OvernightPriorityLoader:
    SOURCE = "v2.candidate-coordinator"
    MIN_SCORE = 65.0
    MAX_DAILY_PERCENTILE = 0.70
    MAX_EXTENSION_ATR = 1.75
    MIN_MEMORY_SCORE = 65.0
    MIN_MARKET_BREADTH = 0.40
    MIN_BUY_EVENTS = 3
    MAX_ITEMS = 30
    MAX_SESSIONS = 3
    ROW_LIMIT = 30_000
    READ_TIMEOUT_SECONDS = 15.0
    ENGAGED_STATES = {"SETUP", "WATCHING", "CONFIRMED"}
    POSITIVE_MEMORY_STATES = {"ABSORBING", "REVERSING", "ACCUMULATING"}
    LATE_OUTFLOW_REASONS = {
        "LARGE_OUTFLOW_OFFSETS_INFLOW",
        "CAPITAL_MEMORY_TURNED_DISTRIBUTING",
    }
    INVALIDATION_REASONS = OVERNIGHT_HARD_INVALIDATIONS

    def __init__(
        self, db: OvernightPriorityDatabasePort, *, calendar: TradingDayCalendarPort | None = None,
        strategy_version: str | None = None,
    ) -> None:
        self._db = strict_reader(db, timeout_seconds=self.READ_TIMEOUT_SECONDS)
        self._calendar = calendar
        self._strategy_version = strategy_version
        self.observations: tuple[OvernightObservation, ...] = ()
        self.market_open = False

    async def load(self, as_of: datetime) -> tuple[OvernightPriority, ...]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of 必须包含时区")
        target_date = market_datetime(as_of).date().isoformat()
        target = date.fromisoformat(target_date)
        self.observations = ()
        if self._calendar is None:
            raise CalendarUnavailableError("跨日期限缺少已知交易日历")
        days = await asyncio.wait_for(asyncio.to_thread(
            self._calendar.known_trading_days, "HK", target - timedelta(days=20), target + timedelta(days=10),
        ), timeout=8.0)
        if days is None:
            raise CalendarUnavailableError("交易日历窗口不可用，暂停跨日提名")
        days = tuple(sorted(set(days)))
        self.market_open = target_date in days
        previous = [day for day in days if day < target_date][-self.MAX_SESSIONS - 1:]
        if not self.market_open or not previous:
            return ()
        version_sql = " AND strategy_version=?" if self._strategy_version else ""
        rows = await asyncio.to_thread(
            self._db.execute_query,
            f"SELECT stock_code, exchange_time, new_state, reason_code, {_COMPACT_EVIDENCE}, "
            "event_id, received_time, strategy_version "
            "FROM v2_decision_events WHERE source=? AND exchange_time>=? "
            "AND exchange_time<? AND stock_code LIKE 'HK.%' "
            "AND new_state IN ('SETUP','WATCHING','CONFIRMED','INVALIDATED')"
            f"{version_sql} ORDER BY exchange_time, id LIMIT ?",
            (
                self.SOURCE,
                (date.fromisoformat(previous[0]) - timedelta(days=1)).isoformat(),
                (target + timedelta(days=1)).isoformat(),
                *((self._strategy_version,) if self._strategy_version else ()),
                self.ROW_LIMIT + 1,
            ),
        )
        if len(rows) > self.ROW_LIMIT:
            raise RuntimeError("跨日事件读取超限，禁止使用截断结果")
        self.observations = self._project(rows, days, as_of, set(previous))
        return tuple(item.priority for item in self.observations if item.retained)[:self.MAX_ITEMS]

    @classmethod
    def _project(
        cls, rows: list, days: tuple[str, ...], as_of: datetime, source_days: set[str],
    ) -> tuple[OvernightObservation, ...]:
        target_date = market_datetime(as_of).date().isoformat()
        observations: dict[str, OvernightObservation] = {}
        timed_rows = [
            (observed_at, row) for row in rows
            if (observed_at := market_datetime(row[1], str(row[0]))) is not None
            and observed_at <= as_of
            and (received_at := market_datetime(row[6], str(row[0]))) is not None
            and received_at <= as_of
            and (observed_at.date().isoformat() in source_days or observed_at.date().isoformat() == target_date)
        ]
        for observed_at, row in sorted(timed_rows, key=lambda item: item[0]):
            code = str(row[0] or "").strip().upper()
            if not code.startswith("HK."):
                continue
            reason = str(row[3] or "")
            invalid = reason in cls.INVALIDATION_REASONS or str(row[2]) == "INVALIDATED"
            try:
                payload = json.loads(row[4] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            feature = payload.get("feature_snapshot") or {}
            memory = feature.get("capital_memory") or {}
            memory_state = str(memory.get("state") or "")
            day_main_net = cls._number(memory.get("day_main_net"))
            historical = observed_at.date().isoformat() < target_date
            priority = None
            if (
                historical and not invalid and str(row[2]) in cls.ENGAGED_STATES
                and not reason.startswith("OVERNIGHT_PRIORITY_")
            ):
                priority = cls._priority(code, observed_at, reason, payload)
            if priority is not None:
                source_index = days.index(priority.source_date)
                if source_index + cls.MAX_SESSIONS >= len(days):
                    raise CalendarUnavailableError("日历不足以确定跨日到期日")
                priority = replace(
                    priority, setup_id=str(row[5]), eligible_date=target_date,
                    expires_date=days[source_index + cls.MAX_SESSIONS],
                    age_sessions=days.index(target_date) - source_index,
                )
                observations[code] = OvernightObservation(
                    priority=priority, status=OvernightStatus.WATCHING,
                    reason_code="OVERNIGHT_PRIORITY_PENDING_RECONFIRMATION", last_event_time=observed_at,
                )
                continue
            previous = observations.get(code)
            if previous is None:
                continue
            status = previous.status
            if reason in cls.INVALIDATION_REASONS or memory_state == "DISTRIBUTING":
                status = OvernightStatus.INVALIDATED
                reason = reason if reason in cls.INVALIDATION_REASONS else "CAPITAL_MEMORY_TURNED_DISTRIBUTING"
            elif status is not OvernightStatus.INVALIDATED:
                if invalid or (historical and memory and day_main_net <= 0):
                    status = OvernightStatus.SUSPENDED
                    reason = reason if invalid else "OVERNIGHT_PRIORITY_CAPITAL_UNRESOLVED"
                elif str(row[2]) in cls.ENGAGED_STATES and reason.startswith("OVERNIGHT_PRIORITY_"):
                    status = OvernightStatus.WATCHING
                else:
                    reason = previous.reason_code
            else:
                reason = previous.reason_code
            observations[code] = replace(previous, status=status, reason_code=reason, last_event_time=observed_at)

        result = [
            replace(item, status=OvernightStatus.EXPIRED, reason_code="OVERNIGHT_PRIORITY_EXPIRED")
            if item.priority.age_sessions > cls.MAX_SESSIONS else item
            for item in observations.values()
        ]
        result.sort(key=lambda item: (not item.retained, -item.priority.score, item.priority.age_sessions, item.priority.stock_code))
        return tuple(result)

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
            + [int(cls._number(feature.get("independent_buy_events")))]
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
            result = float(value)
            return result if isfinite(result) else default
        except (TypeError, ValueError, OverflowError):
            return default
