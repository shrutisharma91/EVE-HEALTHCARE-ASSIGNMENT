import pytest

from apps.bookings.exceptions import InvalidStateTransition
from apps.bookings.models import Booking
from apps.bookings.state_machine import (
    CANCELLED,
    CONFIRMED,
    FAILED,
    PENDING,
    transition,
)

ALLOWED = [
    (PENDING, CONFIRMED),
    (PENDING, FAILED),
    (PENDING, CANCELLED),
    (CONFIRMED, CANCELLED),
]

DISALLOWED = [
    (PENDING, PENDING),
    (CONFIRMED, PENDING),
    (CONFIRMED, FAILED),
    (CONFIRMED, CONFIRMED),
    (FAILED, PENDING),
    (FAILED, CONFIRMED),
    (FAILED, CANCELLED),
    (FAILED, FAILED),
    (CANCELLED, PENDING),
    (CANCELLED, CONFIRMED),
    (CANCELLED, FAILED),
    (CANCELLED, CANCELLED),
]


@pytest.mark.parametrize(("current", "new"), ALLOWED)
def test_allowed_transitions(current, new):
    booking = Booking(status=current)
    transition(booking, new)
    assert booking.status == new


@pytest.mark.parametrize(("current", "new"), DISALLOWED)
def test_disallowed_transitions(current, new):
    booking = Booking(status=current)
    with pytest.raises(InvalidStateTransition) as exc_info:
        transition(booking, new)
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "INVALID_STATE_TRANSITION"
    assert booking.status == current
