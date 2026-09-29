"""Create and cancel bookings. Status changes go through the state machine."""

from datetime import time, timedelta
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.bookings.exceptions import (
    CancellationWindowClosed,
    CentreInactive,
    DuplicateBooking,
    InvalidInput,
    TestInactive,
    TestNotOfferedAtCentre,
    TestUnavailable,
)
from apps.bookings.models import Booking
from apps.bookings.state_machine import CANCELLED, CONFIRMED, transition
from apps.catalog.models import CentreTest, DiagnosticCentre, DiagnosticTest
from apps.core.logging import get_logger

logger = get_logger()

IST = ZoneInfo("Asia/Kolkata")
OPENS_AT = time(7, 0)
CLOSES_AT = time(20, 0)
MAX_ADVANCE = timedelta(days=90)
MIN_CANCEL_NOTICE = timedelta(hours=2)


def create_booking(*, user, centre_id, test_id, appointment_at) -> Booking:
    """Reserve a test. The amount is copied from the centre's current price.

    The client cannot choose the amount. A later price change does not rewrite
    this booking. Active duplicates are rejected by the partial unique index.
    """
    try:
        with transaction.atomic():
            centre = DiagnosticCentre.objects.filter(pk=centre_id).first()
            if centre is None:
                raise Http404()
            test = DiagnosticTest.objects.filter(pk=test_id).first()
            if test is None:
                raise Http404()
            if not centre.is_active:
                raise CentreInactive()
            if not test.is_active:
                raise TestInactive()
            # Shared lock keeps the price stable for this insert without
            # serialising every booking of the same test across centres.
            offering = (
                CentreTest.objects.select_for_update(of=("self",))
                .filter(centre=centre, test=test)
                .first()
            )
            if offering is None:
                raise TestNotOfferedAtCentre()
            if not offering.is_available:
                raise TestUnavailable()
            _validate_appointment(appointment_at)
            booking = Booking(
                user=user,
                centre=centre,
                test=test,
                appointment_at=appointment_at,
                amount=offering.price,
            )
            booking.save()
    except IntegrityError as exc:
        constraint = ""
        cause = getattr(exc, "__cause__", None)
        diag = getattr(cause, "diag", None)
        if diag is not None:
            constraint = getattr(diag, "constraint_name", "") or ""
        if "unique_active_booking" in constraint or "unique_active_booking" in str(exc):
            raise DuplicateBooking() from exc
        raise
    logger.info(
        "booking_created",
        booking_id=str(booking.id),
        user_id=str(user.id),
        amount=str(booking.amount),
    )
    return booking


def cancel_booking(*, user, booking_id, reason: str = "") -> Booking:
    """Cancel a booking the caller can see.

    Owners cancel their own rows. Staff may cancel any booking. Pending bookings
    can be cancelled until they reach a terminal status. A confirmed booking can
    be cancelled only when the appointment is more than two hours away.
    """
    with transaction.atomic():
        queryset = Booking.objects.select_for_update().select_related("centre", "test")
        if not user.is_staff:
            queryset = queryset.filter(user=user)
        booking = get_object_or_404(queryset, pk=booking_id)
        refund_required = False
        if booking.status == CONFIRMED:
            remaining = booking.appointment_at - timezone.now()
            if remaining <= MIN_CANCEL_NOTICE:
                raise CancellationWindowClosed()
            refund_required = True
        transition(booking, CANCELLED)
        booking.cancelled_at = timezone.now()
        booking.cancellation_reason = (reason or "").strip()
        booking.save(update_fields=["status", "cancelled_at", "cancellation_reason", "updated_at"])
    logger.info(
        "booking_cancelled",
        booking_id=str(booking.id),
        user_id=str(user.id),
        refund_required=refund_required,
    )
    return booking


def _validate_appointment(appointment_at) -> None:
    now = timezone.now()
    if appointment_at <= now:
        raise InvalidInput({"appointment_at": ["Must be in the future."]})
    if appointment_at > now + MAX_ADVANCE:
        raise InvalidInput({"appointment_at": ["Must be within 90 days."]})
    local_time = appointment_at.astimezone(IST).time()
    if not (OPENS_AT <= local_time <= CLOSES_AT):
        raise InvalidInput({"appointment_at": ["Must be between 07:00 and 20:00 IST."]})
