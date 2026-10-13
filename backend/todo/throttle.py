"""Attempt limits for the password and biometric sign-in endpoints.

Every counter lives in Django's default cache and an attempt is claimed BEFORE the
work it guards, so a burst of parallel requests cannot all pass the same stale total.
A cache that cannot answer never blocks a sign-in: the limits are skipped and a
warning says so, because refusing everybody while the cache is down would be a worse
outage than the guessing the limits prevent.
"""

import logging
from hashlib import sha256

from django.core.cache import cache
from django.http import HttpRequest

logger = logging.getLogger(__name__)

LOGIN_ATTEMPT_LIMIT = 10
LOGIN_ATTEMPT_WINDOW = 15 * 60
# Across every username from one address, so rotating names cannot multiply the guess
# rate. It also bounds the cache: once an address is over it, no further entry is
# created for the names it makes up.
ADDRESS_ATTEMPT_LIMIT = 100
BIOMETRIC_ATTEMPT_LIMIT = 10
BIOMETRIC_ATTEMPT_WINDOW = 300


def register_attempt(key: str, window: int) -> int:
    """Claim one attempt in a fixed window and report how many it now holds.

    cache.add opens the window and never resets a running one, and cache.incr counts
    inside it atomically, so concurrent requests cannot read the same stale total the
    way a get-then-set counter does. The claim is made BEFORE the work it guards,
    which is what bounds the work a burst of parallel requests can trigger.

    Args:
        key: Cache key of the bucket.
        window: Seconds the bucket lives, counted from its first attempt.

    Returns:
        Attempts registered in the current window, this one included, or 0 when the
        cache could not answer, which is below every limit.
    """
    try:
        cache.add(key, 0, timeout=window)
        try:
            count = cache.incr(key)
        except ValueError:
            # The window ended between the two calls, so this attempt opens the next
            # one.
            # ponytail: two requests landing exactly here both write 1, undercounting
            # by one once per window at most; use add(key, 1) plus a retry if that
            # matters.
            cache.set(key, 1, timeout=window)
            count = 1
    except Exception as error:  # each cache backend raises its own error types
        return _cache_unavailable(type(error).__name__)
    # A backend configured to swallow its own errors answers None instead of raising.
    return count if count is not None else _cache_unavailable("no answer")


def forget_attempts(key: str) -> None:
    """Drop a bucket, for example after the account it counts signed in.

    Args:
        key: Cache key of the bucket.
    """
    try:
        cache.delete(key)
    except Exception as error:  # each cache backend raises its own error types
        _cache_unavailable(type(error).__name__)


def _cache_unavailable(reason: str) -> int:
    """Log that the limits are off for this request and return the count to report.

    Only the kind of failure is logged: the keys name an address and a hashed account,
    and an error message may carry the cache location.
    """
    logger.warning(
        "Sign-in attempt limits are skipped: the cache is unavailable (%s).", reason
    )
    return 0


def _address(request: HttpRequest) -> str:
    """Return the peer address of the request."""
    return request.META.get("REMOTE_ADDR", "")


def _address_key(request: HttpRequest) -> str:
    """Bucket password attempts by client address across every account name."""
    return f"login-address:{_address(request)}"


def _account_key(request: HttpRequest, username: str) -> str:
    """Bucket password attempts by client address and account name.

    The pair is deliberate. The address alone would let one guesser lock out everyone
    behind the same NAT; the name alone would let anybody lock a victim out from
    anywhere. Names are lower-cased and hashed so the key stays bounded and holds no
    account name.
    """
    # ponytail: behind a proxy REMOTE_ADDR is the proxy, so every client shares both
    # buckets (nothing here parses X-Forwarded-For). Run uvicorn with --proxy-headers
    # and --forwarded-allow-ips so REMOTE_ADDR is the real client; see
    # docs/installed-adoption.md.
    digest = sha256(username.lower().encode()).hexdigest()
    return f"login-attempts:{_address(request)}:{digest}"


def biometric_attempt_key(request: HttpRequest) -> str:
    """Bucket unlock attempts by the credential presented, not by the caller alone.

    REMOTE_ADDR on its own collapses every client behind a proxy or NAT into a single
    counter (nothing here parses X-Forwarded-For), so ten rejected tokens would throttle
    a whole deployment and any success would clear the bucket for everyone. The token is
    256 bits of secrets.token_urlsafe, so a per-token limit is the only one that carries
    information anyway.

    Args:
        request: Incoming biometric login request.

    Returns:
        Cache key scoped to this client and this presented token.
    """
    digest = sha256(
        request.POST.get("biometric_token", "").strip().encode()
    ).hexdigest()
    return f"biometric-attempts:{_address(request)}:{digest}"


def claim_password_attempt(request: HttpRequest, username: str) -> bool:
    """Count one password attempt and say whether it may reach authenticate.

    The address is claimed first and, once it is over budget, the account bucket is
    left alone: a flood of made-up names then stops creating cache entries instead of
    pushing a running bucket out of a full cache.

    Args:
        request: Incoming login request.
        username: Account name the form carried.

    Returns:
        False when the attempt is over budget and must be refused unchecked.
    """
    return (
        register_attempt(_address_key(request), LOGIN_ATTEMPT_WINDOW)
        <= ADDRESS_ATTEMPT_LIMIT
        and register_attempt(_account_key(request, username), LOGIN_ATTEMPT_WINDOW)
        <= LOGIN_ATTEMPT_LIMIT
    )


def release_password_attempts(request: HttpRequest, username: str) -> None:
    """Forget the failed attempts against one account after it signed in.

    The address bucket stays: it spans every account name, so clearing it on a success
    would let a guesser with an account of their own refill their budget at will.

    Args:
        request: Incoming login request.
        username: Account name that just authenticated.
    """
    forget_attempts(_account_key(request, username))


def claim_biometric_attempt(request: HttpRequest) -> bool:
    """Count one unlock attempt and say whether it may reach the token lookup.

    Args:
        request: Incoming biometric login request.

    Returns:
        False when the attempt is over budget and must be refused unchecked.
    """
    return (
        register_attempt(biometric_attempt_key(request), BIOMETRIC_ATTEMPT_WINDOW)
        <= BIOMETRIC_ATTEMPT_LIMIT
    )


def release_biometric_attempts(request: HttpRequest) -> None:
    """Forget the rejected tokens this client presented after one was accepted.

    Args:
        request: Incoming biometric login request.
    """
    forget_attempts(biometric_attempt_key(request))
