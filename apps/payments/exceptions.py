from apps.core.exceptions import DomainError


class IdempotencyKeyRequired(DomainError):
    status_code = 400
    code = "IDEMPOTENCY_KEY_REQUIRED"
    message = "Idempotency-Key header is required."


class IdempotencyKeyReused(DomainError):
    status_code = 422
    code = "IDEMPOTENCY_KEY_REUSED"
    message = "This Idempotency-Key was already used for a different booking."


class BookingAlreadyPaid(DomainError):
    status_code = 409
    code = "BOOKING_ALREADY_PAID"
    message = "This booking has already been paid."


class BookingNotPayable(DomainError):
    status_code = 409
    code = "BOOKING_NOT_PAYABLE"
    message = "This booking cannot be paid."


class BookingExpired(DomainError):
    status_code = 409
    code = "BOOKING_EXPIRED"
    message = "The appointment is no longer in the future."


class InvalidWebhookSignature(DomainError):
    status_code = 401
    code = "INVALID_WEBHOOK_SIGNATURE"
    message = "Webhook signature is invalid."
