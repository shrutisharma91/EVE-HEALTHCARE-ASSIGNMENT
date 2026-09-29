import json
import threading
from unittest.mock import patch

import pytest
from django.db import OperationalError, connection
from django.utils import timezone
from rest_framework.test import APIClient

from apps.bookings.state_machine import CANCELLED, transition
from apps.payments.models import Payment, PaymentStatus, ProcessingStatus, WebhookEvent
from apps.payments.signing import sign_webhook
from apps.payments.tasks import process_webhook_event
from tests.factories import BookingFactory

WEBHOOK = "/payments/webhook/"


def _initiated(user, amount="450.00"):
    booking = BookingFactory(user=user, amount=amount)
    payment = Payment.objects.create(
        booking=booking,
        user=user,
        amount=booking.amount,
        currency="INR",
        status=PaymentStatus.INITIATED,
        provider_reference=Payment.new_provider_reference(),
        idempotency_key=f"wh-{Payment.new_provider_reference()}",
    )
    return booking, payment


def _payload(payment, event_id, event_type="payment.succeeded", amount=None, currency="INR"):
    return {
        "event_id": event_id,
        "event_type": event_type,
        "data": {
            "provider_reference": payment.provider_reference if payment else "sim_pay_missing",
            "amount": amount
            if amount is not None
            else str(payment.amount if payment else "450.00"),
            "currency": currency,
        },
        "created_at": "2026-09-26T10:00:00Z",
    }


def post_webhook(payload, *, timestamp=None, signature=None, include_signature=True):
    body = json.dumps(payload).encode()
    stamp = timestamp or str(int(timezone.now().timestamp()))
    headers = {
        "HTTP_X_WEBHOOK_TIMESTAMP": stamp,
    }
    if include_signature:
        headers["HTTP_X_WEBHOOK_SIGNATURE"] = (
            sign_webhook(stamp, body) if signature is None else signature
        )
    return APIClient().post(WEBHOOK, data=body, content_type="application/json", **headers)


@pytest.mark.django_db
def test_iso_timestamp_and_a_second_pass_are_safe(user):
    from apps.payments.tasks import handle_webhook_event

    booking, payment = _initiated(user)
    payload = _payload(payment, "evt_iso")
    naive = timezone.now().replace(tzinfo=None).isoformat(timespec="seconds")
    response = post_webhook(payload, timestamp=naive)
    assert response.status_code == 200
    assert response.data["status"] == "accepted"
    booking.refresh_from_db()
    assert booking.status == "CONFIRMED"
    handle_webhook_event("evt_iso")
    booking.refresh_from_db()
    assert booking.status == "CONFIRMED"

    garbage = post_webhook(_payload(payment, "evt_bad_time"), timestamp="not-a-time")
    assert garbage.status_code == 401
    assert garbage.data["error"]["code"] == "INVALID_WEBHOOK_SIGNATURE"


@pytest.mark.django_db
def test_insert_race_is_a_duplicate(user):
    from django.db import IntegrityError

    _booking, payment = _initiated(user)
    payload = _payload(payment, "evt_race")
    first = post_webhook(payload)
    assert first.status_code == 200
    with patch(
        "apps.payments.ingress.WebhookEvent.objects.get_or_create",
        side_effect=IntegrityError("duplicate"),
    ):
        raced = post_webhook(payload)
    assert raced.status_code == 200
    assert raced.data["status"] == "duplicate"
    assert WebhookEvent.objects.filter(event_id="evt_race").count() == 1


@pytest.mark.django_db
def test_valid_webhook_confirms_the_booking(user):
    booking, payment = _initiated(user)
    response = post_webhook(_payload(payment, "evt_ok"))
    assert response.status_code == 200
    assert response.data["status"] == "accepted"
    booking.refresh_from_db()
    payment.refresh_from_db()
    event = WebhookEvent.objects.get(event_id="evt_ok")
    assert booking.status == "CONFIRMED"
    assert payment.status == PaymentStatus.SUCCESS
    assert event.processing_status == ProcessingStatus.PROCESSED


@pytest.mark.django_db
def test_bad_signature_stale_timestamp_and_malformed_body(user):
    _booking, payment = _initiated(user)
    missing = post_webhook(_payload(payment, "evt_missing_sig"), include_signature=False)
    assert missing.status_code == 401
    assert missing.data["error"]["code"] == "INVALID_WEBHOOK_SIGNATURE"

    invalid = post_webhook(_payload(payment, "evt_bad_sig"), signature="sha256=abcd")
    assert invalid.status_code == 401

    stale = post_webhook(
        _payload(payment, "evt_stale"),
        timestamp=str(int(timezone.now().timestamp()) - 301),
    )
    assert stale.status_code == 401

    malformed = post_webhook({"event_type": "payment.succeeded"})
    assert malformed.status_code == 400
    assert malformed.data["error"]["code"] == "VALIDATION_ERROR"
    assert WebhookEvent.objects.count() == 0


