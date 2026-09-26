import json

import pytest
from django.core.exceptions import PermissionDenied
from rest_framework.exceptions import MethodNotAllowed

from apps.core.exceptions import exception_handler
from apps.core.views import server_error


def _envelope(response, code):
    body = response.json()
    error = body["error"]
    assert set(body) == {"error"}
    assert set(error) == {"code", "message", "details"}
    assert error["code"] == code
    return error


@pytest.mark.django_db
def test_error_envelope_for_client_failures(api_client, auth_client, user):
    missing = api_client.post("/auth/signup/", {}, format="json")
    assert missing.status_code == 400
    _envelope(missing, "VALIDATION_ERROR")

    anonymous = api_client.get("/auth/me/")
    assert anonymous.status_code == 401
    _envelope(anonymous, "NOT_AUTHENTICATED")

    forbidden = auth_client.post(
        "/centres/",
        {
            "name": "Nope",
            "address": "1 Road",
            "city": "Pune",
            "pincode": "411001",
            "phone": "02040000000",
        },
        format="json",
    )
    assert forbidden.status_code == 403
    _envelope(forbidden, "PERMISSION_DENIED")

    missing_booking = auth_client.get("/bookings/not-a-uuid/")
    assert missing_booking.status_code == 404
    _envelope(missing_booking, "NOT_FOUND")

    api_client.post(
        "/auth/signup/",
        {
            "email": "ada@eve.test",
            "password": "Str0ng!Passw0rd",
            "full_name": "Ada",
        },
        format="json",
    )
    duplicate = api_client.post(
        "/auth/signup/",
        {
            "email": "ADA@eve.test",
            "password": "Str0ng!Passw0rd",
            "full_name": "Ada",
        },
        format="json",
    )
    assert duplicate.status_code == 409
    _envelope(duplicate, "EMAIL_ALREADY_REGISTERED")

    body = {"email": user.email, "password": "wrong-password"}
    for _ in range(5):
        api_client.post("/auth/login/", body, format="json")
    throttled = api_client.post("/auth/login/", body, format="json")
    assert throttled.status_code == 429
    _envelope(throttled, "THROTTLED")


def test_unexpected_errors_stay_inside_the_envelope():
    denied = exception_handler(PermissionDenied(), {})
    assert denied.status_code == 403
    assert denied.data["error"]["code"] == "PERMISSION_DENIED"

    method = exception_handler(MethodNotAllowed("GET"), {})
    assert method.status_code == 405
    assert method.data["error"]["code"] == "METHOD_NOT_ALLOWED"

    blown = exception_handler(RuntimeError("secret traceback"), {"request": None})
    assert blown.status_code == 500
    assert blown.data["error"]["code"] == "INTERNAL_ERROR"
    assert "secret" not in blown.data["error"]["message"]

    fallback = server_error(None)
    assert fallback.status_code == 500
    assert json.loads(fallback.content)["error"]["code"] == "INTERNAL_ERROR"
