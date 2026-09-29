import hashlib
from contextlib import suppress

from django.core.cache import cache

CENTRE_LIST_TTL_SECONDS = 60 * 5
_VERSION_KEY = "catalog:centres:version"


def centre_list_version() -> int:
    try:
        version = cache.get(_VERSION_KEY)
        if version is None:
            cache.set(_VERSION_KEY, 1, timeout=None)
            return 1
        return int(version)
    except Exception:
        return 1


def invalidate_centre_list_cache() -> None:
    """Bump the list version so every cached page misses. Old keys expire on their TTL."""
    with suppress(Exception):
        try:
            cache.incr(_VERSION_KEY)
        except ValueError:
            cache.set(_VERSION_KEY, 2, timeout=None)


def centre_list_cache_key(params) -> str:
    version = centre_list_version()
    raw = "|".join(
        [
            str(version),
            (params.get("city") or "").strip().lower(),
            (params.get("test_code") or "").strip().upper(),
            (params.get("search") or "").strip().lower(),
            str(params.get("page") or "1"),
            str(params.get("page_size") or ""),
        ]
    )
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return f"catalog:centres:{digest}"
