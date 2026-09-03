"""Adapter from the V2 subscription port to the legacy subscription helper."""


class LegacyCandidateSubscriptionAdapter:
    def __init__(self, subscription_helper) -> None:
        self._subscription_helper = subscription_helper

    def subscribe_candidate(self, stock_code: str) -> bool:
        result = self._subscription_helper.subscribe_for_candidate_data(stock_code)
        return bool(result.get("success"))
