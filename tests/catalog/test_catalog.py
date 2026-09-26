import pytest
from django.core.management import call_command

from apps.catalog.models import DiagnosticCentre, DiagnosticTest
from tests.factories import DiagnosticCentreFactory, DiagnosticTestFactory

CENTRES = "/centres/"
TESTS = "/tests/"


def _error(response):
    return response.json()["error"] if not hasattr(response, "data") else response.data["error"]


@pytest.mark.django_db
def test_list_filters_by_city_and_test_code(api_client, centre_with_tests):
    by_city = api_client.get(CENTRES, {"city": "bengaluru"})
    assert by_city.status_code == 200
    assert by_city.data["count"] == 1
    assert by_city.data["results"][0]["city"] == "Bengaluru"

    by_code = api_client.get(CENTRES, {"test_code": "cbc"})
    assert [row["id"] for row in by_code.data["results"]] == [str(centre_with_tests.id)]

    unavailable = api_client.get(CENTRES, {"test_code": "LFT"})
    assert [row["id"] for row in unavailable.data["results"]] == [str(centre_with_tests.other.id)]

    by_name = api_client.get(CENTRES, {"search": "delhi"})
    assert by_name.data["count"] == 1
    assert by_name.data["results"][0]["name"] == "EVE Delhi"


@pytest.mark.django_db
def test_centre_list_is_paginated(api_client):
    for index in range(12):
        DiagnosticCentreFactory(name=f"Page Centre {index}", city="Pune", pincode="411001")
    first = api_client.get(CENTRES, {"page_size": 10})
    second = api_client.get(CENTRES, {"page_size": 10, "page": 2})
    assert first.data["count"] == 12
    assert len(first.data["results"]) == 10
    assert len(second.data["results"]) == 2
    huge = api_client.get(CENTRES, {"page_size": 1000})
    assert len(huge.data["results"]) == 12


@pytest.mark.django_db
def test_centre_detail_includes_prices(api_client, centre_with_tests):
    response = api_client.get(f"{CENTRES}{centre_with_tests.id}/")
    assert response.status_code == 200
    prices = {row["code"]: row["price"] for row in response.data["tests"]}
    assert prices["CBC"] == "450.00"
    assert prices["LFT"] == "700.00"
    offered = api_client.get(f"{CENTRES}{centre_with_tests.id}/tests/")
    assert offered.status_code == 200
    assert {row["code"] for row in offered.data} == {"CBC", "LFT"}


@pytest.mark.django_db
def test_non_admin_cannot_create_a_centre(auth_client):
    response = auth_client.post(
        CENTRES,
        {
            "name": "Blocked",
            "address": "1 Road",
            "city": "Pune",
            "pincode": "411001",
            "phone": "02040000000",
        },
        format="json",
    )
    assert response.status_code == 403
    assert response.data["error"]["code"] == "PERMISSION_DENIED"


@pytest.mark.django_db
def test_admin_can_create_and_update_centre_and_test(admin_client):
    created = admin_client.post(
        CENTRES,
        {
            "name": "EVE Lab",
            "address": "  9 Residency Road  ",
            "city": "Mumbai",
            "pincode": "400001",
            "phone": "02240000000",
            "latitude": "18.920000",
            "longitude": "72.830000",
        },
        format="json",
    )
    assert created.status_code == 201
    centre_id = created.data["id"]
    assert created.data["address"] == "9 Residency Road"

    test = admin_client.post(
        TESTS,
        {
            "code": "cbc",
            "name": "Complete Blood Count",
            "sample_type": "BLOOD",
            "description": "Counts",
        },
        format="json",
    )
    assert test.status_code == 201
    assert test.data["code"] == "CBC"

    offering = admin_client.post(
        f"{CENTRES}{centre_id}/tests/",
        {"test_id": test.data["id"], "price": "499.00"},
        format="json",
    )
    assert offering.status_code == 201
    assert offering.data["price"] == "499.00"

    updated = admin_client.patch(
        f"{CENTRES}{centre_id}/tests/{test.data['id']}/",
        {"price": "525.50", "is_available": False},
        format="json",
    )
    assert updated.status_code == 200
    assert updated.data["price"] == "525.50"
    assert updated.data["is_available"] is False

    renamed = admin_client.patch(
        f"{CENTRES}{centre_id}/",
        {"phone": "02241111111"},
        format="json",
    )
    assert renamed.status_code == 200
    assert renamed.data["phone"] == "02241111111"


