"""Charge a booking and apply the result. The webhook uses the same apply function."""

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.bookings.models import Booking
from apps.bookings.state_machine import CANCELLED, CONFIRMED, FAILED, PENDING, transition
from apps.core.logging import get_logger
from apps.payments.exceptions import (
    BookingAlreadyPaid,
    BookingExpired,
    BookingNotPayable,
    IdempotencyKeyRequired,
    IdempotencyKeyReused,
)
from apps.payments.models import Payment, PaymentStatus
from apps.payments.simulator import PaymentSimulator

logger = get_logger()


def create_payment(*, user, booking_id, idempotency_key, simulate_outcome=None, simulator=None):
    """Take payment for the caller's pending booking.

    The same user and Idempotency-Key returns the original payment. The amount
    always comes from the booking, never from the client. A failed simulation
    is a normal business result: the payment row is FAILED and so is the booking.
    simulate_outcome PENDING leaves the payment INITIATED and the booking PENDING.
    The webhook is what moves that attempt to SUCCESS or FAILED.
    """
    key = (idempotency_key or "").strip()
    if not key:
        raise IdempotencyKeyRequired()

    replay = _matching_payment(user, key, booking_id, lock=False)
    if replay is not None:
        return replay, False

    if simulator is None:
        simulator = PaymentSimulator(forced_outcome=simulate_outcome)

    try:
        with transaction.atomic():
            replay = _matching_payment(user, key, booking_id, lock=True)
            if replay is not None:
                return replay, False
            booking = get_object_or_404(
                Booking.objects.select_for_update().filter(user=user),
                pk=booking_id,
            )
            _assert_payable(booking)
            payment = Payment.objects.create(
                booking=booking,
                user=user,
                amount=booking.amount,
                currency="INR",
                provider_reference=Payment.new_provider_reference(),
                idempotency_key=key,
            )
            result = simulator.process(payment)
            if result.status != "PENDING":
                apply_payment_result(
                    payment,
                    result.status,
                    failure_reason=result.failure_reason,
                )
    except IntegrityError:
        replay = _matching_payment(user, key, booking_id, lock=False)
        if replay is not None:
            return replay, False
        raise
    payment = Payment.objects.select_related("booking").get(pk=payment.pk)
    return payment, True


def apply_payment_result(payment, status, *, failure_reason=None) -> Payment:
    """Move a payment to SUCCESS or FAILED and update the booking.

    Idempotent and order-safe:
    - already in the target status: do nothing
    - SUCCESS is final, so a later failure is ignored
    - a success for a cancelled booking does not resurrect it; a refund is logged

    Callers should already be inside transaction.atomic(). This opens a savepoint
    and locks the booking before the payment.
    """
    if status not in (PaymentStatus.SUCCESS, PaymentStatus.FAILED):
        raise ValueError("Payment results must be SUCCESS or FAILED.")

    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=payment.booking_id)
        payment = Payment.objects.select_for_update().get(pk=payment.pk)

        if payment.status == status:
            payment.booking = booking
            return payment

        if payment.status == PaymentStatus.SUCCESS and status == PaymentStatus.FAILED:
            logger.info(
                "payment_processed",
                payment_id=str(payment.id),
                booking_id=str(booking.id),
                ignored=True,
                reason="success_is_final",
            )
            payment.booking = booking
            return payment

        if booking.status == CANCELLED and status == PaymentStatus.SUCCESS:
            payment.status = PaymentStatus.SUCCESS
            payment.failure_reason = None
            payment.save(update_fields=["status", "failure_reason", "updated_at"])
            logger.info(
                "payment_processed",
                payment_id=str(payment.id),
                booking_id=str(booking.id),
                status=payment.status,
                refund_required=True,
            )
            payment.booking = booking
            return payment

        if status == PaymentStatus.SUCCESS:
            transition(booking, CONFIRMED)
            payment.status = PaymentStatus.SUCCESS
            payment.failure_reason = None
        else:
            transition(booking, FAILED)
            payment.status = PaymentStatus.FAILED
            payment.failure_reason = failure_reason or "insufficient_funds"

        booking.save(update_fields=["status", "updated_at"])
        payment.save(update_fields=["status", "failure_reason", "updated_at"])

    logger.info(
        "payment_processed",
        payment_id=str(payment.id),
        booking_id=str(booking.id),
        status=payment.status,
        refund_required=False,
    )
    payment.booking = booking
    return payment


def _assert_payable(booking: Booking) -> None:
    if booking.status == CONFIRMED:
        raise BookingAlreadyPaid()
    if booking.status != PENDING:
        raise BookingNotPayable()
    if booking.appointment_at <= timezone.now():
        raise BookingExpired()


def _matching_payment(user, key, booking_id, *, lock: bool):
    queryset = Payment.objects.select_related("booking").filter(user=user, idempotency_key=key)
    if lock:
        queryset = queryset.select_for_update()
    existing = queryset.first()
    if existing is None:
        return None
    if existing.booking_id != booking_id:
        raise IdempotencyKeyReused()
    return existing
