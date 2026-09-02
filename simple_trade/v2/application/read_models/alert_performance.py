"""Delivered-alert performance across later trading sessions."""

import asyncio
from collections import defaultdict
from datetime import date
import json


HORIZONS = (1, 3, 5, 10)
VALID_SCOPES = {"candidates", "watching", "alerts"}
STAGE_RANK = {"SETUP": 1, "WATCHING": 2, "CONFIRMED": 3}


class AlertPerformanceReader:
    def __init__(self, db) -> None:
        self._db = db

    async def history(
        self,
        *,
        trade_date: str | None = None,
        scope: str = "candidates",
    ) -> dict:
        selected_date = self._validated_date(trade_date)
        if scope not in VALID_SCOPES:
            raise ValueError("复盘范围必须是 candidates、watching 或 alerts")
        alerts = (
            await self._delivered_alerts(selected_date)
            if scope == "alerts"
            else await self._candidate_alerts(selected_date, scope=scope)
        )
        if not alerts:
            return self._empty(selected_date, scope)

        codes = sorted({item["stock_code"] for item in alerts})
        names, klines, intraday = await asyncio.gather(
            self._names(codes),
            self._klines(codes, selected_date),
            self._intraday(codes, selected_date),
        )
        items = [self._evaluate(item, names, klines, intraday) for item in alerts]
        return {
            "trade_date": selected_date,
            "scope": scope,
            "items": items,
            "count": len(items),
            "available_kline_through": max(
                (day for stock_days in klines.values() for day in stock_days),
                default=None,
            ),
            "intraday_coverage_count": sum(
                bool(intraday.get(item["stock_code"])) for item in alerts
            ),
            "summary": self._summary(items),
        }

    async def _delivered_alerts(self, selected_date: str) -> list[dict]:
        rows = await self._query(
            "SELECT e.event_id, e.event_type, e.stock_code, e.exchange_time, "
            "e.reason_code, e.strategy_version, i.intent_type, i.risk_result, "
            "i.buy_leg_json, i.sell_leg_json, n.delivered_at, "
            "o.mfe_pct, o.mae_pct, o.close_return_pct "
            "FROM v2_notification_log n "
            "JOIN v2_decision_events e ON e.event_id=n.decision_event_id "
            "JOIN v2_trade_intents i ON i.source_event_id=e.event_id "
            "LEFT JOIN v2_outcomes o ON o.decision_event_id=e.event_id "
            "WHERE n.channel='WECHAT' AND n.status='DELIVERED' "
            "AND substr(e.exchange_time,1,10)=? "
            "ORDER BY e.exchange_time, e.id",
            (selected_date,),
        )
        return self._collapse_delivered(rows)

    async def _candidate_alerts(self, selected_date: str, *, scope: str) -> list[dict]:
        states = ("WATCHING", "CONFIRMED") if scope == "watching" else (
            "SETUP", "WATCHING", "CONFIRMED"
        )
        placeholders = ",".join("?" for _ in states)
        rows = await self._query(
            "SELECT e.event_id, e.event_type, e.stock_code, e.exchange_time, "
            "e.reason_code, e.strategy_version, e.new_state, e.payload_json, "
            "o.mfe_pct, o.mae_pct, o.close_return_pct "
            "FROM v2_decision_events e LEFT JOIN v2_outcomes o "
            "ON o.decision_event_id=e.event_id "
            "WHERE e.event_type IN "
            "('CANDIDATE_ENTERED','CANDIDATE_UPDATED','BUY_CONFIRMED') "
            f"AND e.new_state IN ({placeholders}) "
            "AND substr(e.exchange_time,1,10)=? "
            "ORDER BY e.exchange_time, e.id",
            (*states, selected_date),
        )
        return self._collapse_candidates(rows)

    async def _names(self, codes: list[str]) -> dict[str, str]:
        placeholders = ",".join("?" for _ in codes)
        rows = await self._query(
            f"SELECT code, COALESCE(name, '') FROM stocks WHERE code IN ({placeholders})",
            tuple(codes),
        )
        return {str(row[0]): str(row[1] or "") for row in rows}

    async def _klines(self, codes: list[str], start_date: str) -> dict[str, dict[str, tuple]]:
        placeholders = ",".join("?" for _ in codes)
        rows = await self._query(
            "SELECT stock_code, substr(time_key,1,10), close_price, high_price, low_price "
            f"FROM kline_data WHERE stock_code IN ({placeholders}) "
            "AND substr(time_key,1,10)>=? ORDER BY stock_code, time_key LIMIT 20000",
            (*codes, start_date),
        )
        result: dict[str, dict[str, tuple]] = defaultdict(dict)
        for row in rows:
            if row[2] is None:
                continue
            result[str(row[0])][str(row[1])] = (
                float(row[2]),
                float(row[3]) if row[3] is not None else float(row[2]),
                float(row[4]) if row[4] is not None else float(row[2]),
            )
        return dict(result)

    async def _intraday(self, codes: list[str], trade_date: str) -> dict[str, list[tuple]]:
        placeholders = ",".join("?" for _ in codes)
        rows = await self._query(
            "SELECT stock_code, minute, price, high, low FROM ticker_minute "
            f"WHERE stock_code IN ({placeholders}) AND trade_date=? "
            "ORDER BY stock_code, minute",
            (*codes, trade_date),
        )
        result: dict[str, list[tuple]] = defaultdict(list)
        for row in rows:
            if row[2] is None:
                continue
            price = float(row[2])
            result[str(row[0])].append((
                str(row[1]),
                price,
                float(row[3]) if row[3] is not None else price,
                float(row[4]) if row[4] is not None else price,
            ))
        return dict(result)

    async def _query(self, sql: str, params: tuple = ()) -> list:
        return await asyncio.to_thread(self._db.execute_query, sql, params)

    @staticmethod
    def _collapse_delivered(rows: list[tuple]) -> list[dict]:
        collapsed: dict[tuple[str, str, str], dict] = {}
        for row in rows:
            intent_type = str(row[6])
            leg_json = row[9] if intent_type == "SELL" else row[8]
            try:
                leg = json.loads(leg_json or "{}")
                stock_code = str(leg.get("stock_code") or row[2]).strip().upper()
                signal_price = float(leg.get("reference_price") or 0)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not stock_code or signal_price <= 0:
                continue
            signal_date = str(row[3])[:10]
            key = (signal_date, stock_code, intent_type)
            if key in collapsed:
                collapsed[key]["alert_count"] += 1
                collapsed[key]["last_alert_time"] = row[3]
                continue
            collapsed[key] = {
                "event_id": row[0],
                "event_type": row[1],
                "stock_code": stock_code,
                "signal_time": row[3],
                "last_alert_time": row[3],
                "signal_date": signal_date,
                "signal_price": signal_price,
                "reason_code": row[4],
                "strategy_version": row[5],
                "action": intent_type,
                "direction": "SELL" if intent_type == "SELL" else "BUY",
                "risk_result": row[7],
                "entry_stage": "CONFIRMED",
                "max_stage": "CONFIRMED",
                "delivered_at": row[10],
                "intraday_mfe_pct": AlertPerformanceReader._number(row[11]),
                "intraday_mae_pct": AlertPerformanceReader._number(row[12]),
                "outcome_close_return_pct": AlertPerformanceReader._number(row[13]),
                "alert_count": 1,
            }
        return list(collapsed.values())

    @staticmethod
    def _collapse_candidates(rows: list[tuple]) -> list[dict]:
        collapsed: dict[tuple[str, str], dict] = {}
        for row in rows:
            try:
                payload = json.loads(row[7] or "{}")
                feature = payload.get("feature_snapshot") or {}
                quote = feature.get("quote") or {}
                signal_price = float(quote.get("last_price") or 0)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            stock_code = str(row[2]).strip().upper()
            stage = str(row[6] or "SETUP")
            if not stock_code or signal_price <= 0 or stage not in STAGE_RANK:
                continue
            signal_date = str(row[3])[:10]
            key = (signal_date, stock_code)
            if key in collapsed:
                item = collapsed[key]
                item["alert_count"] += 1
                item["last_alert_time"] = row[3]
                if STAGE_RANK[stage] > STAGE_RANK[item["max_stage"]]:
                    item["max_stage"] = stage
                item["intraday_mfe_pct"] = AlertPerformanceReader._max_number(
                    item["intraday_mfe_pct"], row[8]
                )
                item["intraday_mae_pct"] = AlertPerformanceReader._min_number(
                    item["intraday_mae_pct"], row[9]
                )
                if row[10] is not None:
                    item["outcome_close_return_pct"] = float(row[10])
                continue
            collapsed[key] = {
                "event_id": row[0],
                "event_type": row[1],
                "stock_code": stock_code,
                "signal_time": row[3],
                "last_alert_time": row[3],
                "signal_date": signal_date,
                "signal_price": signal_price,
                "reason_code": row[4],
                "strategy_version": row[5],
                "action": "CANDIDATE",
                "direction": "BUY",
                "risk_result": "NOT_REQUIRED",
                "entry_stage": stage,
                "max_stage": stage,
                "delivered_at": None,
                "intraday_mfe_pct": AlertPerformanceReader._number(row[8]),
                "intraday_mae_pct": AlertPerformanceReader._number(row[9]),
                "outcome_close_return_pct": AlertPerformanceReader._number(row[10]),
                "alert_count": 1,
            }
        return list(collapsed.values())

    @classmethod
    def _evaluate(
        cls,
        alert: dict,
        names: dict,
        klines: dict,
        intraday: dict,
    ) -> dict:
        basis = alert["signal_price"]
        direction = alert["direction"]
        stock_days = klines.get(alert["stock_code"], {})
        same_day = stock_days.get(alert["signal_date"])
        later_days = [day for day in sorted(stock_days) if day > alert["signal_date"]]
        signal_minute = cls._signal_minute(alert["signal_time"])
        stock_minute_rows = intraday.get(alert["stock_code"], [])
        minute_rows = [row for row in stock_minute_rows if row[0] >= signal_minute]
        if not minute_rows and stock_minute_rows:
            # No later trade means the latest traded price remains the market close.
            minute_rows = [stock_minute_rows[-1]]

        outcome_close = alert["outcome_close_return_pct"]
        same_close = None
        same_day_source = None
        price_scale = 1.0
        if outcome_close is not None:
            same_close = cls._directional_value(
                outcome_close, direction
            )
            same_day_source = "OUTCOME"
            if same_day and same_day[0] > 0:
                actual_close = basis * (1.0 + outcome_close / 100.0)
                price_scale = actual_close / same_day[0]
        elif same_day:
            same_close = cls._directional_return(same_day[0], basis, direction)
            same_day_source = "DAILY_KLINE"
        elif minute_rows:
            same_close = cls._directional_return(
                minute_rows[-1][1], basis, direction
            )
            same_day_source = "TICKER_MINUTE"
        same_best = cls._directional_value(alert["intraday_mfe_pct"], direction)
        same_worst = cls._directional_value(alert["intraday_mae_pct"], direction)
        if direction == "SELL":
            same_best, same_worst = (
                cls._directional_value(alert["intraday_mae_pct"], direction),
                cls._directional_value(alert["intraday_mfe_pct"], direction),
            )
        if minute_rows:
            if same_best is None:
                favorable_price = (
                    min(row[3] for row in minute_rows)
                    if direction == "SELL"
                    else max(row[2] for row in minute_rows)
                )
                same_best = cls._directional_return(
                    favorable_price, basis, direction
                )
            if same_worst is None:
                adverse_price = (
                    max(row[2] for row in minute_rows)
                    if direction == "SELL"
                    else min(row[3] for row in minute_rows)
                )
                same_worst = cls._directional_return(
                    adverse_price, basis, direction
                )

        periods = {
            str(horizon): cls._period(
                horizon, later_days, stock_days, basis, direction, price_scale
            )
            for horizon in HORIZONS
        }
        return {
            **alert,
            "stock_name": names.get(alert["stock_code"], ""),
            "same_day": {
                "status": "READY" if same_close is not None else "OBSERVING",
                "trading_day": alert["signal_date"],
                "close_return_pct": same_close,
                "max_return_pct": same_best,
                "max_drawdown_pct": same_worst,
                "source": same_day_source,
            },
            "periods": periods,
            "completed_horizon": max(
                (horizon for horizon in HORIZONS if periods[str(horizon)]["status"] == "READY"),
                default=0,
            ),
        }

    @classmethod
    def _period(
        cls,
        horizon: int,
        later_days: list[str],
        stock_days: dict[str, tuple],
        basis: float,
        direction: str,
        price_scale: float,
    ) -> dict:
        if len(later_days) < horizon:
            return {
                "status": "PENDING",
                "trading_day": None,
                "close_return_pct": None,
                "max_return_pct": None,
                "max_drawdown_pct": None,
            }
        window = [stock_days[day] for day in later_days[:horizon]]
        close_price = window[-1][0] * price_scale
        if direction == "SELL":
            favorable_price = min(row[2] for row in window) * price_scale
            adverse_price = max(row[1] for row in window) * price_scale
        else:
            favorable_price = max(row[1] for row in window) * price_scale
            adverse_price = min(row[2] for row in window) * price_scale
        return {
            "status": "READY",
            "trading_day": later_days[horizon - 1],
            "close_return_pct": cls._directional_return(close_price, basis, direction),
            "max_return_pct": cls._directional_return(favorable_price, basis, direction),
            "max_drawdown_pct": cls._directional_return(adverse_price, basis, direction),
        }

    @staticmethod
    def _summary(items: list[dict]) -> dict:
        periods = {}
        for horizon in HORIZONS:
            ready = [
                item["periods"][str(horizon)]["close_return_pct"]
                for item in items
                if item["periods"][str(horizon)]["status"] == "READY"
            ]
            periods[str(horizon)] = {
                "completed_count": len(ready),
                "win_count": sum(value > 0 for value in ready),
                "win_ratio": round(sum(value > 0 for value in ready) / len(ready), 4)
                if ready else None,
                "mean_return_pct": round(sum(ready) / len(ready), 4) if ready else None,
            }
        return {"alert_count": len(items), "periods": periods}

    @staticmethod
    def _directional_return(price: float, basis: float, direction: str) -> float:
        raw = (float(price) / basis - 1.0) * 100.0
        return AlertPerformanceReader._directional_value(raw, direction)

    @staticmethod
    def _directional_value(value: float | None, direction: str) -> float | None:
        if value is None:
            return None
        return round(-value if direction == "SELL" else value, 4)

    @staticmethod
    def _number(value) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _signal_minute(value: str) -> str:
        text = str(value or "")
        time_part = text.split("T", 1)[-1] if "T" in text else text.split(" ", 1)[-1]
        return time_part[:5] if len(time_part) >= 5 else "00:00"

    @staticmethod
    def _max_number(current: float | None, candidate) -> float | None:
        value = AlertPerformanceReader._number(candidate)
        if value is None:
            return current
        return value if current is None else max(current, value)

    @staticmethod
    def _min_number(current: float | None, candidate) -> float | None:
        value = AlertPerformanceReader._number(candidate)
        if value is None:
            return current
        return value if current is None else min(current, value)

    @staticmethod
    def _validated_date(value: str | None) -> str:
        if value is None:
            return date.today().isoformat()
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError as error:
            raise ValueError("交易日期必须是 YYYY-MM-DD") from error

    @staticmethod
    def _empty(trade_date: str, scope: str) -> dict:
        return {
            "trade_date": trade_date,
            "scope": scope,
            "items": [],
            "count": 0,
            "available_kline_through": None,
            "intraday_coverage_count": 0,
            "summary": {
                "alert_count": 0,
                "periods": {
                    str(horizon): {
                        "completed_count": 0,
                        "win_count": 0,
                        "win_ratio": None,
                        "mean_return_pct": None,
                    }
                    for horizon in HORIZONS
                },
            },
        }
