"""Domain errors and the one error shape every API response uses."""

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from apps.core.logging import get_logger

logger = get_logger()


class DomainError(Exception):
    """Business-rule failure with a stable code the client can branch on."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "DOMAIN_ERROR"
    message = "Request could not be completed."

    def __init__(self, message=None, *, code=None, status_code=None, details=None):
        if message is not None:
            self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details = details
        super().__init__(self.message)


class EmailAlreadyRegistered(DomainError):
    status_code = status.HTTP_409_CONFLICT
    code = "EMAIL_ALREADY_REGISTERED"
    message = "An account with this email already exists."


class InvalidCredentials(DomainError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "INVALID_CREDENTIALS"
    message = "Invalid email or password."


def error_payload(code: str, message: str, details=None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


def error_response(code: str, message: str, details, http_status: int) -> Response:
    return Response(error_payload(code, message, details), status=http_status)


def _details_from_drf(detail):
    if isinstance(detail, dict):
        return {key: _details_from_drf(value) for key, value in detail.items()}
    if isinstance(detail, list):
        return [str(item) for item in detail]
    return [str(detail)]


def _from_drf(exc, response: Response) -> Response:
    if isinstance(exc, exceptions.ValidationError):
        details = _details_from_drf(exc.detail)
        if not isinstance(details, dict):
            details = {"non_field_errors": details}
        return error_response("VALIDATION_ERROR", "Invalid input.", details, response.status_code)

    if isinstance(exc, exceptions.NotAuthenticated):
        return error_response(
            "NOT_AUTHENTICATED",
            "Authentication credentials were not provided.",
            None,
            response.status_code,
        )

    if isinstance(exc, exceptions.AuthenticationFailed):
        return error_response(
            "AUTHENTICATION_FAILED",
            "Authentication failed.",
            None,
            response.status_code,
        )

    if isinstance(exc, exceptions.PermissionDenied):
        return error_response(
            "PERMISSION_DENIED",
            "You do not have permission to perform this action.",
            None,
            response.status_code,
        )

    if isinstance(exc, exceptions.NotFound):
        return error_response("NOT_FOUND", "Not found.", None, response.status_code)

    if isinstance(exc, exceptions.Throttled):
        details = {"wait_seconds": exc.wait} if exc.wait is not None else None
        return error_response(
            "THROTTLED",
            "Request was throttled.",
            details,
            response.status_code,
        )

    if isinstance(exc, exceptions.ParseError):
        return error_response("PARSE_ERROR", "Malformed request body.", None, response.status_code)

    if isinstance(exc, exceptions.MethodNotAllowed):
        return error_response(
            "METHOD_NOT_ALLOWED",
            "Method not allowed.",
            None,
            response.status_code,
        )

    message = "Request could not be completed."
    if isinstance(exc.detail, str):
        message = exc.detail
    return error_response("API_ERROR", message, None, response.status_code)


def exception_handler(exc, context):
    """Return the standard error envelope. Unexpected errors never leak a traceback."""
    if isinstance(exc, DomainError):
        return error_response(exc.code, exc.message, exc.details, exc.status_code)

    if isinstance(exc, Http404):
        return error_response("NOT_FOUND", "Not found.", None, status.HTTP_404_NOT_FOUND)

    if isinstance(exc, DjangoPermissionDenied):
        return error_response(
            "PERMISSION_DENIED",
            "You do not have permission to perform this action.",
            None,
            status.HTTP_403_FORBIDDEN,
        )

    response = drf_exception_handler(exc, context)
    if response is not None:
        return _from_drf(exc, response)

    request = context.get("request")
    request_id = getattr(request, "request_id", None)
    logger.exception("unhandled_exception", request_id=request_id)
    return error_response(
        "INTERNAL_ERROR",
        "An unexpected error occurred.",
        None,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
