"""Request middleware owned by the TODO application."""

from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.utils import translation

from .context_processors import theme
from .recovery import is_recovery

# App-specific on purpose. Hyperview owns the X-Hyperview-* namespace for its own
# request headers (services/dom/parser.ts:120-128) and a future version could claim
# a response header there.
THEME_HEADER = "X-HyperTodo-Theme"


class ProfileLanguageMiddleware:
    """Let a stored account preference outrank the Accept-Language header.

    Django 6.1's get_language_from_request resolves cookie, then
    Accept-Language, then LANGUAGE_CODE (trans_real.py); session-based
    language selection is gone. Nothing in that chain can express "this account
    asked for Spanish", so LocaleMiddleware runs first for the header parsing,
    Content-Language and the Vary patch, and this overrides the result.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        """Store the next handler in the chain.

        Args:
            get_response: Next middleware or view.
        """
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Activate the account's stated language, if it stated one.

        Args:
            request: Incoming request, authenticated or not.

        Returns:
            The downstream response.
        """
        if request.path == "/realtime/events/":
            return self.get_response(request)
        if is_recovery(request):
            request.LANGUAGE_CODE = settings.LANGUAGE_CODE
            with translation.override(settings.LANGUAGE_CODE):
                response = self.get_response(request)
                response.headers["Content-Language"] = settings.LANGUAGE_CODE
                return response
        profile = getattr(getattr(request, "user", None), "profile", None)
        stored = getattr(profile, "language", "") or ""
        if stored in dict(settings.LANGUAGES):
            translation.activate(stored)
            # LocaleMiddleware already set this from the header. Leaving it stale
            # renders the WRONG option as current while every other string on the
            # screen is right, which is the hardest kind of bug to spot.
            request.LANGUAGE_CODE = translation.get_language()
        return self.get_response(request)


class ThemeHeaderMiddleware:
    """Tell the native shell which palette the response it is holding was painted with.

    The client owns four surfaces no HXML document can reach -- both safe-area
    insets, the splash overlay and the two full-screen failure states -- so without
    a channel it hardcodes the light palette and a dark screen sits on a #F7F8FC
    strip. This is that channel, and it is deliberately the whole of it: the
    colours themselves live in mobile/src/theme.ts, pinned to this repo by
    tests/test_theme_client_tokens.py, because shipping ten hexes on every
    response would put presentation in a transport header and buy nothing that test
    does not already guarantee.

    Additive by construction. Nothing in hyperview reads an unknown response
    header (services/dom/parser.ts:176-181 reads Content-Type and
    X-Response-Stale-Reason and nothing else), so a binary that predates the client
    half keeps its hardcoded light shell and behaves exactly as it does today.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        """Store the next handler in the chain.

        Args:
            get_response: Next middleware or view.
        """
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Name the palette this response's body already resolved.

        Calls the same theme() the context processor does rather than
        reimplementing the profile-then-cookie order, and reads it AFTER the view,
        by which point Django has already rendered the TemplateResponse
        (BaseHandler._get_response). The header can therefore only ever agree
        with the stylesheet it ships with.

        Args:
            request: Incoming request, authenticated or not.

        Returns:
            The downstream response, now naming its own palette.
        """
        response = self.get_response(request)
        if request.path != "/realtime/events/" and not is_recovery(request):
            response.headers[THEME_HEADER] = theme(request)["theme_name"]
        return response
