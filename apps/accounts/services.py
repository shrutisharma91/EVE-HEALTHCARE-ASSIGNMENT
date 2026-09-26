"""Account creation and credential checks. Views stay thin and call these."""

from django.contrib.auth import authenticate
from django.db import IntegrityError, transaction
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.core.exceptions import EmailAlreadyRegistered, InvalidCredentials


def _token_pair(user: User) -> tuple[str, str]:
    refresh = RefreshToken.for_user(user)
    return str(refresh.access_token), str(refresh)


def signup(*, email: str, password: str, full_name: str, phone: str = "") -> tuple[User, str, str]:
    """Create an active user and return them with a fresh JWT pair.

    Email is stored lowercase. A duplicate, including a case-only difference,
    raises EmailAlreadyRegistered. The unique constraint is the race backstop.
    """
    email = email.strip().lower()
    full_name = full_name.strip()
    phone = (phone or "").strip()
    try:
        with transaction.atomic():
            if User.objects.filter(email=email).exists():
                raise EmailAlreadyRegistered()
            user = User(email=email, full_name=full_name, phone=phone)
            user.set_password(password)
            user.save()
    except IntegrityError as exc:
        raise EmailAlreadyRegistered() from exc
    access, refresh = _token_pair(user)
    return user, access, refresh


def login(*, email: str, password: str) -> tuple[str, str]:
    """Return a JWT pair. Unknown emails and bad passwords share one error."""
    user = authenticate(username=email.strip().lower(), password=password)
    if user is None or not user.is_active:
        raise InvalidCredentials()
    return _token_pair(user)
