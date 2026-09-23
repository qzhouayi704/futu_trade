"""Versioned JSON boundary for paper replay and durable Decimal account state."""

from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
import json

from .models import (
    EntrySetup, PaperAccount, PaperBook, PaperFill, PaperOrder, PaperPolicy, TradePlan,
)


def _default(value: object) -> object:
    if isinstance(value, (Decimal, datetime)):
        return value.isoformat() if isinstance(value, datetime) else str(value)
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f"unsupported paper JSON value: {type(value).__name__}")


def encode(value: object) -> str:
    return json.dumps(value, default=_default, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def policy_from_payload(payload: dict) -> PaperPolicy:
    values = dict(payload)
    for name in ("initial_cash", "fee_rate", "minimum_fee", "risk_fraction",
                 "portfolio_risk_fraction", "position_fraction", "cash_reserve_fraction",
                 "participation_fraction"):
        if name in values:
            values[name] = Decimal(str(values[name]))
    return PaperPolicy(**values)


def setup_from_payload(payload: dict) -> EntrySetup:
    values = dict(payload)
    for name in ("entry_min", "entry_limit", "stop_price", "take_profit", "position_fraction"):
        if values.get(name) is not None:
            values[name] = Decimal(str(values[name]))
    for name in ("created_at", "valid_until", "exit_at"):
        values[name] = datetime.fromisoformat(values[name])
    return EntrySetup(**values)


def book_from_payload(payload: dict) -> PaperBook:
    values = dict(payload)
    for name in ("bid", "ask"):
        values[name] = Decimal(str(values[name]))
    for name in ("exchange_time", "received_at"):
        values[name] = datetime.fromisoformat(values[name])
    return PaperBook(**values)


def decode_account(raw: str) -> PaperAccount:
    payload = json.loads(raw)
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported paper account schema")
    values = payload["account"]
    orders = []
    for item in values["orders"]:
        plan_values = dict(item["plan"])
        plan_values["setup"] = setup_from_payload(plan_values["setup"])
        plan_values["approved_at"] = datetime.fromisoformat(plan_values["approved_at"])
        plan_values["initial_risk"] = Decimal(plan_values["initial_risk"])
        order_values = {**item, "plan": TradePlan(**plan_values)}
        for name in ("buy_notional", "sell_notional", "buy_fee", "sell_fee"):
            order_values[name] = Decimal(order_values[name])
        if order_values.get("exit_triggered_at"):
            order_values["exit_triggered_at"] = datetime.fromisoformat(order_values["exit_triggered_at"])
        orders.append(PaperOrder(**order_values))
    fills = []
    for item in values["fills"]:
        fills.append(PaperFill(**{
            **item, "price": Decimal(item["price"]), "fee": Decimal(item["fee"]),
            "exchange_time": datetime.fromisoformat(item["exchange_time"]),
        }))
    return PaperAccount(
        account_id=values["account_id"], policy=policy_from_payload(values["policy"]),
        cash=Decimal(values["cash"]), orders=orders, fills=fills,
        as_of=datetime.fromisoformat(values["as_of"]) if values["as_of"] else None,
        marks={key: Decimal(value) for key, value in values["marks"].items()},
        book_times={key: datetime.fromisoformat(value) for key, value in values["book_times"].items()},
    )


def encode_account(account: PaperAccount) -> str:
    return encode({"schema_version": 1, "account": account})
