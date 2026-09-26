from datetime import timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
import structlog
from django.utils import timezone
from structlog.testing import LogCapture

from apps.core.logging import configure_logging

IST = ZoneInfo("Asia/Kolkata")


@pytest.mark.django_db
def test_health_reports_database_and_cache(api_client):
    response = api_client.get("/health/")
    assert response.status_code == 200
    assert response.data == {"status": "ok", "db": "ok", "cache": "ok"}


@pytest.mark.django_db
def test_health_is_unavailable_when_a_dependency_fails(api_client):
    with patch("apps.core.views._check_database", return_value="error"):
        down = api_client.get("/health/")
    assert down.status_code == 503
    assert down.data["status"] == "error"
    assert down.data["db"] == "error"
    assert down.data["cache"] == "ok"

    with patch("apps.core.views._check_cache", return_value="error"):
        cache_down = api_client.get("/health/")
    assert cache_down.status_code == 503
    assert cache_down.data["cache"] == "error"


@pytest.mark.django_db
def test_request_id_is_reused_or_generated(api_client):
    echoed = api_client.get("/health/", HTTP_X_REQUEST_ID="req-abc")
    assert echoed["X-Request-ID"] == "req-abc"

    generated = api_client.get("/health/", HTTP_X_REQUEST_ID="not a safe id")
    assert generated["X-Request-ID"]
    assert generated["X-Request-ID"] != "not a safe id"


@pytest.mark.django_db
def test_login_is_throttled(api_client, user):
    body = {"email": user.email, "password": "wrong-password"}
    for _ in range(5):
        attempt = api_client.post("/auth/login/", body, format="json")
        assert attempt.status_code == 401
    blocked = api_client.post("/auth/login/", body, format="json")
    assert blocked.status_code == 429
    assert blocked.data["error"]["code"] == "THROTTLED"
    assert blocked.data["error"]["message"] == "Request was throttled."


@pytest.mark.django_db
def test_booking_created_log_includes_the_request_id(auth_client, centre_with_tests):
    local = timezone.now().astimezone(IST) + timedelta(days=2)
    when = local.replace(hour=10, minute=0, second=0, microsecond=0)
    captured = LogCapture()
    structlog.configure(
        processors=[structlog.contextvars.merge_contextvars, captured],
        cache_logger_on_first_use=False,
    )
    try:
        response = auth_client.post(
            "/bookings/",
            {
                "centre_id": str(centre_with_tests.id),
                "test_id": str(centre_with_tests.cbc.id),
                "appointment_at": when.isoformat(),
            },
            format="json",
            HTTP_X_REQUEST_ID="req-booking",
        )
    finally:
        configure_logging()
    assert response.status_code == 201
    created = [entry for entry in captured.entries if entry["event"] == "booking_created"]
    assert created
    assert created[0]["request_id"] == "req-booking"
    assert "password" not in created[0]
