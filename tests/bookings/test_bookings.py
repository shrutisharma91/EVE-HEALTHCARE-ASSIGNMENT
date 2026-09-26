from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone
from freezegun import freeze_time
from rest_framework_simplejwt.tokens import RefreshToken

from apps.bookings.models import Booking
from apps.bookings.state_machine import CONFIRMED, FAILED, transition
from tests.factories import BookingFactory, DiagnosticTestFactory

IST = ZoneInfo("Asia/Kolkata")
BOOKINGS = "/bookings/"


def at_ist(*, days=1, hour=10, minute=0):
    local = timezone.now().astimezone(IST) + timedelta(days=days)
    return local.replace(hour=hour, minute=minute, second=0, microsecond=0)


def book(client, centre, test, when, **extra):
    body = {
        "centre_id": str(centre.id),
        "test_id": str(test.id),
        "appointment_at": when.isoformat(),
        **extra,
    }
    return client.post(BOOKINGS, body, format="json")


def move(booking, status):
    transition(booking, status)
    booking.save(update_fields=["status", "updated_at"])
    booking.refresh_from_db()
    return booking


@pytest.mark.django_db
def test_create_snapshots_price_and_ignores_client_amount(auth_client, user, centre_with_tests):
    when = at_ist(days=3, hour=10)
    response = book(
        auth_client,
        centre_with_tests,
        centre_with_tests.cbc,
        when,
        amount="1.00",
    )
    assert response.status_code == 201
    assert response.data["status"] == "PENDING"
    assert response.data["amount"] == "450.00"
    assert response.data["test_code"] == "CBC"
    stored = Booking.objects.get(pk=response.data["id"])
    assert stored.user_id == user.id
    assert stored.amount == Decimal("450.00")

    centre_with_tests.offerings.filter(test=centre_with_tests.cbc).update(price="999.00")
    stored.refresh_from_db()
    assert stored.amount == Decimal("450.00")
    detail = auth_client.get(f"{BOOKINGS}{stored.id}/")
    assert detail.data["amount"] == "450.00"


