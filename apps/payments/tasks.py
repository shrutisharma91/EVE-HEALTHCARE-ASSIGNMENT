"""Background processing for payment webhooks. Domain errors are not retried."""

from decimal import Decimal

from django.db import OperationalError, transaction
from django.utils import timezone

from apps.bookings.models import Booking
from apps.core.logging import get_logger
from apps.payments.models import Payment, PaymentStatus, ProcessingStatus, WebhookEvent
from apps.payments.services import apply_payment_result
from celery import shared_task

logger = get_logger()

SUCCEEDED = "payment.succeeded"
FAILED_EVENT = "payment.failed"
KNOWN_EVENTS = {SUCCEEDED, FAILED_EVENT}


@shared_task(
    bind=True,
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    max_retries=5,
)
def process_webhook_event(self, event_id: str):
    """Apply one stored webhook. Database blips are retried; bad payloads are not."""
    try:
        handle_webhook_event(event_id)
    except OperationalError as exc:
        final = self.request.retries >= (self.max_retries or 0)
        record_webhook_attempt(event_id, exc, final=final)
        if final:
            return None
        raise
    return None


def handle_webhook_event(event_id: str) -> None:
    with transaction.atomic():
        event = WebhookEvent.objects.select_for_update().get(event_id=event_id)
        if event.processing_status in (ProcessingStatus.PROCESSED, ProcessingStatus.IGNORED):
            return

        data = event.payload.get("data") or {}
        reference = data.get("provider_reference")
        payment = Payment.objects.filter(provider_reference=reference).first()
        if payment is None:
            _fail(event, "Unknown provider_reference.")
            return

        booking = Booking.objects.select_for_update().get(pk=payment.booking_id)
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        if not _amount_matches(payment, data):
            logger.warning(
                "webhook_amount_mismatch",
                event_id=event.event_id,
                payment_id=str(payment.id),
                booking_id=str(booking.id),
            )
            event.payment = payment
            _fail(event, "Amount or currency does not match the payment.")
            return

        target = PaymentStatus.SUCCESS if event.event_type == SUCCEEDED else PaymentStatus.FAILED
        reason = None if target == PaymentStatus.SUCCESS else "insufficient_funds"
        apply_payment_result(payment, target, failure_reason=reason)
        event.processing_status = ProcessingStatus.PROCESSED
        event.payment = payment
        event.processed_at = timezone.now()
        event.last_error = ""
        event.save(
            update_fields=[
                "processing_status",
                "payment",
                "processed_at",
                "last_error",
                "updated_at",
            ]
        )
    logger.info(
        "webhook_processed",
        event_id=event_id,
        payment_id=str(payment.id),
    )


def record_webhook_attempt(event_id: str, exc: Exception, *, final: bool) -> None:
    with transaction.atomic():
        event = WebhookEvent.objects.select_for_update().get(event_id=event_id)
        event.attempts += 1
        event.last_error = str(exc)[:2000]
        if final:
            event.processing_status = ProcessingStatus.FAILED
            event.processed_at = timezone.now()
        event.save(
            update_fields=[
                "attempts",
                "last_error",
                "processing_status",
                "processed_at",
                "updated_at",
            ]
        )


def _amount_matches(payment: Payment, data: dict) -> bool:
    try:
        amount = Decimal(str(data.get("amount")))
    except Exception:
        return False
    return amount == payment.amount and data.get("currency") == payment.currency


def _fail(event: WebhookEvent, message: str) -> None:
    event.processing_status = ProcessingStatus.FAILED
    event.last_error = message
    event.processed_at = timezone.now()
    event.save(
        update_fields=["processing_status", "last_error", "processed_at", "payment", "updated_at"]
    )
