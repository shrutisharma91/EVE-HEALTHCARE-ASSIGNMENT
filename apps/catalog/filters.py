import django_filters
from django.db.models import Q

from apps.catalog.models import DiagnosticCentre, DiagnosticTest


class CentreFilter(django_filters.FilterSet):
    city = django_filters.CharFilter(field_name="city", lookup_expr="iexact")
    search = django_filters.CharFilter(field_name="name", lookup_expr="icontains")
    test_code = django_filters.CharFilter(method="filter_test_code")

    class Meta:
        model = DiagnosticCentre
        fields = ["city", "search", "test_code"]

    def filter_test_code(self, queryset, name, value):
        return queryset.filter(
            offerings__test__code__iexact=value.strip(),
            offerings__is_available=True,
            offerings__test__is_active=True,
        ).distinct()


class TestFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(method="filter_search")

    class Meta:
        model = DiagnosticTest
        fields = ["search"]

    def filter_search(self, queryset, name, value):
        return queryset.filter(Q(name__icontains=value) | Q(code__icontains=value))
