from django.db.models import Prefetch
from django.shortcuts import get_object_or_404

from apps.catalog.filters import CentreFilter, TestFilter
from apps.catalog.models import CentreTest, DiagnosticCentre, DiagnosticTest


def active_centres():
    return DiagnosticCentre.objects.filter(is_active=True).order_by("city", "name", "id")


def filter_centres(params):
    return CentreFilter(data=params, queryset=active_centres()).qs


def get_centre(centre_id, *, include_inactive: bool):
    offerings = CentreTest.objects.select_related("test").order_by("test__code")
    queryset = DiagnosticCentre.objects.prefetch_related(Prefetch("offerings", queryset=offerings))
    if not include_inactive:
        queryset = queryset.filter(is_active=True)
    return get_object_or_404(queryset, pk=centre_id)


def filter_tests(params, *, include_inactive: bool):
    queryset = DiagnosticTest.objects.all().order_by("code", "id")
    if not include_inactive:
        queryset = queryset.filter(is_active=True)
    return TestFilter(data=params, queryset=queryset).qs
