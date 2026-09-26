"""Create and cancel bookings. Status changes go through the state machine."""

import logging
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

logger = logging.getLogger(__name__)

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
            centre = DiagnosticCentre.objects.select_for_update().filter(pk=centre_id).first()
            if centre is None:
                raise Http404()
            test = DiagnosticTest.objects.select_for_update().filter(pk=test_id).first()
            if test is None:
                raise Http404()
            if not centre.is_active:
                raise CentreInactive()
            if not test.is_active:
                raise TestInactive()
            offering = (
                CentreTest.objects.select_for_update().filter(centre=centre, test=test).first()
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
        raise DuplicateBooking() from exc
    logger.info(
        "booking_created",
        extra={
            "booking_id": str(booking.id),
            "user_id": str(user.id),
            "amount": str(booking.amount),
        },
    )
    return booking


def cancel_booking(*, user, booking_id, reason: str = "") -> Booking:
    """Cancel the caller's own booking.

    Pending bookings can be cancelled until they reach a terminal status.
    A confirmed booking can be cancelled only when the appointment is more
    than two hours away. That cancellation is where a refund would be triggered.
    """
    with transaction.atomic():
        booking = get_object_or_404(
            Booking.objects.select_for_update().filter(user=user).select_related("centre", "test"),
            pk=booking_id,
        )
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
        extra={
            "booking_id": str(booking.id),
            "user_id": str(user.id),
            "refund_required": refund_required,
        },
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
