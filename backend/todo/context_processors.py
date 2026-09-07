"""Template context shared by every server-driven screen."""

from django.http import HttpRequest

from .theme import DEFAULT_THEME, THEMES, palette

# The sign-in and session-expired screens render for an ANONYMOUS request, so no
# profile exists to read and a dark-mode user would otherwise be handed a
# full-brightness white screen the moment their session lapsed. The cookie is a
# fallback only: an authenticated profile always wins, so a preference changed on
# another device is never overridden by a stale copy here. Nothing sensitive rides
# in it, and an attacker-controlled value can only ever select a palette that
# already ships, because `palette()` falls back to light for anything unknown.
THEME_COOKIE = "theme"
THEME_COOKIE_MAX_AGE = 60 * 60 * 24 * 365


def theme(request: HttpRequest) -> dict[str, object]:
    """Publish the colour tokens this request should be painted with.

    dj-hyperview inherits the consumer's TEMPLATES OPTIONS wholesale
    (dj_hyperview/engine.py pops only loaders) and renders through
    backends.django.Template.render(context, request), so a context
    processor reaches every HXML document with no view change at all.

    getattr(user, "profile", None) is the whole fallback for accounts that
    predate migration 0003: Django's RelatedObjectDoesNotExist inherits from
    AttributeError, so it returns None, and AnonymousUser returns None too.

    Args:
        request: Incoming request, authenticated or not.

    Returns:
        The resolved palette, plus the name of the theme that produced it so the
        switcher can mark its own current option.
    """
    profile = getattr(getattr(request, "user", None), "profile", None)
    stored = getattr(profile, "theme", "") or ""
    if stored not in THEMES:
        stored = request.COOKIES.get(THEME_COOKIE, "")
    name = stored if stored in THEMES else DEFAULT_THEME
    return {"theme": palette(name), "theme_name": name}
