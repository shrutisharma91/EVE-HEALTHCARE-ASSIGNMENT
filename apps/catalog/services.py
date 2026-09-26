"""Catalog writes. Each one is atomic and clears the centre-list cache afterwards."""

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404

from apps.catalog.cache import invalidate_centre_list_cache
from apps.catalog.exceptions import (
    CentreAlreadyExists,
    TestAlreadyOffered,
    TestCodeAlreadyExists,
)
from apps.catalog.models import CentreTest, DiagnosticCentre, DiagnosticTest


def create_centre(**fields) -> DiagnosticCentre:
    """Create a centre. The (name, city) pair is unique."""
    try:
        with transaction.atomic():
            centre = DiagnosticCentre.objects.create(**fields)
    except IntegrityError as exc:
        raise CentreAlreadyExists() from exc
    invalidate_centre_list_cache()
    return centre


def update_centre(*, centre_id, **fields) -> DiagnosticCentre:
    """Update a centre, including one that was soft-deleted, so staff can restore it."""
    try:
        with transaction.atomic():
            centre = get_object_or_404(
                DiagnosticCentre.objects.select_for_update(),
                pk=centre_id,
            )
            for name, value in fields.items():
                setattr(centre, name, value)
            centre.save()
    except IntegrityError as exc:
        raise CentreAlreadyExists() from exc
    invalidate_centre_list_cache()
    return centre


def deactivate_centre(*, centre_id) -> DiagnosticCentre:
    """Hide a centre from the public catalogue without deleting its history."""
    with transaction.atomic():
        centre = get_object_or_404(
            DiagnosticCentre.objects.select_for_update(),
            pk=centre_id,
        )
        centre.is_active = False
        centre.save(update_fields=["is_active", "updated_at"])
    invalidate_centre_list_cache()
    return centre


def create_test(**fields) -> DiagnosticTest:
    try:
        with transaction.atomic():
            test = DiagnosticTest.objects.create(**fields)
    except IntegrityError as exc:
        raise TestCodeAlreadyExists() from exc
    invalidate_centre_list_cache()
    return test


def update_test(*, test_id, **fields) -> DiagnosticTest:
    try:
        with transaction.atomic():
            test = get_object_or_404(DiagnosticTest.objects.select_for_update(), pk=test_id)
            for name, value in fields.items():
                setattr(test, name, value)
            test.save()
    except IntegrityError as exc:
        raise TestCodeAlreadyExists() from exc
    invalidate_centre_list_cache()
    return test


def add_centre_test(*, centre_id, test_id, price, is_available=True) -> CentreTest:
    """Attach a catalogue test to a centre at that centre's price."""
    try:
        with transaction.atomic():
            centre = get_object_or_404(
                DiagnosticCentre.objects.select_for_update(),
                pk=centre_id,
            )
            test = get_object_or_404(DiagnosticTest, pk=test_id)
            if CentreTest.objects.filter(centre=centre, test=test).exists():
                raise TestAlreadyOffered()
            offering = CentreTest.objects.create(
                centre=centre,
                test=test,
                price=price,
                is_available=is_available,
            )
    except IntegrityError as exc:
        raise TestAlreadyOffered() from exc
    invalidate_centre_list_cache()
    return CentreTest.objects.select_related("test").get(pk=offering.pk)


def update_centre_test(*, centre_id, test_id, **fields) -> CentreTest:
    with transaction.atomic():
        offering = get_object_or_404(
            CentreTest.objects.select_for_update().select_related("test"),
            centre_id=centre_id,
            test_id=test_id,
        )
        for name, value in fields.items():
            setattr(offering, name, value)
        offering.save()
    invalidate_centre_list_cache()
    return offering


def remove_centre_test(*, centre_id, test_id) -> None:
    with transaction.atomic():
        offering = get_object_or_404(
            CentreTest.objects.select_for_update(),
            centre_id=centre_id,
            test_id=test_id,
        )
        offering.delete()
    invalidate_centre_list_cache()
