from django.urls import path

from apps.catalog.views import (
    CentreDetailView,
    CentreListCreateView,
    CentreTestDetailView,
    CentreTestListCreateView,
    TestDetailView,
    TestListCreateView,
)

urlpatterns = [
    path("centres/", CentreListCreateView.as_view(), name="centre-list"),
    path("centres/<uuid:centre_id>/", CentreDetailView.as_view(), name="centre-detail"),
    path(
        "centres/<uuid:centre_id>/tests/",
        CentreTestListCreateView.as_view(),
        name="centre-test-list",
    ),
    path(
        "centres/<uuid:centre_id>/tests/<uuid:test_id>/",
        CentreTestDetailView.as_view(),
        name="centre-test-detail",
    ),
    path("tests/", TestListCreateView.as_view(), name="test-list"),
    path("tests/<uuid:test_id>/", TestDetailView.as_view(), name="test-detail"),
]
