"""Negotiate realtime session expectations before application side effects."""

from collections.abc import Callable

from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseNotAllowed,
    HttpResponseNotFound,
    JsonResponse,
)
from django.utils.cache import patch_cache_control, patch_vary_headers

from .recovery import RECOVERY_HEADER, is_recovery, mark_recovery, recovery_error
from .session_contract import (
    AUTH_OUTCOME_HEADER,
    CLIENT_CONTRACT,
    CLIENT_CONTRACT_HEADER,
    EXPECTED_SESSION_HEADER,
    SESSION_BINDING_HEADER,
    SESSION_STATE_PATH,
    expected_session_matches,
    session_binding,
    valid_expected_binding,
)


def _error(code: str, status: int) -> JsonResponse:
    """Return bounded non-personal negotiation errors without disclosing state."""
    response = JsonResponse({"error": code}, status=status)
    patch_cache_control(response, no_store=True)
    patch_vary_headers(response, ["Cookie", CLIENT_CONTRACT_HEADER, RECOVERY_HEADER])
    return response


def _mark_response(request: HttpRequest, response: HttpResponse) -> HttpResponse:
    """Mark only this guarded response for post-persistence trusted metadata."""
    # Resolve lazy auth now so builtin cleanup precedes session response handling.
    _ = request.user.is_authenticated
    request._hv_session_response = (response, response.status_code)
    patch_cache_control(response, no_store=True)
    patch_vary_headers(response, ["Cookie", CLIENT_CONTRACT_HEADER, RECOVERY_HEADER])
    return response


class SessionContractMiddleware:
    """Guard only modern /hv/ requests; preserve legacy and Admin contracts."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        """Store the downstream handler.

        Args:
            get_response: Remaining middleware and view handler.
        """
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Check expectations before views and publish resulting session metadata.

        Args:
            request: Request after SessionMiddleware and AuthenticationMiddleware.

        Returns:
            Negotiation rejection or unchanged downstream body/status plus metadata.
        """
        contract = request.headers.get(CLIENT_CONTRACT_HEADER)
        if code := recovery_error(request, contract):
            return _error(code, 404 if code == "recovery-required" else 400)
        if not request.path_info.startswith("/hv/"):
            return self.get_response(request)
        if contract is None:
            if request.path_info == SESSION_STATE_PATH:
                return HttpResponseNotFound()
            return self.get_response(request)
        if contract != CLIENT_CONTRACT:
            return _error("unsupported-client-contract", 400)
        request.hv_realtime_v1 = True
        if request.path_info == SESSION_STATE_PATH:
            # Method rejection never reaches a view or changes CSRF policy for
            # any mutation endpoint. Only GET can perform confirmation.
            if request.method != "GET":
                return _mark_response(request, HttpResponseNotAllowed(["GET"]))
        else:
            expected = request.headers.get(EXPECTED_SESSION_HEADER)
            if not valid_expected_binding(expected):
                return _error("invalid-session-binding", 400)
            if not expected_session_matches(request, expected):
                return _error("session-binding-mismatch", 409)
        if request.headers.get(RECOVERY_HEADER) is not None:
            mark_recovery(request)
        return _mark_response(request, self.get_response(request))


class SessionBindingResponseMiddleware:
    """Finalize binding only after Django has persisted the resulting session.

    Install before SessionMiddleware so response order is reversed. Keeping the
    marker on the request detects replacement responses from failed persistence.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        """Store the downstream handler.

        Args:
            get_response: Handler including Django session persistence.
        """
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Attach resulting metadata without allocating or saving a session.

        Args:
            request: Request whose inner guard may mark one modern response.

        Returns:
            The final response, never claiming a replaced auth result succeeded.
        """
        response = self.get_response(request)
        marker = getattr(request, "_hv_session_response", None)
        if marker is not None:
            guarded_response, guarded_status = marker
            patch_cache_control(response, no_store=True)
            patch_vary_headers(
                response, ["Cookie", CLIENT_CONTRACT_HEADER, RECOVERY_HEADER]
            )
            if (
                response is guarded_response
                and response.status_code == guarded_status
                and not (is_recovery(request) and response.status_code >= 500)
            ):
                response[SESSION_BINDING_HEADER] = session_binding(request)
            else:
                # A replaced result or neutral 5xx cannot claim persistence:
                # Django skips session.save on 5xx. Do not expose an in-memory
                # auth binding; subsequent confirmation observes actual state.
                response.headers.pop(AUTH_OUTCOME_HEADER, None)
                response.headers.pop(SESSION_BINDING_HEADER, None)
        return response
