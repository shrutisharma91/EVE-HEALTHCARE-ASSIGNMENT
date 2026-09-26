from django.http import JsonResponse

from apps.core.exceptions import error_payload


def not_found(request, exception):
    """JSON 404 for routes Django rejects before DRF, including bad UUIDs."""
    return JsonResponse(error_payload("NOT_FOUND", "Not found.", None), status=404)


def server_error(request):
    return JsonResponse(
        error_payload("INTERNAL_ERROR", "An unexpected error occurred.", None),
        status=500,
    )
