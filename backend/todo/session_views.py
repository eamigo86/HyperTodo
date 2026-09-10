"""Read-only confirmation of the effective Django cookie session."""

from django.http import HttpRequest, JsonResponse

from .session_contract import session_binding


def session_state(request: HttpRequest) -> JsonResponse:
    """Confirm negotiated cookie state without application-owned writes.

    The middleware enforces modern-contract GET before dispatch. Django may
    still sanitize invalid authentication or rotate a fallback security key.

    Args:
        request: Negotiated GET after Django authentication.

    Returns:
        Only protocol version, actual authentication flag and opaque binding.
    """
    binding = session_binding(request)
    return JsonResponse(
        {
            "version": 1,
            "authenticated": request.user.is_authenticated,
            "binding": binding,
        }
    )
