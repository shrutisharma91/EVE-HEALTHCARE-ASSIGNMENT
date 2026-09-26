import pytest
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection


def test_project_uses_postgres_and_kolkata_time():
    assert connection.vendor == "postgresql" or settings.DATABASES["default"]["ENGINE"].endswith(
        "postgresql"
    )
    assert settings.AUTH_USER_MODEL == "accounts.User"
    assert settings.TIME_ZONE == "Asia/Kolkata"
    assert settings.USE_TZ is True
    assert settings.DEBUG is False


@pytest.mark.django_db
def test_database_connection_is_postgresql():
    assert connection.vendor == "postgresql"


@pytest.mark.django_db
def test_create_user_normalises_email_and_hashes_password():
    from apps.accounts.models import User

    user = User.objects.create_user(
        email="Ada@Eve.Test",
        password="Str0ng!Passw0rd",
        full_name="Ada Lovelace",
        phone="+919876543210",
    )
    assert user.email == "ada@eve.test"
    assert user.check_password("Str0ng!Passw0rd")
    assert user.phone == "+919876543210"


@pytest.mark.django_db
def test_invalid_phone_fails_validation():
    from apps.accounts.models import User

    user = User(email="ada@eve.test", full_name="Ada", phone="12345")
    with pytest.raises(ValidationError):
        user.full_clean()
