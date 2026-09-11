from types import SimpleNamespace
from unittest.mock import patch

from simple_trade.services.market_data.ticker_analysis.ticker_service import (
    TickerRecord,
    TickerService,
)


def test_on_demand_ticker_persistence_uses_nine_field_contract():
    db_manager = SimpleNamespace(conn_manager=object())
    service = TickerService(futu_client=None, db_manager=db_manager)
    records = [TickerRecord(
        time="2026-09-10 10:24:01.123",
        price=80.2,
        volume=1_000,
        turnover=0,
        direction="BUY",
    )]

    with patch(
        "simple_trade.database.queries.ticker_queries."
        "TickerQueries.insert_ticker_batch"
    ) as insert_batch:
        service._persist_ticker_data("HK.06106", records)

    rows = insert_batch.call_args.args[0]
    assert len(rows) == 1
    assert len(rows[0]) == 9
    assert rows[0][0] == "HK.06106"
    assert rows[0][3] == 80_200
    assert rows[0][7] is None
    assert rows[0][8] == "2026-09-10 10:24:01.123"