@pytest.mark.django_db
def test_soft_delete_hides_centre_from_the_public(api_client, admin_client):
    centre = DiagnosticCentreFactory(name="Soon Hidden", city="Delhi", pincode="110001")
    deleted = admin_client.delete(f"{CENTRES}{centre.id}/")
    assert deleted.status_code == 204
    centre.refresh_from_db()
    assert centre.is_active is False
    assert api_client.get(CENTRES).data["count"] == 0
    hidden = api_client.get(f"{CENTRES}{centre.id}/")
    assert hidden.status_code == 404
    assert hidden.data["error"]["code"] == "NOT_FOUND"
    visible_to_staff = admin_client.get(f"{CENTRES}{centre.id}/")
    assert visible_to_staff.status_code == 200


@pytest.mark.django_db
def test_centre_list_cache_is_invalidated_on_update(api_client, admin_client):
    centre = DiagnosticCentreFactory(name="Cache Clinic", city="Pune", pincode="411001")
    warm = api_client.get(CENTRES)
    assert warm.data["results"][0]["name"] == "Cache Clinic"

    centre.name = "Hidden Clinic"
    centre.save(update_fields=["name"])
    stale = api_client.get(CENTRES)
    assert stale.data["results"][0]["name"] == "Cache Clinic"

    patched = admin_client.patch(
        f"{CENTRES}{centre.id}/",
        {"name": "Fresh Clinic"},
        format="json",
    )
    assert patched.status_code == 200
    fresh = api_client.get(CENTRES)
    assert fresh.data["results"][0]["name"] == "Fresh Clinic"


@pytest.mark.django_db
def test_invalid_centre_uuid_is_404(api_client):
    response = api_client.get(f"{CENTRES}not-a-uuid/")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.django_db
def test_duplicate_centre_and_bad_pincode(admin_client):
    body = {
        "name": "EVE Lab",
        "address": "1 Road",
        "city": "Pune",
        "pincode": "411001",
        "phone": "02040000000",
    }
    assert admin_client.post(CENTRES, body, format="json").status_code == 201
    duplicate = admin_client.post(CENTRES, body, format="json")
    assert duplicate.status_code == 409
    assert duplicate.data["error"]["code"] == "CENTRE_ALREADY_EXISTS"
    bad = admin_client.post(CENTRES, {**body, "name": "Other", "pincode": "12"}, format="json")
    assert bad.status_code == 400
    assert bad.data["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.django_db
def test_catalogue_search_and_seed_are_idempotent(api_client):
    DiagnosticTestFactory(code="CBC", name="Complete Blood Count")
    found = api_client.get(TESTS, {"search": "blood"})
    assert found.data["count"] == 1
    call_command("seed_data")
    call_command("seed_data")
    assert DiagnosticCentre.objects.filter(name="EVE Diagnostics Guwahati").count() == 1
    assert DiagnosticTest.objects.filter(code="CBC").count() == 1
    assert DiagnosticTest.objects.count() == 10


@pytest.mark.django_db
def test_admin_can_update_a_test_and_remove_an_offering(admin_client, centre_with_tests):
    renamed = admin_client.patch(
        f"{TESTS}{centre_with_tests.cbc.id}/",
        {"name": "CBC Panel"},
        format="json",
    )
    assert renamed.status_code == 200
    assert renamed.data["name"] == "CBC Panel"

    empty = admin_client.patch(f"{TESTS}{centre_with_tests.cbc.id}/", {}, format="json")
    assert empty.status_code == 400

    removed = admin_client.delete(
        f"{CENTRES}{centre_with_tests.id}/tests/{centre_with_tests.cbc.id}/"
    )
    assert removed.status_code == 204
    listed = admin_client.get(f"{CENTRES}{centre_with_tests.id}/tests/")
    assert [row["code"] for row in listed.data] == ["LFT"]


@pytest.mark.django_db
def test_seed_promotes_an_existing_admin_email(admin_user):
    admin_user.is_staff = False
    admin_user.is_superuser = False
    admin_user.save(update_fields=["is_staff", "is_superuser"])
    call_command("seed_data")
    admin_user.refresh_from_db()
    assert admin_user.is_staff is True
    assert admin_user.is_superuser is True


@pytest.mark.django_db
def test_zero_price_is_rejected(admin_client, centre_with_tests):
    response = admin_client.post(
        f"{CENTRES}{centre_with_tests.id}/tests/",
        {"test_id": str(centre_with_tests.cbc.id), "price": "0.00"},
        format="json",
    )
    assert response.status_code == 400
    assert "price" in response.data["error"]["details"]