@pytest.mark.django_db
def test_duplicate_delivery_updates_the_booking_once(user):
    booking, payment = _initiated(user)
    payload = _payload(payment, "evt_repeat")
    statuses = [post_webhook(payload).data["status"] for _ in range(3)]
    assert statuses[0] == "accepted"
    assert statuses[1:] == ["duplicate", "duplicate"]
    assert WebhookEvent.objects.filter(event_id="evt_repeat").count() == 1
    booking.refresh_from_db()
    assert booking.status == "CONFIRMED"

    changed = _payload(payment, "evt_repeat", amount="1.00")
    replay = post_webhook(changed)
    assert replay.status_code == 200
    assert replay.data["status"] == "duplicate"
    booking.refresh_from_db()
    assert booking.status == "CONFIRMED"
    assert WebhookEvent.objects.get(event_id="evt_repeat").payload["data"]["amount"] == str(
        payment.amount
    )


@pytest.mark.django_db
def test_unknown_reference_and_amount_mismatch_do_not_touch_the_booking(user):
    booking, payment = _initiated(user)
    unknown = post_webhook(_payload(None, "evt_unknown"))
    assert unknown.status_code == 200
    assert unknown.data["status"] == "accepted"
    assert (
        WebhookEvent.objects.get(event_id="evt_unknown").processing_status
        == ProcessingStatus.FAILED
    )
    booking.refresh_from_db()
    assert booking.status == "PENDING"

    mismatch = post_webhook(_payload(payment, "evt_mismatch", amount="1.00"))
    assert mismatch.status_code == 200
    event = WebhookEvent.objects.get(event_id="evt_mismatch")
    assert event.processing_status == ProcessingStatus.FAILED
    booking.refresh_from_db()
    payment.refresh_from_db()
    assert booking.status == "PENDING"
    assert payment.status == PaymentStatus.INITIATED


@pytest.mark.django_db
def test_late_failure_and_success_on_a_cancelled_booking(user):
    booking, payment = _initiated(user)
    assert post_webhook(_payload(payment, "evt_success")).status_code == 200
    late = post_webhook(_payload(payment, "evt_late", event_type="payment.failed"))
    assert late.data["status"] == "accepted"
    booking.refresh_from_db()
    payment.refresh_from_db()
    assert booking.status == "CONFIRMED"
    assert payment.status == PaymentStatus.SUCCESS
    assert (
        WebhookEvent.objects.get(event_id="evt_late").processing_status
        == ProcessingStatus.PROCESSED
    )

    cancelled_booking, cancelled_payment = _initiated(user)
    transition(cancelled_booking, CANCELLED)
    cancelled_booking.cancelled_at = timezone.now()
    cancelled_booking.save(update_fields=["status", "cancelled_at", "updated_at"])
    post_webhook(_payload(cancelled_payment, "evt_cancelled_success"))
    cancelled_booking.refresh_from_db()
    cancelled_payment.refresh_from_db()
    assert cancelled_booking.status == CANCELLED
    assert cancelled_payment.status == PaymentStatus.SUCCESS


@pytest.mark.django_db
def test_unknown_event_type_is_ignored(user):
    booking, payment = _initiated(user)
    response = post_webhook(_payload(payment, "evt_refund", event_type="payment.refunded"))
    assert response.status_code == 200
    assert response.data["status"] == "ignored"
    event = WebhookEvent.objects.get(event_id="evt_refund")
    assert event.processing_status == ProcessingStatus.IGNORED
    booking.refresh_from_db()
    assert booking.status == "PENDING"


@pytest.mark.django_db
def test_retry_increments_attempts_on_operational_error(user):
    WebhookEvent.objects.create(
        event_id="evt_retry",
        event_type="payment.succeeded",
        payload={"data": {}},
        processing_status=ProcessingStatus.RECEIVED,
    )
    with (
        patch(
            "apps.payments.tasks.handle_webhook_event",
            side_effect=OperationalError("db down"),
        ),
        pytest.raises(OperationalError),
    ):
        process_webhook_event("evt_retry")
    event = WebhookEvent.objects.get(event_id="evt_retry")
    assert event.attempts == 1
    assert "db down" in event.last_error

    process_webhook_event.push_request(retries=process_webhook_event.max_retries)
    try:
        with patch(
            "apps.payments.tasks.handle_webhook_event",
            side_effect=OperationalError("db down"),
        ):
            process_webhook_event.run("evt_retry")
    finally:
        process_webhook_event.pop_request()
    event.refresh_from_db()
    assert event.attempts == 2
    assert event.processing_status == ProcessingStatus.FAILED


