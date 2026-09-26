from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from apps.core.views import HealthView

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("admin/", admin.site.urls),
    path("auth/", include("apps.accounts.urls")),
    path("", include("apps.catalog.urls")),
    path("", include("apps.bookings.urls")),
    path("", include("apps.payments.urls")),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]

handler404 = "apps.core.views.not_found"
handler500 = "apps.core.views.server_error"
