from apps.core.exceptions import DomainError


class CentreAlreadyExists(DomainError):
    status_code = 409
    code = "CENTRE_ALREADY_EXISTS"
    message = "A centre with this name already exists in this city."


class TestCodeAlreadyExists(DomainError):
    status_code = 409
    code = "TEST_CODE_ALREADY_EXISTS"
    message = "A test with this code already exists."


class TestAlreadyOffered(DomainError):
    status_code = 409
    code = "TEST_ALREADY_OFFERED"
    message = "This centre already offers that test."
