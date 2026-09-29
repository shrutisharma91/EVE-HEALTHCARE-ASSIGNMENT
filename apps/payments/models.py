import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.bookings.models import Booking
from apps.core.models import TimeStampedModel, UUIDModel


class PaymentStatus(models.TextChoices):
    INITIATED = "INITIATED", "Initiated"
    SUCCESS = "SUCCESS", "Success"
    FAILED = "FAILED", "Failed"


class Payment(UUIDModel, TimeStampedModel):
    """One attempt to pay a booking.

    A PENDING booking may have several INITIATED/FAILED attempts (for example
    via simulate_outcome PENDING). At most one SUCCESS is allowed. Once the
    booking itself is FAILED or CANCELLED it is terminal — the user creates a
    new booking to try again.
    """

    booking = models.ForeignKey(Booking, on_delete=models.PROTECT, related_name="payments")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payments",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="INR")
    status = models.CharField(
        max_length=16,
        choices=PaymentStatus.choices,
        default=PaymentStatus.INITIATED,
        db_index=True,
    )
    provider_reference = models.CharField(max_length=64, unique=True)
    idempotency_key = models.CharField(max_length=255)
    failure_reason = models.CharField(max_length=255, null=True, blank=True)
    refund_required = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            "True when the gateway captured money that the booking can no longer "
            "use (late success after cancel/fail, or a second successful charge)."
        ),
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="payment_amount_positive"),
            models.UniqueConstraint(
                fields=["user", "idempotency_key"],
                name="unique_user_idempotency_key",
            ),
            # At most one SUCCESS that confirmed the booking. Extra gateway
            # successes that need a refund are SUCCESS + refund_required=True.
            models.UniqueConstraint(
                fields=["booking"],
                condition=Q(status=PaymentStatus.SUCCESS, refund_required=False),
                name="unique_success_payment_per_booking",
            ),
        ]

    def __str__(self) -> str:
        return self.provider_reference

    @staticmethod
    def new_provider_reference() -> str:
        return f"sim_pay_{uuid.uuid4().hex}"


class ProcessingStatus(models.TextChoices):
    RECEIVED = "RECEIVED", "Received"
    PROCESSED = "PROCESSED", "Processed"
    IGNORED = "IGNORED", "Ignored"
    FAILED = "FAILED", "Failed"


class WebhookEvent(TimeStampedModel):
    """Idempotency ledger. The provider's event_id is unique, so duplicates are a no-op."""

    event_id = models.CharField(max_length=255, unique=True)
    event_type = models.CharField(max_length=64)
    payload = models.JSONField()
    payment = models.ForeignKey(
        Payment,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="webhook_events",
    )
    processing_status = models.CharField(
        max_length=16,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.RECEIVED,
        db_index=True,
    )
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self) -> str:
        return self.event_id
