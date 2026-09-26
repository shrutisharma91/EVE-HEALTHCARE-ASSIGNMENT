from decimal import Decimal

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from tests.factories import (
    CentreTestFactory,
    DiagnosticCentreFactory,
    DiagnosticTestFactory,
    UserFactory,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


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
def auth_client(user):
    client = APIClient()
    access = RefreshToken.for_user(user).access_token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return client


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    access = RefreshToken.for_user(admin_user).access_token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return client


@pytest.fixture
def centre_with_tests(db):
    centre = DiagnosticCentreFactory(name="EVE Bengaluru", city="Bengaluru", pincode="560001")
    other = DiagnosticCentreFactory(name="EVE Delhi", city="Delhi", pincode="110001")
    cbc = DiagnosticTestFactory(code="CBC", name="Complete Blood Count")
    lft = DiagnosticTestFactory(code="LFT", name="Liver Function Test")
    CentreTestFactory(centre=centre, test=cbc, price=Decimal("450.00"), is_available=True)
    CentreTestFactory(centre=centre, test=lft, price=Decimal("700.00"), is_available=False)
    CentreTestFactory(centre=other, test=lft, price=Decimal("650.00"), is_available=True)
    centre.cbc = cbc
    centre.lft = lft
    centre.other = other
    return centre
