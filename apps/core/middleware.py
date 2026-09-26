"""Attach one request id to the request, the response, and every log line."""

import uuid

import structlog

_MAX_REQUEST_ID_LENGTH = 128


class RequestIdMiddleware:
    """Reuse an incoming X-Request-ID, or mint one when it is missing or unsafe."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = _request_id(request.headers.get("X-Request-ID", ""))
        request.request_id = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = self.get_response(request)
            response["X-Request-ID"] = request_id
            return response
        finally:
            structlog.contextvars.clear_contextvars()


def _request_id(incoming: str) -> str:
    candidate = incoming.strip()
    if (
        candidate
        and len(candidate) <= _MAX_REQUEST_ID_LENGTH
        and candidate.isascii()
        and " " not in candidate
    ):
        return candidate
    return str(uuid.uuid4())
