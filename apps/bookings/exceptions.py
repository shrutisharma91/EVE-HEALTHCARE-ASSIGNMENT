from apps.core.exceptions import DomainError


class InvalidStateTransition(DomainError):
    status_code = 409
    code = "INVALID_STATE_TRANSITION"
    message = "That status change is not allowed."


class DuplicateBooking(DomainError):
    status_code = 409
    code = "DUPLICATE_BOOKING"
    message = "You already have an active booking for this test at that time."


class TestNotOfferedAtCentre(DomainError):
    status_code = 400
    code = "TEST_NOT_OFFERED_AT_CENTRE"
    message = "This centre does not offer that test."


class TestUnavailable(DomainError):
    status_code = 400
    code = "TEST_UNAVAILABLE"
    message = "This test is not currently available at the centre."


class CentreInactive(DomainError):
    status_code = 400
    code = "CENTRE_INACTIVE"
    message = "This centre is not accepting bookings."


class TestInactive(DomainError):
    status_code = 400
    code = "TEST_INACTIVE"
    message = "This test is not currently offered."


class CancellationWindowClosed(DomainError):
    status_code = 409
    code = "CANCELLATION_WINDOW_CLOSED"
    message = "Confirmed bookings can only be cancelled more than 2 hours before the appointment."


class InvalidInput(DomainError):
    status_code = 400
    code = "VALIDATION_ERROR"
    message = "Invalid input."

    def __init__(self, details):
        super().__init__(details=details)
