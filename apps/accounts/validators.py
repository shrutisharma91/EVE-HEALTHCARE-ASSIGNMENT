import re

from django.core.exceptions import ValidationError

# 10-digit Indian mobile, optionally prefixed with +91. Numbers start with 6-9.
INDIAN_MOBILE_RE = re.compile(r"^(?:\+91)?[6-9]\d{9}$")


def validate_indian_mobile(value: str) -> None:
    if value and not INDIAN_MOBILE_RE.fullmatch(value):
        raise ValidationError("Enter a valid Indian mobile number (10 digits, optional +91).")
