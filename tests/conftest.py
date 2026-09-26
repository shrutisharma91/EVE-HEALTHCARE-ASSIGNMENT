import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from tests.factories import UserFactory


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user(db):
    return UserFactory(email="user@eve.test", full_name="Test User")


@pytest.fixture
def other_user(db):
    return UserFactory(email="other@eve.test", full_name="Other User")


@pytest.fixture
def admin_user(db):
    return UserFactory(
        email="admin@eve.test",
        full_name="Admin User",
        is_staff=True,
        is_superuser=True,
    )


@pytest.fixture
def auth_client(api_client, user):
    access = RefreshToken.for_user(user).access_token
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return api_client
