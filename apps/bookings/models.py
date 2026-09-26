from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.catalog.models import DiagnosticCentre, DiagnosticTest
from apps.core.models import TimeStampedModel, UUIDModel


class BookingStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    CONFIRMED = "CONFIRMED", "Confirmed"
    FAILED = "FAILED", "Failed"
    CANCELLED = "CANCELLED", "Cancelled"


class Booking(UUIDModel, TimeStampedModel):
    """A reserved test. `amount` is the centre's price at the moment of booking."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="bookings"
    )
    centre = models.ForeignKey(DiagnosticCentre, on_delete=models.PROTECT, related_name="bookings")
    test = models.ForeignKey(DiagnosticTest, on_delete=models.PROTECT, related_name="bookings")
    appointment_at = models.DateTimeField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=16,
        choices=BookingStatus.choices,
        default=BookingStatus.PENDING,
        db_index=True,
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status"], name="booking_user_status_idx"),
            models.Index(fields=["centre", "appointment_at"], name="booking_centre_slot_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="booking_amount_positive"),
            models.UniqueConstraint(
                fields=["user", "centre", "test", "appointment_at"],
                condition=Q(status__in=[BookingStatus.PENDING, BookingStatus.CONFIRMED]),
                name="unique_active_booking",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.id} {self.status}"
