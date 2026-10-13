"""Attempt limits for the password and biometric sign-in endpoints.

Every counter lives in Django's default cache and an attempt is claimed BEFORE the
work it guards, so a burst of parallel requests cannot all pass the same stale total.
A cache that cannot answer never blocks a sign-in: the limits are skipped and a
warning says so, because refusing everybody while the cache is down would be a worse
outage than the guessing the limits prevent.

Clients are told apart by address, normalised so that one machine cannot spell itself
into several: an IPv6 client is its whole /64 and an IPv4-mapped IPv6 address is the
IPv4 address it wraps. A sign-in that succeeds gives its own address claim back, so
the address budget counts failures and a NAT full of honest users cannot exhaust it.
"""

import ipaddress
import logging
from hashlib import sha256

from django.core.cache import cache
from django.http import HttpRequest

logger = logging.getLogger(__name__)

LOGIN_ATTEMPT_LIMIT = 10
LOGIN_ATTEMPT_WINDOW = 15 * 60
# Failed attempts across every username from one address, so rotating names cannot
# multiply the guess rate. It also bounds the cache: once an address is over it, no
# further entry is created for the names it makes up.
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


def refund_attempt(key: str) -> None:
    """Give back one attempt claimed in a bucket, never more than was claimed.

    The count goes down by one, which is not a reset: every other attempt in the
    window stays counted. A bucket whose window already ended has nothing to give
    back, so it is left missing instead of being recreated below zero, which would
    buy extra attempts.

    Args:
        key: Cache key of the bucket.
    """
    try:
        # ponytail: if a new window opened since the claim, this takes back one attempt
        # of that window instead, so a budget is off by one once per window at most;
        # a compare-and-set would need a lock the cache API does not offer.
        cache.decr(key)
    except ValueError:
        # The window ended and nothing opened another: nothing is left to give back.
        pass
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
    """Return the client the request counts against, one name per machine.

    An IPv6 client is handed a whole /64, so keying on the raw address would let it
    refill its budget by writing another one of 2**64 addresses; it is reduced to its
    network instead. An IPv4 client reaching a dual-stack socket arrives as
    ::ffff:a.b.c.d and is the same machine as a.b.c.d. A value that is not an address
    at all, or none (uvicorn has no peer behind a unix socket), shares one fixed key,
    which also keeps what a client can make up out of the cache keys.

    Args:
        request: Incoming request.

    Returns:
        The IPv4 address, the IPv6 /64 network, or "" when there is no usable address.
    """
    try:
        address = ipaddress.ip_address(request.META.get("REMOTE_ADDR", ""))
    except ValueError:
        return ""
    if address.version == 4:
        return str(address)
    if address.ipv4_mapped is not None:
        return str(address.ipv4_mapped)
    return str(ipaddress.ip_network((address, 64), strict=False))


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
    # ponytail: behind a proxy REMOTE_ADDR is the proxy, and behind a unix socket it is
    # empty, so every client shares both buckets (nothing here parses X-Forwarded-For).
    # Run uvicorn with --proxy-headers and --forwarded-allow-ips so REMOTE_ADDR is the
    # real client; see docs/installed-adoption.md.
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
    """Settle the buckets of a sign-in that succeeded.

    The failed attempts against the account are forgotten. The address bucket gets
    back the one claim this very sign-in made and nothing else: it spans every
    account name, so clearing it would let a guesser with an account of their own
    refill their budget at will, while keeping the claim would make a NAT full of
    honest users lock itself out after 100 successes. What is left in it is exactly
    the failures.

    Args:
        request: Incoming login request.
        username: Account name that just authenticated.
    """
    forget_attempts(_account_key(request, username))
    refund_attempt(_address_key(request))


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
