import pytest
from django.contrib import admin
from freezegun import freeze_time
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User

SIGNUP_URL = "/auth/signup/"
LOGIN_URL = "/auth/login/"
REFRESH_URL = "/auth/token/refresh/"
ME_URL = "/auth/me/"
PASSWORD = "Str0ng!Passw0rd"


def _error(response):
    return response.data["error"]


@pytest.mark.django_db
def test_signup_returns_user_and_tokens(api_client):
    response = api_client.post(
        SIGNUP_URL,
        {
            "email": "Ada@Eve.Test",
            "password": PASSWORD,
            "full_name": "  Ada Lovelace  ",
            "phone": "+919876543210",
        },
        format="json",
    )
    assert response.status_code == 201
    assert response.data["user"]["email"] == "ada@eve.test"
    assert response.data["user"]["full_name"] == "Ada Lovelace"
    assert response.data["user"]["phone"] == "+919876543210"
    assert response.data["access"]
    assert response.data["refresh"]
    assert "password" not in response.data["user"]
    assert User.objects.filter(email="ada@eve.test").count() == 1


@pytest.mark.django_db
def test_signup_duplicate_email_is_case_insensitive(api_client):
    first = api_client.post(
        SIGNUP_URL,
        {"email": "Ada@Eve.Test", "password": PASSWORD, "full_name": "Ada"},
        format="json",
    )
    assert first.status_code == 201
    second = api_client.post(
        SIGNUP_URL,
        {"email": "ada@eve.test", "password": PASSWORD, "full_name": "Ada Two"},
        format="json",
    )
    assert second.status_code == 409
    assert _error(second)["code"] == "EMAIL_ALREADY_REGISTERED"
    assert set(_error(second)) == {"code", "message", "details"}


@pytest.mark.django_db
def test_signup_weak_password(api_client):
    response = api_client.post(
        SIGNUP_URL,
        {"email": "ada@eve.test", "password": "password", "full_name": "Ada"},
        format="json",
    )
    assert response.status_code == 400
    assert _error(response)["code"] == "VALIDATION_ERROR"
    assert "password" in _error(response)["details"]


@pytest.mark.django_db
def test_signup_missing_fields(api_client):
    response = api_client.post(SIGNUP_URL, {}, format="json")
    assert response.status_code == 400
    assert _error(response)["code"] == "VALIDATION_ERROR"
    assert set(_error(response)["details"]) >= {"email", "password", "full_name"}


@pytest.mark.django_db
def test_login_success(api_client, user):
    response = api_client.post(
        LOGIN_URL,
        {"email": "User@Eve.Test", "password": PASSWORD},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["access"]
    assert response.data["refresh"]


@pytest.mark.django_db
def test_login_wrong_password_and_unknown_email_share_message(api_client, user):
    wrong = api_client.post(
        LOGIN_URL,
        {"email": user.email, "password": "not-the-password"},
        format="json",
    )
    unknown = api_client.post(
        LOGIN_URL,
        {"email": "nobody@eve.test", "password": PASSWORD},
        format="json",
    )
    assert wrong.status_code == 401
    assert unknown.status_code == 401
    assert _error(wrong)["code"] == "INVALID_CREDENTIALS"
    assert _error(unknown)["code"] == "INVALID_CREDENTIALS"
    assert _error(wrong)["message"] == _error(unknown)["message"]


@pytest.mark.django_db
def test_me_requires_a_token(api_client):
    response = api_client.get(ME_URL)
    assert response.status_code == 401
    assert _error(response)["code"] == "NOT_AUTHENTICATED"


@pytest.mark.django_db
def test_me_returns_the_current_user(auth_client, user):
    response = auth_client.get(ME_URL)
    assert response.status_code == 200
    assert response.data["email"] == user.email
    assert response.data["full_name"] == user.full_name


@pytest.mark.django_db
def test_expired_access_token_is_rejected(api_client, user):
    with freeze_time("2026-09-26 10:00:00"):
        token = str(RefreshToken.for_user(user).access_token)
    with freeze_time("2026-09-26 10:31:00"):
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        response = api_client.get(ME_URL)
    assert response.status_code == 401
    assert _error(response)["code"] == "AUTHENTICATION_FAILED"


@pytest.mark.django_db
def test_refresh_rotates_and_blacklists_the_old_token(api_client, user):
    login = api_client.post(
        LOGIN_URL,
        {"email": user.email, "password": PASSWORD},
        format="json",
    )
    old_refresh = login.data["refresh"]
    refreshed = api_client.post(REFRESH_URL, {"refresh": old_refresh}, format="json")
    assert refreshed.status_code == 200
    assert refreshed.data["access"]
    assert refreshed.data["refresh"] != old_refresh

    reused = api_client.post(REFRESH_URL, {"refresh": old_refresh}, format="json")
    assert reused.status_code == 401
    assert _error(reused)["code"] == "AUTHENTICATION_FAILED"

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refreshed.data['access']}")
    assert api_client.get(ME_URL).status_code == 200


def test_user_is_registered_in_admin():
    assert admin.site.is_registered(User)


@pytest.mark.django_db
def test_manager_creates_superusers_and_rejects_a_blank_email():
    from apps.accounts.models import User

    admin = User.objects.create_superuser(
        email="Root@Eve.Test",
        password="Str0ng!Passw0rd",
        full_name="Root",
    )
    assert admin.is_staff is True
    assert admin.is_superuser is True
    assert admin.email == "root@eve.test"

    with pytest.raises(ValueError):
        User.objects.create_user(email="", password="Str0ng!Passw0rd", full_name="Ada")
    with pytest.raises(ValueError):
        User.objects.create_superuser(
            email="nope@eve.test",
            password="Str0ng!Passw0rd",
            full_name="Nope",
            is_staff=False,
        )
