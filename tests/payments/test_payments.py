from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone
from freezegun import freeze_time
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.bookings.state_machine import CANCELLED, CONFIRMED, transition
from apps.payments.models import Payment, PaymentStatus
from apps.payments.services import apply_payment_result
from apps.payments.simulator import PaymentSimulator
from tests.factories import BookingFactory

PAYMENTS = "/payments/"


def pay(client, booking, key, outcome="SUCCESS", **extra):
    return client.post(
        PAYMENTS,
        {"booking_id": str(booking.id), "simulate_outcome": outcome, **extra},
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )


def _payment(booking, **overrides):
    values = {
        "booking": booking,
        "user": booking.user,
        "amount": booking.amount,
        "currency": "INR",
        "status": PaymentStatus.INITIATED,
        "provider_reference": Payment.new_provider_reference(),
        "idempotency_key": f"key-{Payment.new_provider_reference()}",
    }
    values.update(overrides)
    return Payment.objects.create(**values)


@pytest.mark.django_db
def test_successful_payment_confirms_the_booking(auth_client, user):
    booking = BookingFactory(user=user, amount="450.00")
    response = pay(auth_client, booking, "key-success", amount="1.00")
    assert response.status_code == 201
    assert response.data["status"] == "SUCCESS"
    assert response.data["amount"] == "450.00"
    assert response.data["currency"] == "INR"
    assert response.data["booking_status"] == "CONFIRMED"
    assert response.data["provider_reference"].startswith("sim_pay_")
    booking.refresh_from_db()
    assert booking.status == "CONFIRMED"


@pytest.mark.django_db
def test_failed_payment_fails_the_booking_with_201(auth_client, user):
    booking = BookingFactory(user=user)
    response = pay(auth_client, booking, "key-fail", outcome="FAILED")
    assert response.status_code == 201
    assert response.data["status"] == "FAILED"
    assert response.data["failure_reason"] == "insufficient_funds"
    assert response.data["booking_status"] == "FAILED"
    booking.refresh_from_db()
    assert booking.status == "FAILED"


