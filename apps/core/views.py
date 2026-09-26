from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import error_payload
from apps.core.serializers import HealthSerializer

_HEALTH_CACHE_KEY = "healthcheck"


class HealthView(APIView):
    """Report whether Postgres and Redis answer. Docker uses this as a healthcheck."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(tags=["Ops"], auth=[], responses={200: HealthSerializer, 503: HealthSerializer})
    def get(self, request):
        db_status = _check_database()
        cache_status = _check_cache()
        healthy = db_status == "ok" and cache_status == "ok"
        payload = {
            "status": "ok" if healthy else "error",
            "db": db_status,
            "cache": cache_status,
        }
        return Response(payload, status=200 if healthy else 503)


def _check_database() -> str:
    try:
        connection.ensure_connection()
    except Exception:
        return "error"
    return "ok"


def _check_cache() -> str:
    try:
        cache.set(_HEALTH_CACHE_KEY, "1", 5)
        if cache.get(_HEALTH_CACHE_KEY) != "1":
            return "error"
    except Exception:
        return "error"
    return "ok"


def not_found(request, exception):
    """JSON 404 for routes Django rejects before DRF, including bad UUIDs."""
    return JsonResponse(error_payload("NOT_FOUND", "Not found.", None), status=404)


def server_error(request):
    return JsonResponse(
        error_payload("INTERNAL_ERROR", "An unexpected error occurred.", None),
        status=500,
    )
