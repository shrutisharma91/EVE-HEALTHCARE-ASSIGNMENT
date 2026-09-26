"""The only place a booking's status is allowed to change."""

import logging

from apps.bookings.exceptions import InvalidStateTransition

logger = logging.getLogger(__name__)

PENDING = "PENDING"
CONFIRMED = "CONFIRMED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

ALLOWED_TRANSITIONS = {
    PENDING: {CONFIRMED, FAILED, CANCELLED},
    CONFIRMED: {CANCELLED},
    FAILED: set(),
    CANCELLED: set(),
}


def transition(booking, new_status: str):
    """Move a booking to new_status or raise InvalidStateTransition.

    Callers save the booking. This function does not touch the database.
    """
    allowed = ALLOWED_TRANSITIONS.get(booking.status, set())
    if new_status not in allowed:
        logger.info(
            "invalid_state_transition",
            extra={
                "booking_id": str(getattr(booking, "id", "")),
                "from_status": booking.status,
                "to_status": new_status,
            },
        )
        raise InvalidStateTransition()
    booking.status = new_status
    return booking
