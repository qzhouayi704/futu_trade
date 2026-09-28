"""Read only the two FIRST sequences authorized after the 11:36 aggregate."""
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import gzip
import json
import sqlite3
import sys
import time


HK = timezone(timedelta(hours=8))
DAY = '2026-09-28'
CUTOFF = datetime(2026, 9, 28, 11, 36, 26, 826760, tzinfo=HK)
MAX_SEQUENCE_ROWS = 64
TERMINAL = {'EXPIRED', 'INVALIDATED', 'REJECTED', 'TRAIL_EXIT', 'WATCH_TRAIL_EXIT'}
STAGE_SQL = "json_extract(CASE WHEN json_valid(raw_detail) THEN raw_detail ELSE '{}' END,'$.inflow_stage')"


@dataclass(frozen=True)
class SequenceEvent:
    row_id: int
    code: str
    name: str | None
    emitted_at: str
    persisted_utc: str
    action: str | None
    stage: str | None
    sequence: int | None
    direction: str | None
    reason: str | None
    price: float | None
    first_price: float | None
    peak_price: float | None
    confirm_price: float | None
    pullback_pct: float | None
    intraday_change_pct: float | None
    window_net: float | None
    window_buy_ratio: float | None
    window_big_buy: float | None
    window_big_sell: float | None
    large_inflow: bool | None
    observe_only: bool | None
    plate_name: str | None
    risk_mode: str | None
    required_confirmations: int | None
    gate_reason: str | None
    market_breadth: float | None
    plate_breadth: float | None
    turnover_rank_percentile: float | None
    relative_strength_pct: float | None


@dataclass(frozen=True)
class Sequence:
    first_row_id: int
    code: str
    events: tuple[SequenceEvent, ...]
    terminal_observed: bool


@dataclass(frozen=True)
class EpisodeProbe:
    observed_at: str
    sequence_cutoff: str
    sequences: tuple[Sequence, ...]
    elapsed_seconds: float
    schema: int = 1
    kind: str = 'AUTHORIZED_TWO_FIRST_SEQUENCES'
    source: str = 'PRODUCTION_SQLITE_READ_ONLY'
    scope: str = 'TWO_FIRSTS_AT_20260928_113626_AND_THEIR_FIRST_TERMINAL_ONLY'
    read_only: bool = True
    truncated: bool = False
    performance_result: None = None


def event(row: tuple) -> SequenceEvent:
    identity, code, name, emitted, persisted, action, raw = row
    detail = json.loads(raw)
    if detail.get('stock_code') != code or detail.get('trade_date') != DAY:
        raise ValueError('source identity does not match authorized stock/date')
    # Explicit field whitelist; do not export the full raw payload or other data.
    return SequenceEvent(identity, code, name, emitted, persisted, action,
        detail.get('inflow_stage'), detail.get('inflow_sequence_no'), detail.get('direction'), detail.get('reason'),
        detail.get('last_price'), detail.get('inflow_first_price'), detail.get('inflow_peak_price'),
        detail.get('inflow_confirm_price'), detail.get('price_pullback_pct'), detail.get('intraday_change_pct'),
        detail.get('window_main_net'), detail.get('window_buy_ratio'), detail.get('window_big_buy'),
        detail.get('window_big_sell'), detail.get('is_large_inflow'), detail.get('legacy_observe_only'),
        detail.get('plate_name'), detail.get('inflow_risk_mode'), detail.get('required_confirmations'),
        detail.get('inflow_gate_reason'), detail.get('market_breadth'), detail.get('plate_breadth'),
        detail.get('turnover_rank_percentile'), detail.get('relative_strength_pct'))


def snapshot(connection: sqlite3.Connection, now: datetime) -> EpisodeProbe:
    if now.tzinfo is None or now.utcoffset() is None or now < CUTOFF:
        raise ValueError('aware observation time after authorized aggregate required')
    connection.execute('PRAGMA query_only=ON')
    started = time.monotonic()
    connection.set_progress_handler(lambda: time.monotonic()-started > 25, 10000)
    connection.execute('BEGIN')
    cutoff_local = CUTOFF.replace(tzinfo=None).isoformat()
    cutoff_utc = CUTOFF.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    try:
        firsts = connection.execute(
            'SELECT id,stock_code,timestamp FROM signal_pipeline '
            "WHERE source='capital_trend' AND stock_code LIKE 'HK.%' AND trade_date=? "
            f"AND {STAGE_SQL}='FIRST' AND timestamp<=? AND created_at<=? ORDER BY timestamp,id LIMIT 3",
            (DAY, cutoff_local, cutoff_utc),
        ).fetchall()
        if len(firsts) != 2 or len({r[1] for r in firsts}) != 2:
            raise ValueError('authorized two-FIRST snapshot no longer matches; no details exported')
        sequences = []
        for first_id, code, first_time in firsts:
            rows = connection.execute(
                'SELECT id,stock_code,stock_name,timestamp,created_at,final_action,raw_detail FROM signal_pipeline '
                "WHERE source='capital_trend' AND stock_code=? AND trade_date=? "
                f"AND COALESCE({STAGE_SQL},'')<>'' AND timestamp>=? AND timestamp<=? AND created_at<=? "
                'ORDER BY timestamp,id LIMIT ?',
                (code, DAY, first_time, cutoff_local, cutoff_utc, MAX_SEQUENCE_ROWS+1),
            ).fetchall()
            if len(rows) > MAX_SEQUENCE_ROWS:
                raise ValueError('sequence row limit exceeded')
            selected = []
            for row in rows:
                item = event(row)
                if not selected and item.row_id != first_id:
                    raise ValueError('ambiguous sequence start; no details exported')
                if selected and item.stage == 'FIRST':
                    break
                selected.append(item)
                if item.stage in TERMINAL:
                    break
            if not selected:
                raise ValueError('missing authorized FIRST')
            sequences.append(Sequence(first_id, code, tuple(selected), selected[-1].stage in TERMINAL))
    finally:
        connection.rollback()
    return EpisodeProbe(now.astimezone(HK).isoformat(), CUTOFF.isoformat(), tuple(sequences), time.monotonic()-started)


def main() -> None:
    connection = sqlite3.connect('file:/data/futu_trade_data/trade.db?mode=ro', uri=True, timeout=3)
    try:
        result = snapshot(connection, datetime.now(HK))
    finally:
        connection.close()
    raw = json.dumps(asdict(result), ensure_ascii=True, allow_nan=False).encode()
    if len(raw) > 128*1024:
        raise ValueError('sequence output bound exceeded')
    sys.stdout.buffer.write(gzip.compress(raw, mtime=0))


if __name__ == '__main__':
    main()
