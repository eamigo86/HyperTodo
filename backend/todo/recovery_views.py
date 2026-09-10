"""Public navigator and login rendering under the guarded recovery scope."""

from django.http import HttpRequest, HttpResponse

from .forms import LoginForm
from .recovery import is_recovery
from .views import _template_response, hxml_endpoint


@hxml_endpoint
def recovery_view(request: HttpRequest) -> HttpResponse:
    """Render the exact neutral route selected by the presentation guard.

    Args:
        request: Original cookie/session request with validated recovery scope.

    Returns:
        Existing public navigator or login document; never a private dashboard.
    """
    if not is_recovery(request):
        # Defense in depth for a custom URL configuration without the guard.
        return HttpResponse(status=404)
    if request.GET.get("screen") == "login":
        return _template_response(
            request, "screens/login.xml", {"form": LoginForm(), "optin_default": "off"}
        )
    return _template_response(request, "screens/root.xml")
