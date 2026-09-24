"""Atomic input, result and account updates for a local paper experiment."""

from dataclasses import fields, replace
from collections.abc import Callable
from datetime import datetime
import hashlib
import json

from ...domain.capture import CapturedBook
from ...domain.decisions import DecisionEvent
from ...domain.enums import EventType
from ...domain.events import FeatureSnapshotEvent
from ...domain.paper_session import PaperExperiment
from ...domain.planning.codec import encode
from ...domain.planning.models import PaperAccount
from ...domain.serialization import to_primitive
from ...ports.paper_account import PaperAccountStore
from ..book_capture.paper_input import to_paper_book
from ..planning.paper_engine import PaperEngine
from .factory import research_plan
from .positions import PaperPositionFollower


class PaperSessionService:
    def __init__(self, store: PaperAccountStore, experiment: PaperExperiment) -> None:
        self.store = store
        self.experiment = experiment
        self._positions = PaperPositionFollower(experiment)
        account = store.read()
        if account.policy != experiment.policy:
            raise ValueError("paper account policy does not match experiment")
        PaperEngine.assert_invariants(account)

    def signal(self, event: DecisionEvent, when: datetime) -> str:
        source = {field.name: to_primitive(getattr(event, field.name)) for field in fields(event)}

        def operate(account: PaperAccount) -> dict[str, object]:
            PaperEngine.advance(account, when)
            if event.event_type in {EventType.BUY_INVALIDATED, EventType.CANDIDATE_INVALIDATED}:
                if (event.strategy_version != self.experiment.strategy_version
                        or not event.exchange_time <= event.received_time <= when):
                    return {"reason": "INVALIDATION_EVIDENCE_INVALID"}
                cancelled = 0
                for order in account.orders:
                    if (order.plan.setup.stock_code == event.stock_code and order.entry_remaining
                            and order.plan.approved_at <= event.received_time):
                        PaperEngine.cancel_entry(account, order.plan.plan_id, when)
                        cancelled += 1
                return {"reason": "SIGNAL_INVALIDATED_ENTRY_CANCELLED" if cancelled else "NO_ENTRY_TO_CANCEL"}
            assessment = research_plan(event, self.experiment, when)
            if assessment.setup is None:
                return {"reason": assessment.reason}
            plan_id = assessment.setup.plan_id(account.account_id)
            if any(order.plan.plan_id == plan_id for order in account.orders):
                return {"reason": "EXPERIMENT_STOCK_DAY_ALREADY_PLANNED", "plan_id": plan_id}
            result = PaperEngine.submit(account, assessment.setup, when)
            return {"reason": result.reason, "assessment": result}

        return self._apply(f"paper-signal:{event.event_id}", source, when, operate)

    def feature(self, event: FeatureSnapshotEvent, when: datetime) -> str:
        def operate(account: PaperAccount) -> dict[str, object]:
            PaperEngine.advance(account, when)
            result = self._positions.evaluate(account, event, when)
            return {"reason": result.reason, "decisions": result.decisions}

        return self._apply(f"paper-position:{event.event_id}", to_primitive(event), when, operate)

    def book(self, book: CapturedBook, when: datetime) -> str:
        def operate(account: PaperAccount) -> dict[str, object]:
            PaperEngine.advance(account, when)
            # Delayed archive delivery is not retroactively available to the account.
            if not 0 <= (when - book.received_at).total_seconds() <= account.policy.max_book_age_seconds:
                return {"reason": "CAPTURE_DELIVERY_STALE_OR_FUTURE"}
            interval = self.experiment.interval_at(when)
            if interval is None or any(
                stamp is None or not interval.opens_at <= stamp < interval.closes_at
                for stamp in (book.bid_time, book.ask_time)
            ):
                return {"reason": "TRADING_INTERVAL_UNAVAILABLE_OR_CLOSED"}
            try:
                paper_book = to_paper_book(book, allow_sampled_server_time=True, market_open=True)
            except ValueError:
                return {"reason": "CAPTURE_NOT_EXECUTABLE"}
            paper_book = replace(paper_book, received_at=when)
            return {"reason": PaperEngine.on_book(account, paper_book)}

        return self._apply(f"paper-book:{book.event_id}", book, when, operate)

    def clock(self, when: datetime) -> str:
        return self._apply(f"paper-clock:{when.isoformat()}", ("clock", when), when,
                           lambda account: self._advance(account, when))

    @staticmethod
    def _advance(account: PaperAccount, when: datetime) -> dict[str, object]:
        PaperEngine.advance(account, when)
        return {"reason": "CLOCK_ADVANCED"}

    def _apply(self, event_id: str, source: object, when: datetime,
               operation: Callable[[PaperAccount], dict[str, object]]) -> str:
        fingerprint = hashlib.sha256(encode(source).encode("utf-8")).hexdigest()

        def checked(account: PaperAccount) -> str:
            result = operation(account)
            PaperEngine.assert_invariants(account)
            return encode({"input": source, "processed_at": when, "result": result})

        return json.loads(self.store.apply(event_id, fingerprint, checked))["result"]["reason"]
