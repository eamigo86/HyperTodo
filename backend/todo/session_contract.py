"""Opaque cookie-session identity metadata for the opt-in realtime contract."""

import base64
import json
import re
from typing import Literal

from django.http import HttpRequest, HttpResponse
from django.utils.crypto import constant_time_compare, salted_hmac

CLIENT_CONTRACT_HEADER = "X-HyperTodo-Client-Contract"
CLIENT_CONTRACT = "realtime-v1"
EXPECTED_SESSION_HEADER = "X-HyperTodo-Expected-Session"
SESSION_BINDING_HEADER = "X-HyperTodo-Session-Binding"
AUTH_OUTCOME_HEADER = "X-HyperTodo-Auth-Outcome"
SESSION_STATE_PATH = "/hv/session-state/"
_BINDING_PATTERN = re.compile(r"hvs1\.[A-Za-z0-9_-]{43}")
AuthOutcome = Literal[
    "password-ok",
    "password-invalid",
    "biometric-ok",
    "biometric-invalid",
    "biometric-throttled",
    "logout-ok",
]


def session_binding(request: HttpRequest) -> str:
    """Identify actual Django authentication without exposing its inputs.

    Evaluating the lazy user preserves Django's invalid-session cleanup and
    fallback-key rotation. This function never allocates a session itself.

    Args:
        request: Request after Django authentication middleware.

    Returns:
        Versioned, unpadded base64url SHA-256 HMAC; not a credential.
    """
    user = request.user
    identity = (
        [1, user._state.db, str(user.pk), request.session.session_key]
        if user.is_authenticated
        else [1, None, None, None]
    )
    payload = json.dumps(identity, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )
    digest = salted_hmac(
        "hypertodo.session-binding.v1", payload, algorithm="sha256"
    ).digest()
    return "hvs1." + base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def valid_expected_binding(value: str | None) -> bool:
    """Require the exact bounded ASCII binding format.

    Args:
        value: Untrusted expected-session header.

    Returns:
        Whether the complete value has the protocol format.
    """
    return value is not None and _BINDING_PATTERN.fullmatch(value) is not None


def expected_session_matches(request: HttpRequest, expected: str) -> bool:
    """Compare a formatted expectation to actual cookie state in constant time.

    Args:
        request: Request authenticated by Django, never by this header.
        expected: Previously format-checked client expectation.

    Returns:
        Whether the actual incoming session matches the expectation.
    """
    return constant_time_compare(session_binding(request), expected)


def attach_auth_outcome(
    request: HttpRequest, response: HttpResponse, outcome: AuthOutcome
) -> None:
    """Tag only an explicitly selected auth branch for modern requests.

    Args:
        request: Request negotiated by the session-contract middleware.
        response: Existing auth response whose body/status remain unchanged.
        outcome: Literal selected by the owning auth branch, not inferred.
    """
    if getattr(request, "hv_realtime_v1", False):
        response[AUTH_OUTCOME_HEADER] = outcome
