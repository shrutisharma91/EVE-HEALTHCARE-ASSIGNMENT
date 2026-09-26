import re

from django.core.exceptions import ValidationError

PINCODE_RE = re.compile(r"^\d{6}$")


def validate_pincode(value: str) -> None:
    if not PINCODE_RE.fullmatch(value or ""):
        raise ValidationError("Enter a valid 6-digit pincode.")