@pytest.mark.django_db(transaction=True)
def test_concurrent_duplicate_webhook_is_processed_once(user):
    """Threads deliver one event together. Exactly one ledger row is processed."""
    booking, payment = _initiated(user)
    payload = _payload(payment, "evt_concurrent")
    body = json.dumps(payload).encode()
    timestamp = str(int(timezone.now().timestamp()))
    signature = sign_webhook(timestamp, body)
    barrier = threading.Barrier(6)
    statuses = []
    errors = []

    def worker():
        try:
            barrier.wait(timeout=10)
            client = APIClient()
            response = client.post(
                WEBHOOK,
                data=body,
                content_type="application/json",
                HTTP_X_WEBHOOK_SIGNATURE=signature,
                HTTP_X_WEBHOOK_TIMESTAMP=timestamp,
            )
            statuses.append(response.status_code)
        except Exception as exc:  # noqa: BLE001 - the test reports worker failures
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors
    assert statuses == [200, 200, 200, 200, 200, 200] or set(statuses) == {200}
    assert WebhookEvent.objects.filter(event_id="evt_concurrent").count() == 1
    event = WebhookEvent.objects.get(event_id="evt_concurrent")
    assert event.processing_status == ProcessingStatus.PROCESSED
    booking.refresh_from_db()
    assert booking.status == "CONFIRMED"


@pytest.mark.django_db
def test_late_success_after_second_attempt_confirms_only_once(auth_client, user):
    """Variant a: first PENDING, second SUCCESS, late success webhook for attempt 1."""
    from tests.payments.test_payments import pay

    booking = BookingFactory(user=user, amount="450.00")
    first = pay(auth_client, booking, "late-a-1", outcome="PENDING")
    second = pay(auth_client, booking, "late-a-2", outcome="SUCCESS")
    assert first.status_code == 201
    assert second.status_code == 201
    booking.refresh_from_db()
    assert booking.status == "CONFIRMED"

    first_payment = Payment.objects.get(pk=first.data["id"])
    response = post_webhook(_payload(first_payment, "evt_late_a"))
    assert response.status_code == 200
    booking.refresh_from_db()
    first_payment.refresh_from_db()
    event = WebhookEvent.objects.get(event_id="evt_late_a")
    assert booking.status == "CONFIRMED"
    assert first_payment.status == PaymentStatus.FAILED
    assert first_payment.failure_reason == "duplicate_gateway_success_refund_required"
    assert event.processing_status == ProcessingStatus.PROCESSED
    assert Payment.objects.filter(booking=booking, status=PaymentStatus.SUCCESS).count() == 1


@pytest.mark.django_db
def test_late_success_after_failed_booking_does_not_resurrect(auth_client, user):
    """Variant b: first PENDING, second FAILED, late success webhook for attempt 1."""
    from tests.payments.test_payments import pay

    booking = BookingFactory(user=user, amount="450.00")
    first = pay(auth_client, booking, "late-b-1", outcome="PENDING")
    second = pay(auth_client, booking, "late-b-2", outcome="FAILED")
    assert second.status_code == 201
    booking.refresh_from_db()
    assert booking.status == "FAILED"

    first_payment = Payment.objects.get(pk=first.data["id"])
    response = post_webhook(_payload(first_payment, "evt_late_b"))
    assert response.status_code == 200
    booking.refresh_from_db()
    first_payment.refresh_from_db()
    event = WebhookEvent.objects.get(event_id="evt_late_b")
    assert booking.status == "FAILED"
    assert first_payment.status == PaymentStatus.SUCCESS
    assert event.processing_status == ProcessingStatus.PROCESSED


@pytest.mark.django_db
def test_failure_webhook_after_cancel_settles_payment_only(auth_client, user):
    """Variant c: PENDING payment, user cancels, then payment.failed webhook."""
    from tests.payments.test_payments import pay

    booking = BookingFactory(user=user, amount="450.00")
    first = pay(auth_client, booking, "late-c-1", outcome="PENDING")
    transition(booking, CANCELLED)
    booking.cancelled_at = timezone.now()
    booking.save(update_fields=["status", "cancelled_at", "updated_at"])

    first_payment = Payment.objects.get(pk=first.data["id"])
    response = post_webhook(_payload(first_payment, "evt_late_c", event_type="payment.failed"))
    assert response.status_code == 200
    booking.refresh_from_db()
    first_payment.refresh_from_db()
    event = WebhookEvent.objects.get(event_id="evt_late_c")
    assert booking.status == CANCELLED
    assert first_payment.status == PaymentStatus.FAILED
    assert event.processing_status == ProcessingStatus.PROCESSED


@pytest.mark.django_db
def test_future_timestamp_outside_window_is_rejected(user):
    _booking, payment = _initiated(user)
    future = str(int(timezone.now().timestamp()) + 600)
    response = post_webhook(_payload(payment, "evt_future"), timestamp=future)
    assert response.status_code == 401
    assert response.data["error"]["code"] == "INVALID_WEBHOOK_SIGNATURE"


@pytest.mark.django_db
def test_webhook_ignores_unknown_extra_fields(user):
    booking, payment = _initiated(user)
    payload = _payload(payment, "evt_extra")
    payload["provider_meta"] = {"region": "in"}
    response = post_webhook(payload)
    assert response.status_code == 200
    assert response.data["status"] == "accepted"
    booking.refresh_from_db()
    assert booking.status == "CONFIRMED"
