"""Read-only startup loader for recent daily bars used by V2 features."""

import asyncio
from datetime import datetime, time, timedelta, timezone
from typing import Protocol

from ..domain.enums import DataQuality
from ..domain.features import CapitalBaseline, DailyBar


class FeatureReferenceDatabasePort(Protocol):
    def execute_query(self, query: str, params: tuple | None = None) -> list: ...


class FeatureReferenceLoader:
    def __init__(self, db: FeatureReferenceDatabasePort, lookback: int = 30) -> None:
        if lookback < 20:
            raise ValueError("feature reference lookback must be at least 20")
        self._db = db
        self._lookback = lookback

    async def load_daily_bars(self) -> tuple[DailyBar, ...]:
        rows = await asyncio.to_thread(
            self._db.execute_query,
            "WITH universe AS ("
            "SELECT stock_code FROM daily_active_stocks "
            "WHERE check_date=(SELECT MAX(check_date) FROM daily_active_stocks) "
            "AND is_active=1 UNION "
            "SELECT code FROM stocks WHERE is_manual=1 OR stock_priority>0 OR heat_score>0"
            "), ranked AS ("
            "SELECT kline_data.stock_code AS stock_code, time_key, open_price, "
            "high_price, low_price, close_price, volume, turnover, "
            "ROW_NUMBER() OVER (PARTITION BY kline_data.stock_code "
            "ORDER BY time_key DESC) AS rn "
            "FROM kline_data JOIN universe ON universe.stock_code=kline_data.stock_code) "
            "SELECT stock_code, time_key, open_price, high_price, low_price, "
            "close_price, volume, turnover FROM ranked WHERE rn <= ? "
            "ORDER BY stock_code, time_key",
            (self._lookback,),
        )
        bars: list[DailyBar] = []
        for row in rows:
            try:
                code = str(row[0])
                bars.append(
                    DailyBar(
                        stock_code=code,
                        as_of=self._parse_bar_time(code, row[1]),
                        open_price=float(row[2] or 0.0),
                        high_price=float(row[3] or 0.0),
                        low_price=float(row[4] or 0.0),
                        close_price=float(row[5] or 0.0),
                        volume=int(row[6] or 0),
                        turnover=float(row[7] or 0.0),
                    )
                )
            except (TypeError, ValueError, OverflowError):
                continue
        return tuple(bars)

    async def load_capital_baselines(self) -> tuple[CapitalBaseline, ...]:
        rows = await asyncio.to_thread(
            self._db.execute_query,
            "SELECT stock_code, metric_key, p50, sample_count, computed_at "
            "FROM market_baselines WHERE metric_key IN "
            "('big_order_threshold', 'window_net_scale') "
            "ORDER BY stock_code, metric_key, computed_at DESC",
        )
        latest: dict[tuple[str, str], tuple[float, int]] = {}
        for row in rows:
            key = (str(row[0]).strip().upper(), str(row[1]))
            if key in latest:
                continue
            try:
                value = float(row[2] or 0.0)
                if value > 0:
                    latest[key] = (value, int(row[3] or 0))
            except (TypeError, ValueError, OverflowError):
                continue
        codes = {code for code, metric in latest if metric == "big_order_threshold"}
        baselines: list[CapitalBaseline] = []
        for code in sorted(codes):
            threshold, threshold_samples = latest[(code, "big_order_threshold")]
            scale_row = latest.get((code, "window_net_scale"))
            scale = scale_row[0] if scale_row is not None else threshold
            sample_count = min(
                threshold_samples,
                scale_row[1] if scale_row is not None else threshold_samples,
            )
            baselines.append(
                CapitalBaseline(
                    stock_code=code,
                    large_order_threshold=threshold,
                    flow_scale=max(scale, threshold),
                    quality=(
                        DataQuality.GOOD if sample_count >= 3 else DataQuality.DEGRADED
                    ),
                )
            )
        return tuple(baselines)

    @staticmethod
    def _parse_bar_time(stock_code: str, value: object) -> datetime:
        parsed = datetime.fromisoformat(str(value).replace("T", " ", 1))
        if parsed.time() == time.min:
            parsed = datetime.combine(parsed.date(), time(16, 0))
        if parsed.tzinfo is None:
            try:
                from zoneinfo import ZoneInfo

                tz = ZoneInfo(
                    "America/New_York" if stock_code.startswith("US.") else "Asia/Hong_Kong"
                )
            except Exception:
                tz = timezone(timedelta(hours=-5 if stock_code.startswith("US.") else 8))
            parsed = parsed.replace(tzinfo=tz)
        return parsed