@pytest.mark.django_db
def test_blank_idempotency_key_is_rejected(auth_client, user):
    booking = BookingFactory(user=user)
    response = pay(auth_client, booking, "   ")
    assert response.status_code == 400
    assert response.data["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_apply_payment_result_rejects_an_unknown_status(user):
    booking = BookingFactory(user=user)
    payment = _payment(booking)
    with pytest.raises(ValueError):
        apply_payment_result(payment, PaymentStatus.INITIATED)


def test_idempotency_key_is_required_and_replays_the_original(auth_client, user):
    booking = BookingFactory(user=user)
    other = BookingFactory(user=user)
    missing = auth_client.post(
        PAYMENTS,
        {"booking_id": str(booking.id), "simulate_outcome": "SUCCESS"},
        format="json",
    )
    assert missing.status_code == 400
    assert missing.data["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"

    first = pay(auth_client, booking, "same-key")
    assert first.status_code == 201
    replay = pay(auth_client, booking, "same-key", outcome="FAILED")
    assert replay.status_code == 200
    assert replay.data["id"] == first.data["id"]
    assert replay.data["status"] == "SUCCESS"
    assert Payment.objects.filter(user=user, idempotency_key="same-key").count() == 1

    reused = pay(auth_client, other, "same-key")
    assert reused.status_code == 422
    assert reused.data["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


@pytest.mark.django_db
def test_cannot_pay_someone_elses_or_unpayable_booking(auth_client, user, other_user):
    foreign = BookingFactory(user=other_user)
    hidden = pay(auth_client, foreign, "foreign")
    assert hidden.status_code == 404

    confirmed = BookingFactory(user=user)
    transition(confirmed, CONFIRMED)
    confirmed.save(update_fields=["status", "updated_at"])
    already = pay(auth_client, confirmed, "already")
    assert already.status_code == 409
    assert already.data["error"]["code"] == "BOOKING_ALREADY_PAID"

    cancelled = BookingFactory(user=user)
    transition(cancelled, CANCELLED)
    cancelled.save(update_fields=["status", "updated_at"])
    closed = pay(auth_client, cancelled, "closed")
    assert closed.status_code == 409
    assert closed.data["error"]["code"] == "BOOKING_NOT_PAYABLE"

    failed = BookingFactory(user=user)
    transition(failed, "FAILED")
    failed.save(update_fields=["status", "updated_at"])
    dead = pay(auth_client, failed, "dead")
    assert dead.status_code == 409
    assert dead.data["error"]["code"] == "BOOKING_NOT_PAYABLE"


@pytest.mark.django_db
def test_expired_booking_cannot_be_paid(auth_client, user):
    booking = BookingFactory(user=user, appointment_at=timezone.now() + timedelta(hours=2))
    with freeze_time(booking.appointment_at + timedelta(minutes=1)):
        access = RefreshToken.for_user(user).access_token
        auth_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        response = pay(auth_client, booking, "expired")
    assert response.status_code == 409
    assert response.data["error"]["code"] == "BOOKING_EXPIRED"


@pytest.mark.django_db
def test_second_attempt_cannot_create_another_success(auth_client, user):
    booking = BookingFactory(user=user)
    first = pay(auth_client, booking, "attempt-1")
    assert first.status_code == 201
    second = pay(auth_client, booking, "attempt-2")
    assert second.status_code == 409
    assert second.data["error"]["code"] == "BOOKING_ALREADY_PAID"
    assert Payment.objects.filter(booking=booking, status=PaymentStatus.SUCCESS).count() == 1


@pytest.mark.django_db
def test_partial_unique_index_allows_many_failures_but_one_success(user):
    booking = BookingFactory(user=user)
    _payment(booking, status=PaymentStatus.FAILED, failure_reason="insufficient_funds")
    _payment(booking, status=PaymentStatus.FAILED, failure_reason="insufficient_funds")
    _payment(booking, status=PaymentStatus.SUCCESS)
    with pytest.raises(IntegrityError), transaction.atomic():
        _payment(booking, status=PaymentStatus.SUCCESS)


@pytest.mark.django_db
def test_payment_reads_are_limited_to_the_owner(auth_client, user, other_user):
    booking = BookingFactory(user=user)
    created = pay(auth_client, booking, "readable")
    own = auth_client.get(f"{PAYMENTS}{created.data['id']}/")
    assert own.status_code == 200
    attempts = auth_client.get(f"/bookings/{booking.id}/payments/")
    assert attempts.status_code == 200
    assert attempts.data["count"] == 1

    other = APIClient()
    access = RefreshToken.for_user(other_user).access_token
    other.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    assert other.get(f"{PAYMENTS}{created.data['id']}/").status_code == 404
    assert other.get(f"/bookings/{booking.id}/payments/").status_code == 404


@pytest.mark.django_db
def test_apply_payment_result_is_order_safe(user):
    booking = BookingFactory(user=user)
    payment = _payment(booking)
    apply_payment_result(payment, PaymentStatus.SUCCESS)
    booking.refresh_from_db()
    payment.refresh_from_db()
    assert booking.status == CONFIRMED
    assert payment.status == PaymentStatus.SUCCESS

    apply_payment_result(payment, PaymentStatus.SUCCESS)
    apply_payment_result(payment, PaymentStatus.FAILED, failure_reason="late")
    booking.refresh_from_db()
    payment.refresh_from_db()
    assert booking.status == CONFIRMED
    assert payment.status == PaymentStatus.SUCCESS

    cancelled = BookingFactory(user=user)
    transition(cancelled, CANCELLED)
    cancelled.save(update_fields=["status", "updated_at"])
    late = _payment(cancelled)
    apply_payment_result(late, PaymentStatus.SUCCESS)
    cancelled.refresh_from_db()
    late.refresh_from_db()
    assert cancelled.status == CANCELLED
    assert late.status == PaymentStatus.SUCCESS


@pytest.mark.django_db
def test_pending_outcome_stays_initiated_until_the_webhook(auth_client, user):
    booking = BookingFactory(user=user, amount="450.00")
    response = pay(auth_client, booking, "key-pending", outcome="PENDING")
    assert response.status_code == 201
    assert response.data["status"] == "INITIATED"
    assert response.data["failure_reason"] is None
    assert response.data["booking_status"] == "PENDING"
    booking.refresh_from_db()
    assert booking.status == "PENDING"
    payment = Payment.objects.get(pk=response.data["id"])
    assert payment.status == PaymentStatus.INITIATED

    from tests.payments.test_webhooks import post_webhook

    payload = {
        "event_id": "evt_pending_settle",
        "event_type": "payment.succeeded",
        "data": {
            "provider_reference": payment.provider_reference,
            "amount": str(payment.amount),
            "currency": "INR",
        },
        "created_at": "2026-09-26T10:00:00Z",
    }
    accepted = post_webhook(payload)
    assert accepted.status_code == 200
    assert accepted.data["status"] == "accepted"
    booking.refresh_from_db()
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.SUCCESS
    assert booking.status == "CONFIRMED"


def test_simulator_uses_the_injected_rng():
    class Sequence:
        def __init__(self, values):
            self.values = iter(values)

        def random(self):
            return next(self.values)

    low = PaymentSimulator(success_rate=0.8, rng=Sequence([0.1]))
    high = PaymentSimulator(success_rate=0.8, rng=Sequence([0.95]))
    assert low.process(object()).status == "SUCCESS"
    assert high.process(object()).failure_reason == "insufficient_funds"
    forced = PaymentSimulator(forced_outcome="FAILED")
    assert forced.process(object()).status == "FAILED"
    pending = PaymentSimulator(forced_outcome="PENDING")
    assert pending.process(object()).status == "PENDING"
    assert pending.process(object()).failure_reason is None