@pytest.mark.django_db
def test_appointment_must_be_soon_and_inside_opening_hours(auth_client, centre_with_tests):
    centre = centre_with_tests
    test = centre.cbc
    past = book(auth_client, centre, test, timezone.now() - timedelta(hours=1))
    assert past.status_code == 400
    assert past.data["error"]["details"]["appointment_at"]

    too_far = book(auth_client, centre, test, at_ist(days=91, hour=10))
    assert too_far.status_code == 400
    assert "90 days" in too_far.data["error"]["details"]["appointment_at"][0]

    late = book(auth_client, centre, test, at_ist(days=2, hour=21))
    early = book(auth_client, centre, test, at_ist(days=2, hour=6, minute=30))
    assert late.status_code == 400
    assert early.status_code == 400
    assert late.data["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.django_db
def test_centre_and_test_must_be_bookable(auth_client, centre_with_tests):
    centre = centre_with_tests
    when = at_ist(days=2, hour=11)
    missing_centre = auth_client.post(
        BOOKINGS,
        {
            "centre_id": "11111111-1111-1111-1111-111111111111",
            "test_id": str(centre.cbc.id),
            "appointment_at": when.isoformat(),
        },
        format="json",
    )
    assert missing_centre.status_code == 404

    missing_test = auth_client.post(
        BOOKINGS,
        {
            "centre_id": str(centre.id),
            "test_id": "22222222-2222-2222-2222-222222222222",
            "appointment_at": when.isoformat(),
        },
        format="json",
    )
    assert missing_test.status_code == 404

    not_offered = DiagnosticTestFactory(code="ECG", name="ECG", sample_type="OTHER")
    absent = book(auth_client, centre, not_offered, when)
    assert absent.status_code == 400
    assert absent.data["error"]["code"] == "TEST_NOT_OFFERED_AT_CENTRE"

    unavailable = book(auth_client, centre, centre.lft, when)
    assert unavailable.status_code == 400
    assert unavailable.data["error"]["code"] == "TEST_UNAVAILABLE"

    centre.is_active = False
    centre.save(update_fields=["is_active"])
    inactive = book(auth_client, centre, centre.cbc, when)
    assert inactive.status_code == 400
    assert inactive.data["error"]["code"] == "CENTRE_INACTIVE"

    centre.is_active = True
    centre.save(update_fields=["is_active"])
    centre.cbc.is_active = False
    centre.cbc.save(update_fields=["is_active"])
    retired = book(auth_client, centre, centre.cbc, when)
    assert retired.status_code == 400
    assert retired.data["error"]["code"] == "TEST_INACTIVE"


@pytest.mark.django_db
def test_duplicate_active_booking_conflicts_until_cancelled(auth_client, centre_with_tests):
    when = at_ist(days=4, hour=9)
    first = book(auth_client, centre_with_tests, centre_with_tests.cbc, when)
    assert first.status_code == 201
    second = book(auth_client, centre_with_tests, centre_with_tests.cbc, when)
    assert second.status_code == 409
    assert second.data["error"]["code"] == "DUPLICATE_BOOKING"

    booking = Booking.objects.get(pk=first.data["id"])
    move(booking, CONFIRMED)
    third = book(auth_client, centre_with_tests, centre_with_tests.cbc, when)
    assert third.status_code == 409

    cancelled = auth_client.post(
        f"{BOOKINGS}{booking.id}/cancel/", {"reason": "plans changed"}, format="json"
    )
    assert cancelled.status_code == 200
    assert cancelled.data["status"] == "CANCELLED"
    assert cancelled.data["cancellation_reason"] == "plans changed"
    again = book(auth_client, centre_with_tests, centre_with_tests.cbc, when)
    assert again.status_code == 201


@pytest.mark.django_db
def test_list_and_detail_hide_other_users_bookings(
    auth_client, user, other_user, admin_client, centre_with_tests
):
    own = book(auth_client, centre_with_tests, centre_with_tests.cbc, at_ist(days=2, hour=10))
    foreign = BookingFactory(user=other_user, centre=centre_with_tests, test=centre_with_tests.cbc)
    listing = auth_client.get(BOOKINGS)
    ids = {row["id"] for row in listing.data["results"]}
    assert str(own.data["id"]) in ids
    assert str(foreign.id) not in ids

    hidden = auth_client.get(f"{BOOKINGS}{foreign.id}/")
    assert hidden.status_code == 404
    assert hidden.data["error"]["code"] == "NOT_FOUND"

    visible = admin_client.get(f"{BOOKINGS}{foreign.id}/")
    assert visible.status_code == 200
    staff_list = admin_client.get(BOOKINGS)
    assert staff_list.data["count"] >= 2

    pending = auth_client.get(BOOKINGS, {"status": "PENDING"})
    assert pending.data["count"] >= 1
    assert all(row["status"] == "PENDING" for row in pending.data["results"])


@pytest.mark.django_db
def test_unknown_status_filter_is_rejected(auth_client):
    response = auth_client.get(BOOKINGS, {"status": "NOPE"})
    assert response.status_code == 400
    assert response.data["error"]["code"] == "VALIDATION_ERROR"


def test_malformed_booking_uuid_is_404(auth_client):
    response = auth_client.get(f"{BOOKINGS}not-a-uuid/")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def _use_fresh_token(client, user):
    access = RefreshToken.for_user(user).access_token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")


@pytest.mark.django_db
def test_cancel_follows_the_state_machine(auth_client, user, centre_with_tests):
    centre = centre_with_tests
    pending = Booking.objects.get(
        pk=book(auth_client, centre, centre.cbc, at_ist(days=5, hour=8)).data["id"]
    )
    with freeze_time(pending.appointment_at - timedelta(minutes=30)):
        _use_fresh_token(auth_client, user)
        still_pending = auth_client.post(f"{BOOKINGS}{pending.id}/cancel/", {}, format="json")
    assert still_pending.status_code == 200
    assert still_pending.data["status"] == "CANCELLED"
    _use_fresh_token(auth_client, user)

    confirmed = Booking.objects.get(
        pk=book(auth_client, centre, centre.cbc, at_ist(days=6, hour=12)).data["id"]
    )
    move(confirmed, CONFIRMED)
    early = auth_client.post(f"{BOOKINGS}{confirmed.id}/cancel/", {}, format="json")
    assert early.status_code == 200
    assert early.data["status"] == "CANCELLED"

    late_booking = Booking.objects.get(
        pk=book(auth_client, centre, centre.cbc, at_ist(days=7, hour=15)).data["id"]
    )
    move(late_booking, CONFIRMED)
    with freeze_time(late_booking.appointment_at - timedelta(minutes=30)):
        _use_fresh_token(auth_client, user)
        too_late = auth_client.post(f"{BOOKINGS}{late_booking.id}/cancel/", {}, format="json")
    assert too_late.status_code == 409
    assert too_late.data["error"]["code"] == "CANCELLATION_WINDOW_CLOSED"
    _use_fresh_token(auth_client, user)

    failed = Booking.objects.get(
        pk=book(auth_client, centre, centre.cbc, at_ist(days=8, hour=16)).data["id"]
    )
    move(failed, FAILED)
    failed_cancel = auth_client.post(f"{BOOKINGS}{failed.id}/cancel/", {}, format="json")
    assert failed_cancel.status_code == 409
    assert failed_cancel.data["error"]["code"] == "INVALID_STATE_TRANSITION"

    already = Booking.objects.get(
        pk=book(auth_client, centre, centre.cbc, at_ist(days=9, hour=17)).data["id"]
    )
    auth_client.post(f"{BOOKINGS}{already.id}/cancel/", {}, format="json")
    again = auth_client.post(f"{BOOKINGS}{already.id}/cancel/", {}, format="json")
    assert again.status_code == 409
    assert again.data["error"]["code"] == "INVALID_STATE_TRANSITION"


@pytest.mark.django_db
def test_other_user_cannot_cancel(auth_client, other_user):
    foreign = BookingFactory(user=other_user)
    response = auth_client.post(f"{BOOKINGS}{foreign.id}/cancel/", {}, format="json")
    assert response.status_code == 404
    foreign.refresh_from_db()
    assert foreign.status == "PENDING"
