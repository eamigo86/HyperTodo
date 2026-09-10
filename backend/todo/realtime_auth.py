"""Fresh database-session authority for the app-owned SSE endpoint."""

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from asgiref.sync import sync_to_async
from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user
from django.contrib.sessions.backends.db import SessionStore
from django.db import router
from django.http import HttpRequest
from django.utils.crypto import constant_time_compare

from .realtime_config import RealtimeConfig, get_realtime_config
from .realtime_notifications import private_topic, ui_topic
from .session_contract import (
    CLIENT_CONTRACT,
    CLIENT_CONTRACT_HEADER,
    EXPECTED_SESSION_HEADER,
    session_binding,
    valid_expected_binding,
)


class RealtimeDenied(Exception):
    """Closed HTTP failure without private identity or exception information."""

    def __init__(self, status: int) -> None:
        """Capture a status without storing untrusted error details.

        Args:
            status: Closed endpoint denial status.
        """
        self.status = status
        super().__init__("Realtime request unavailable")


@dataclass(frozen=True, slots=True)
class Identity:
    """Authenticated principal and exact session binding captured server-side."""

    using: str
    user_id: str = field(repr=False)
    binding: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class Access:
    """Authorized connection inputs, not a bearer credential or client topic."""

    config: RealtimeConfig
    identity: Identity
    session_key: str = field(repr=False)


def fresh_identity(session_key: str | None) -> Identity | None:
    """Load a new session and apply Django's user/active/auth-hash validation.

    Args:
        session_key: Captured cookie key; never a cached request session.

    Returns:
        Actual database identity or None after expiry, revocation or logout.
    """
    request = HttpRequest()
    request.session = SessionStore(session_key=session_key)
    request.user = get_user(request)
    user = request.user
    if not user.is_authenticated or not user.is_active:
        return None
    return Identity(user._state.db, str(user.pk), session_binding(request))


fresh_identity_async = sync_to_async(fresh_identity, thread_sensitive=True)


def same_identity(expected: Identity, actual: Identity | None) -> bool:
    """Reject replacement users, databases and session keys without adoption.

    Args:
        expected: Captured authenticated connection identity.
        actual: Freshly resolved authority, possibly anonymous.

    Returns:
        Whether all authority components still match.
    """
    return (
        actual is not None
        and actual.using == expected.using
        and actual.user_id == expected.user_id
        and constant_time_compare(actual.binding, expected.binding)
    )


def _origin(request: HttpRequest) -> bool:
    origin = request.headers.get("Origin")
    if origin is None:
        return True  # Native fetch has no browser Origin header.
    try:
        incoming = urlsplit(origin)
        expected = urlsplit(f"{request.scheme}://{request.get_host()}")
        return (
            incoming.scheme in {"http", "https"}
            and incoming.username is None
            and incoming.password is None
            and not incoming.path
            and not incoming.query
            and not incoming.fragment
            and incoming.scheme == expected.scheme
            and incoming.hostname == expected.hostname
            and (
                (443 if incoming.scheme == "https" else 80)
                if incoming.port is None
                else incoming.port
            )
            == (
                (443 if expected.scheme == "https" else 80)
                if expected.port is None
                else expected.port
            )
        )
    except ValueError:
        return False


async def authorize(request: HttpRequest) -> Access:
    """Validate request scope and fresh Django auth before broker admission.

    Args:
        request: Incoming request; cached user and session are not trusted here.

    Returns:
        Immutable actual-cookie authority and server configuration.

    Raises:
        RealtimeDenied: For disabled, malformed, cross-origin or unauthorized use.
    """
    config = get_realtime_config()
    if config is None:
        raise RealtimeDenied(404)
    if request.method != "GET":
        raise RealtimeDenied(405)
    expected = request.headers.get(EXPECTED_SESSION_HEADER)
    if (
        request.headers.get(CLIENT_CONTRACT_HEADER) != CLIENT_CONTRACT
        or not valid_expected_binding(expected)
        or request.META.get("QUERY_STRING", "")
        or not _origin(request)
    ):
        raise RealtimeDenied(403)
    key = request.COOKIES.get(settings.SESSION_COOKIE_NAME)
    identity = await fresh_identity_async(key)
    if identity is None:
        raise RealtimeDenied(401)
    if not constant_time_compare(identity.binding, expected):
        raise RealtimeDenied(403)
    return Access(config, identity, key)


def topics_for(identity: Identity) -> tuple[str, ...]:
    """Select private principal and configured template aliases, never user input.

    Args:
        identity: Freshly authorized server-side principal.

    Returns:
        Deduplicated private and shared UI topic tuple.
    """
    aliases = set()
    for source in settings.HYPERVIEW.get("SOURCES", ()):
        if (
            isinstance(source, dict)
            and source.get("BACKEND")
            == "dj_hyperview.contrib.database.sources.DatabaseSource"
        ):
            alias = source.get("OPTIONS", {}).get("using")
            if alias is None:
                model = apps.get_model("dj_hyperview_database", "HyperviewTemplate")
                alias = router.db_for_read(model)
            aliases.add(alias)
    return (private_topic(identity.using, identity.user_id),) + tuple(
        ui_topic(alias) for alias in sorted(aliases)
    )
