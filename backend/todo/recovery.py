"""Neutral presentation scope; never authority over the actual cookie session."""

from typing import Any

from django import forms
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.http import HttpRequest
from django.middleware.csrf import get_token

from .session_contract import CLIENT_CONTRACT

RECOVERY_HEADER = "X-HyperTodo-Recovery"
RECOVERY_VERSION = "login-v1"
RECOVERY_PATH = "/hv/recovery/"
RECOVERY_LOGIN = RECOVERY_PATH + "?screen=login"
_MARKER = object()
_PUBLIC_FIELDS = frozenset(
    {
        "optin_default",
        "biometric",
        "biometric_error",
        "biometric_token",
        "message",
        "realtime_enabled",
        "realtime_request_id",
        "realtime_fragment",
        "realtime_target",
        "realtime_resources",
        "realtime_mode",
    }
)


def recovery_error(request: HttpRequest, contract: str | None) -> str | None:
    """Validate the exact presentation selector without reading account data.

    Args:
        request: Original request before application middleware/views.
        contract: Existing modern contract header value.

    Returns:
        A bounded rejection code, or None for normal/valid recovery scope.
    """
    value = request.headers.get(RECOVERY_HEADER)
    if value is None:
        return "recovery-required" if request.path_info == RECOVERY_PATH else None
    if contract != CLIENT_CONTRACT or value != RECOVERY_VERSION:
        return "invalid-recovery-contract"
    query = request.META.get("QUERY_STRING", "")
    if request.method == "GET":
        if request.path_info == RECOVERY_PATH and query in {"", "screen=login"}:
            return None
        if request.path_info == "/hv/session-state/" and not query:
            return None
    elif (
        request.method == "POST"
        and request.path_info in {"/hv/login/", "/hv/biometric/login/"}
        and not query
    ):
        return None
    return "invalid-recovery-scope"


def mark_recovery(request: HttpRequest) -> None:
    """Mark a scope only after the original request passes the session guard.

    Args:
        request: Validated original request; no session/user mutation occurs.
    """
    request._hv_neutral_recovery = _MARKER


def is_recovery(request: HttpRequest) -> bool:
    """Check the private guard marker, never a caller-controlled header alone.

    Args:
        request: A request whose presentation scope may be guarded.

    Returns:
        Whether this exact request received the private marker.
    """
    return getattr(request, "_hv_neutral_recovery", None) is _MARKER


def neutral_render_context(
    request: HttpRequest, context: dict[str, Any]
) -> tuple[HttpRequest, dict[str, Any]]:
    """Project public presentation without retaining an actual request or Form.

    Args:
        request: Original guarded request, used only for Django's masked CSRF.
        context: View-selected public messages and auth result values.

    Returns:
        A fresh anonymous render request and allowlisted value-only context.
    """
    public_request = HttpRequest()
    public_request.method = "GET"
    public_request.path = public_request.path_info = RECOVERY_PATH
    public_request.user = AnonymousUser()
    public_request.session = {}
    public_request.LANGUAGE_CODE = settings.LANGUAGE_CODE
    public = {key: value for key, value in context.items() if key in _PUBLIC_FIELDS}
    form = context.get("form")
    if isinstance(form, forms.Form):
        # Errors were already computed by the actual Django authentication view.
        # Only the username presentation is echoed, never bound password data.
        public["form"] = {
            "username": {"value": str(form["username"].value() or "")},
            "errors": bool(form.errors),
            "non_field_errors": list(form.non_field_errors()),
        }
    masked = get_token(request)
    public.update(
        recovery_csrf_token=masked,
        csrf_token=masked,
        route_id="root-route",
        route_href=RECOVERY_LOGIN,
        home_href=RECOVERY_PATH,
        realtime_refresh_href=RECOVERY_LOGIN,
    )
    return public_request, public
