"""Stand-in for a payment gateway. Swap this class for a real provider later."""

import random
from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True)
class SimulatedResult:
    status: str
    failure_reason: str | None


class PaymentSimulator:
    """Decide SUCCESS, FAILED, or PENDING without calling out to a network.

    `process(payment)` is the whole interface. A Razorpay (or similar) gateway
    can replace this class without changing the booking flow. PENDING means the
    gateway has not settled yet: the payment stays INITIATED until a webhook.
    """

    def __init__(
        self,
        success_rate: float | None = None,
        rng: random.Random | None = None,
        forced_outcome: str | None = None,
    ):
        if success_rate is None:
            success_rate = settings.PAYMENT_SUCCESS_RATE
        self.success_rate = success_rate
        self.rng = rng or random.Random()
        self.forced_outcome = forced_outcome

    def process(self, payment) -> SimulatedResult:
        outcome = self.forced_outcome
        if outcome is None:
            outcome = "SUCCESS" if self.rng.random() < self.success_rate else "FAILED"
        if outcome == "PENDING":
            return SimulatedResult(status="PENDING", failure_reason=None)
        if outcome == "SUCCESS":
            return SimulatedResult(status="SUCCESS", failure_reason=None)
        return SimulatedResult(status="FAILED", failure_reason="insufficient_funds")
