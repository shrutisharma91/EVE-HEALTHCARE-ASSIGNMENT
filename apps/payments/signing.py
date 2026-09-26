"""HMAC checks for the simulated payment provider."""

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.payments.exceptions import InvalidWebhookSignature

MAX_WEBHOOK_AGE = timedelta(minutes=5)


def sign_body(raw_body: bytes, secret: str | None = None) -> str:
    key = (secret if secret is not None else settings.WEBHOOK_SECRET).encode()
    digest = hmac.new(key, raw_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_webhook(raw_body: bytes, signature_header: str, timestamp_header: str) -> None:
    """Reject a missing or bad signature, and timestamps older than five minutes."""
    if not signature_header or not timestamp_header:
        raise InvalidWebhookSignature()
    timestamp = _parse_timestamp(timestamp_header)
    if timezone.now() - timestamp > MAX_WEBHOOK_AGE:
        raise InvalidWebhookSignature()
    expected = sign_body(raw_body).removeprefix("sha256=")
    provided = signature_header.strip().removeprefix("sha256=")
    if len(provided) != len(expected) or not hmac.compare_digest(provided, expected):
        raise InvalidWebhookSignature()


def _parse_timestamp(value: str) -> datetime:
    raw = value.strip()
    if raw.isdigit():
        return datetime.fromtimestamp(int(raw), tz=UTC)
    parsed = parse_datetime(raw)
    if parsed is None:
        raise InvalidWebhookSignature()
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, UTC)
    return parsed
